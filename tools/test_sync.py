#!/usr/bin/env python3
"""
test_sync.py - end-to-end tests for the sync chain, against BOTH native implementations.

Every scenario is one of the audit's area-06 reproductions, run against local bare remotes:

  bash        sync-memory.sh  - the default on macOS / Linux
  powershell  sync-memory.ps1 - the default on Windows (what the dispatcher runs there)
  --impl all  both; a requested implementation that is missing is a failure, not a skip

On Windows it runs with `powershell` (5.1), the implementation the dispatcher uses there; CI runs
that column on every change (tests.yml, windows-sync). It also covers a protected default branch
and the pull-request mode of sync-memory.py.

    py tools/test_sync.py            # Windows
    python3 tools/test_sync.py       # macOS / Linux
"""
import json
import os
import shutil
import socket
import time
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testpolicy  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
RESULTS = []
EMAIL = "alex@example.test"


def ok(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + str(detail)) if detail else ""))


def clean_env(extra=None):
    e = {k: v for k, v in os.environ.items()
         if not k.startswith(("MEMORY_", "CLAUDE", "KIRO_", "CURSOR_", "GIT_"))}
    e.update({"GIT_AUTHOR_NAME": "K", "GIT_COMMITTER_NAME": "K", "GIT_AUTHOR_EMAIL": EMAIL,
              "GIT_COMMITTER_EMAIL": EMAIL, "MEMORY_SYNC_QUIET": "0"})
    e.update(extra or {})
    return e


def git(cwd, *a, env=None):
    p = subprocess.run(["git", *a], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                       env=env or clean_env())
    return p.stdout.strip()


def ps_shell():
    for c in ("powershell", "pwsh"):
        if shutil.which(c):
            return shutil.which(c)
    return None


def run_native(impl, notes_root, mode, env=None):
    if impl == "bash":
        cmd = [shutil.which("bash"), os.path.join(notes_root, "scripts", "sync-memory.sh"), mode]
    else:
        cmd = [ps_shell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
               os.path.join(notes_root, "scripts", "sync-memory.ps1"), mode]
    p = subprocess.run(cmd, cwd=notes_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                       env=clean_env(env))
    return p.returncode, p.stdout + p.stderr


NOTE = """---
title: {t}
type: note
tags: [t]
---

# {t}

A note.

## Observations
- [fact] {t} exists

## Relations
- relates_to [[Core]]
"""


def install_tier(root, prefix=""):
    """A notes tier at root/prefix with this repo's scripts and policy."""
    nr = os.path.join(root, prefix) if prefix else root
    os.makedirs(os.path.join(nr, "scripts"), exist_ok=True)
    for f in ("sync-memory.sh", "sync-memory.ps1", "sync-memory.py", "memory_guard.py", "mem.py"):
        shutil.copy(os.path.join(SCRIPTS, f), os.path.join(nr, "scripts", f))
    os.makedirs(os.path.join(nr, "governance"), exist_ok=True)
    testpolicy.install(os.path.join(nr, "governance"))
    os.makedirs(os.path.join(nr, ".basic-memory"), exist_ok=True)
    with open(os.path.join(nr, ".basic-memory", "project.json"), "w") as fh:
        json.dump({"name": "sync-test", "kind": "project" if prefix else "team"}, fh)
    os.makedirs(os.path.join(nr, "context"), exist_ok=True)
    os.makedirs(os.path.join(nr, "log", "journal"), exist_ok=True)
    with open(os.path.join(nr, ".gitignore"), "w", newline="\n") as fh:
        fh.write(".memory/\n__pycache__/\n")  # as every real tier has (the guard refuses .memory/)
    return nr


def make_remote(tmp, name, prefix=""):
    """bare remote + clone A with one committed note. Returns (bare, clone_a, notes_root_a)."""
    bare = os.path.join(tmp, name + ".git")
    git(tmp, "init", "-q", "--bare", "-b", "main", bare)
    a = os.path.join(tmp, name + "-a")
    os.makedirs(a)
    git(a, "init", "-q", "-b", "main")
    git(a, "config", "user.email", EMAIL)
    git(a, "config", "user.name", "K")
    nr = install_tier(a, prefix)
    with open(os.path.join(nr, "context", "note.md"), "w", newline="\n") as fh:
        fh.write(NOTE.format(t="Note"))
    subprocess.run([sys.executable, os.path.join(nr, "scripts", "memory_guard.py"), "--notes-root", nr, "stamp", "--all"],
                   cwd=a, env=clean_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    git(a, "add", "-A")
    git(a, "commit", "-qm", "base")
    git(a, "remote", "add", "origin", bare)
    git(a, "push", "-q", "-u", "origin", "main")
    return bare, a, nr


def clone(tmp, bare, name, prefix=""):
    d = os.path.join(tmp, name)
    git(tmp, "clone", "-q", bare, d)
    git(d, "config", "user.email", EMAIL)
    git(d, "config", "user.name", "K")
    return d, (os.path.join(d, prefix) if prefix else d)


PROTECT_HOOK = """#!/bin/sh
# emulates GitHub branch protection: refuse direct updates to main unless ALLOW_MAIN is set
while read old new ref; do
  if [ "$ref" = "refs/heads/main" ] && [ -z "$ALLOW_MAIN" ]; then
    echo "error: GH006: Protected branch update failed for refs/heads/main." >&2; exit 1
  fi
done
exit 0
"""


def protect(bare):
    hook = os.path.join(bare, "hooks", "pre-receive")
    with open(hook, "w", newline="\n") as fh:
        fh.write(PROTECT_HOOK)
    os.chmod(hook, 0o755)


def remote_count(bare, rng):
    out = subprocess.run(["git", "--git-dir", bare, "rev-list", "--count", rng], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True).stdout.strip()
    return int(out) if out.isdigit() else -1


def new_note(nr, name):
    os.makedirs(os.path.join(nr, "log", "journal"), exist_ok=True)
    with open(os.path.join(nr, "log", "journal", name + ".md"), "w", newline="\n") as fh:
        fh.write(NOTE.format(t=name.replace("-", " ").title()))


def append(path, text):
    with open(path, "a", newline="\n") as fh:
        fh.write(text)


def scenarios(impl, tmp):
    print("\n=== %s ===" % impl)
    T = lambda n: os.path.join(tmp, impl + "-" + n)
    for n in ("happy", "scope", "fail", "conflict", "autostash", "ahead", "detached", "upstream", "staging", "secret", "protected"):
        os.makedirs(T(n))

    # happy path
    bare, a, nr = make_remote(T("happy"), "r")
    append(os.path.join(nr, "context", "note.md"), "\nMore.\n")
    rc, out = run_native(impl, nr, "post")
    remote_head = git(T("happy"), "--git-dir", bare, "log", "-1", "--format=%s", "main")
    ok("post commits a note change and pushes it", rc == 0 and remote_head.startswith("memory: 1 file"), (rc, out[-200:]))

    # 06-F1 out-of-tier staged file in a project tier
    bare, a, nr = make_remote(T("scope"), "r", prefix="memory")
    os.makedirs(os.path.join(a, "app"), exist_ok=True)
    append(os.path.join(a, "app", ".env"), "TOKEN=abc\n")
    git(a, "add", "app/.env")
    append(os.path.join(nr, "context", "note.md"), "\nMore.\n")
    rc, out = run_native(impl, nr, "post")
    committed = git(a, "show", "--name-only", "--format=", "HEAD").split()
    remote_tree = git(T("scope"), "--git-dir", bare, "ls-tree", "-r", "--name-only", "main").split()
    ok("06-F1: a file staged outside the tier is neither committed nor pushed", rc == 0 and "app/.env" not in committed
       and "app/.env" not in remote_tree and committed == ["memory/context/note.md"], (rc, committed, out[-200:]))
    ok("06-F1/F11: ...and it is still staged afterwards (the user's index is untouched)",
       "app/.env" in git(a, "diff", "--cached", "--name-only").split())

    # 06-F4 missing guard fails closed
    bare, a, nr = make_remote(T("fail"), "r")
    os.remove(os.path.join(nr, "scripts", "memory_guard.py"))
    append(os.path.join(nr, "context", "note.md"), "\nMore.\n")
    before = git(a, "rev-parse", "HEAD")
    rc, out = run_native(impl, nr, "post")
    ok("06-F4: a missing guard is exit 6 and nothing is committed", rc == 6 and git(a, "rev-parse", "HEAD") == before, (rc, out[-160:]))

    # conflicts: two clones
    bare, a, nr = make_remote(T("conflict"), "r")
    b, nrb = clone(T("conflict"), bare, "b")
    append(os.path.join(nrb, "context", "note.md"), "\nFrom B.\n")
    git(b, "commit", "-qam", "b")
    git(b, "push", "-q")
    append(os.path.join(nr, "context", "note.md"), "\nFrom A.\n")
    git(a, "commit", "-qam", "a")
    rc, out = run_native(impl, nr, "pre")
    ok("two clones editing the same line: pre stops with exit 2 and names the file", rc == 2 and "context/note.md" in out, (rc, out[-200:]))

    # 06-F5 autostash conflict
    bare, a, nr = make_remote(T("autostash"), "r")
    b, nrb = clone(T("autostash"), bare, "b")
    append(os.path.join(nrb, "context", "note.md"), "\nFrom B.\n")
    git(b, "commit", "-qam", "b")
    git(b, "push", "-q")
    append(os.path.join(nr, "context", "note.md"), "\nUncommitted A.\n")  # unstaged edit, same place
    rc, out = run_native(impl, nr, "pre")
    ok("06-F5: an autostash that cannot re-apply is exit 2, not 'memory synced'", rc == 2 and "memory synced" not in out, (rc, out[-200:]))

    # 06-F6 unrelated ahead commit in a project tier
    bare, a, nr = make_remote(T("ahead"), "r", prefix="memory")
    os.makedirs(os.path.join(a, "app"), exist_ok=True)
    append(os.path.join(a, "app", "code.txt"), "x\n")
    git(a, "add", "app/code.txt")
    git(a, "commit", "-qm", "app work")
    rc, out = run_native(impl, nr, "post")
    remote_log = git(T("ahead"), "--git-dir", bare, "log", "--format=%s", "main")
    ok("06-F6: a no-op memory post does not push an unrelated application commit", rc == 0 and "app work" not in remote_log, (rc, out[-160:]))

    # 06-F8 detached HEAD
    bare, a, nr = make_remote(T("detached"), "r")
    git(a, "checkout", "-q", "--detach")
    append(os.path.join(nr, "context", "note.md"), "\nMore.\n")
    before = git(a, "rev-parse", "HEAD")
    rc, out = run_native(impl, nr, "post")
    ok("06-F8: a detached HEAD is refused (exit 1) before anything is committed",
       rc == 1 and "detached" in out.lower() and git(a, "rev-parse", "HEAD") == before, (rc, out[-160:]))

    # 06-F9 upstream with a different name
    bare, a, nr = make_remote(T("upstream"), "r")
    git(a, "checkout", "-q", "-b", "work")
    git(a, "branch", "-q", "--set-upstream-to=origin/main")
    append(os.path.join(nr, "context", "note.md"), "\nOn work.\n")
    rc, out = run_native(impl, nr, "post")
    remote_head = git(T("upstream"), "--git-dir", bare, "log", "-1", "--format=%s", "main")
    ok("06-F9: a branch tracking a differently named upstream pushes to that upstream", rc == 0 and remote_head.startswith("memory:"), (rc, out[-200:]))

    # 06-F11 a blocked post keeps the user's staging
    bare, a, nr = make_remote(T("staging"), "r")
    append(os.path.join(nr, "context", "note.md"), "\nStaged by me.\n")
    git(a, "add", "context/note.md")
    with open(os.path.join(nr, "context", "bad.md"), "w") as fh:
        fh.write("no frontmatter, no relations\n")
    rc, out = run_native(impl, nr, "post")
    ok("06-F11: a blocked post (exit 5) leaves the user's prior staging exactly as it was",
       rc == 5 and git(a, "diff", "--cached", "--name-only").split() == ["context/note.md"], (rc, out[-160:]))

    # in-tier secret file
    bare, a, nr = make_remote(T("secret"), "r")
    append(os.path.join(nr, "context", ".env"), "TOKEN=abc\n")
    before = git(a, "rev-parse", "HEAD")
    rc, out = run_native(impl, nr, "post")
    ok("an in-tier .env is exit 3 and nothing is committed", rc == 3 and git(a, "rev-parse", "HEAD") == before, (rc, out[-160:]))

    # protected default branch: the native script refuses to retry and says so with exit 7
    bare, a, nr = make_remote(T("protected"), "r")
    protect(bare)
    new_note(nr, "2026-10-06-protected")
    rc, out = run_native(impl, nr, "post")
    ok("a push refused by a protected branch is exit 7, the commit kept locally, main untouched",
       rc == 7 and git(a, "rev-list", "--count", "@{u}..HEAD") == "1" and remote_count(bare, "main") == 1, (rc, out[-200:]))
    new_note(nr, "2026-10-07-commit-only")
    rc, out = run_native(impl, nr, "post", env={"MEMORY_SYNC_DIRECT_PUSH": "0"})
    ok("MEMORY_SYNC_DIRECT_PUSH=0 commits and rebases but attempts no push",
       rc == 0 and git(a, "rev-list", "--count", "@{u}..HEAD") == "2" and "GH006" not in out, (rc, out[-200:]))


def dispatcher_tests(tmp):
    print("\n=== dispatcher (sync-memory.py) ===")
    d = os.path.join(tmp, "disp")
    os.makedirs(d)
    bare, a, nr = make_remote(d, "r")
    disp = os.path.join(nr, "scripts", "sync-memory.py")
    for argv, label in (([], "no argument"), (["PRE"], "PRE"), (["pre"], "pre")):
        shutil.rmtree(os.path.join(nr, ".memory"), ignore_errors=True)
        p = subprocess.run([sys.executable, disp, *argv], cwd=nr, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, env=clean_env())
        ok("06-F10: '%s' runs pre and refreshes the pack" % label, p.returncode == 0 and
           os.path.isfile(os.path.join(nr, ".memory", "pack", "claims.jsonl")), (p.returncode, (p.stdout + p.stderr)[-160:]))
    lock = os.path.join(git(a, "rev-parse", "--absolute-git-dir"), "sync-memory.lock")
    os.mkdir(lock)
    shutil.rmtree(os.path.join(nr, ".memory"), ignore_errors=True)
    p = subprocess.run([sys.executable, disp, "pre"], cwd=nr, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, env=clean_env())
    ok("06-F7: a held lock is exit 75 and no pack work runs", p.returncode == 75 and
       not os.path.isdir(os.path.join(nr, ".memory", "pack")), p.returncode)
    os.rmdir(lock)
    p = subprocess.run([sys.executable, disp, "bogus"], cwd=nr, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, env=clean_env())
    ok("an unknown mode is a usage error (64)", p.returncode == 64, p.returncode)
    head = git(a, "rev-parse", "HEAD")
    with open(os.path.join(nr, "scripts", "\u00e9vil.py"), "w") as fh:
        fh.write("print(1)\n")
    p = subprocess.run([sys.executable, disp, "post", "--agent"], cwd=nr, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, env=clean_env({"MEMORY_SYNC_NO_GH": "1"}))
    ok("recheck U1: an agent's post of scripts/\u00e9vil.py is refused (4) and nothing is committed",
       p.returncode == 4 and git(a, "rev-parse", "HEAD") == head, (p.returncode, (p.stdout + p.stderr)[-200:]))
    os.remove(os.path.join(nr, "scripts", "\u00e9vil.py"))
    pr_mode_tests(tmp)
    squash_and_index_tests(tmp)


FAKE_GH = """import os, sys
log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gh.log")
open(log, "a").write(" ".join(sys.argv[1:3]) + "\\n")
flag = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pr.open")
if sys.argv[1:3] == ["pr", "list"]:
    if os.path.exists(flag):
        print("https://github.com/example/repo/pull/7")
elif sys.argv[1:3] == ["pr", "create"]:
    open(flag, "w").close()
    print("https://github.com/example/repo/pull/7")
"""


def pr_mode_tests(tmp):
    """The protected-branch path end to end, through the dispatcher (the platform's native script)."""
    print("\n=== pull-request mode (sync-memory.py) ===")
    d = os.path.join(tmp, "prmode")
    os.makedirs(d)
    bare, a, nr = make_remote(d, "r")
    protect(bare)
    disp = os.path.join(nr, "scripts", "sync-memory.py")

    def post(extra=None):
        p = subprocess.run([sys.executable, disp, "post", "--agent"], cwd=nr, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, env=clean_env(dict({"MEMORY_SYNC_NO_GH": "1"}, **(extra or {}))))
        return p.returncode, p.stdout + p.stderr

    new_note(nr, "2026-10-06-one")
    rc, out = post()
    ok("direct mode on a protected main falls back to memory/<who>: exit 0, one commit on the branch",
       rc == 0 and remote_count(bare, "main..memory/alex") == 1 and remote_count(bare, "main") == 1, (rc, out[-240:]))
    new_note(nr, "2026-10-07-two")
    rc, out = post()
    ok("the next turn adds to the same branch (one pull request per person)",
       rc == 0 and remote_count(bare, "main..memory/alex") == 2, (rc, out[-200:]))
    m = os.path.join(d, "merger")
    git(d, "clone", "-q", bare, m)
    git(m, "merge", "-q", "--squash", "origin/memory/alex")
    git(m, "commit", "-qm", "memory: notes from alex (#1)")
    git(m, "push", "-q", "origin", "main", env=clean_env({"ALLOW_MAIN": "1"}))
    p = subprocess.run([sys.executable, disp, "pre"], cwd=nr, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, env=clean_env())
    ok("after the pull request is squash-merged, pre leaves nothing unpushed",
       p.returncode == 0 and git(a, "rev-list", "--count", "@{u}..HEAD") == "0", (p.returncode, (p.stdout + p.stderr)[-200:]))
    git(m, "fetch", "-q")
    git(m, "switch", "-q", "-c", "foreign", "origin/memory/alex")
    new_note(os.path.join(m, os.path.relpath(nr, a)) if nr != a else m, "2026-10-08-foreign")
    git(m, "add", "-A")
    git(m, "commit", "-qm", "foreign")
    git(m, "push", "-q", "origin", "HEAD:memory/alex")
    before = subprocess.run(["git", "--git-dir", bare, "rev-parse", "memory/alex"], stdout=subprocess.PIPE, text=True).stdout.strip()
    new_note(nr, "2026-10-09-three")
    rc, out = post()
    after = subprocess.run(["git", "--git-dir", bare, "rev-parse", "memory/alex"], stdout=subprocess.PIPE, text=True).stdout.strip()
    ok("negative: a change on memory/<who> this machine lacks is never overwritten (exit 1)",
       rc == 1 and before == after and "not overwriting" in out, (rc, out[-200:]))
    # a clean second person, mode pr, with a fake GitHub CLI: one pull request created, then reused
    bin_dir = os.path.join(d, "bin")
    os.makedirs(bin_dir)
    with open(os.path.join(bin_dir, "gh.py"), "w") as fh:
        fh.write(FAKE_GH)
    if os.name == "nt":
        with open(os.path.join(bin_dir, "gh.cmd"), "w") as fh:
            fh.write('@"%s" "%%~dp0gh.py" %%*\n' % sys.executable)
    else:
        with open(os.path.join(bin_dir, "gh"), "w") as fh:
            fh.write('#!/bin/sh\nexec "%s" "$(dirname "$0")/gh.py" "$@"\n' % sys.executable)
        os.chmod(os.path.join(bin_dir, "gh"), 0o755)
    d2 = os.path.join(d, "second")
    os.makedirs(d2)
    bare2, _a2, nr2 = make_remote(d2, "r")
    protect(bare2)
    env2 = {"MEMORY_SYNC_MODE": "pr", "PATH": bin_dir + os.pathsep + os.environ.get("PATH", "")}
    disp2 = os.path.join(nr2, "scripts", "sync-memory.py")
    outs = []
    for name in ("2026-10-10-pr-one", "2026-10-11-pr-two"):
        new_note(nr2, name)
        p = subprocess.run([sys.executable, disp2, "post", "--agent"], cwd=nr2, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, env=clean_env(env2))
        outs.append((p.returncode, p.stdout + p.stderr))
    calls = open(os.path.join(bin_dir, "gh.log")).read().split("\n") if os.path.exists(os.path.join(bin_dir, "gh.log")) else []
    ok("mode pr: no direct push is attempted, one pull request is created and then reused",
       all(rc == 0 for rc, _ in outs) and calls.count("pr create") == 1 and all("GH006" not in o for _, o in outs)
       and "pull/7" in outs[-1][1] and remote_count(bare2, "main..memory/alex") == 2, (outs, calls))


def squash_and_index_tests(tmp):
    """Recheck P1, P2, N1, the lock owner and branch names: each is the recheck's reproduction."""
    print("\n=== squash merges, left-behind branches, the index, the lock ===")
    d = os.path.join(tmp, "squash")
    os.makedirs(d)
    bare, a, nr = make_remote(d, "r")
    protect(bare)
    disp = os.path.join(nr, "scripts", "sync-memory.py")
    note = os.path.join(nr, "context", "note.md")

    def run_disp(*argv, extra=None):
        p = subprocess.run([sys.executable, disp, *argv], cwd=nr, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, env=clean_env(dict({"MEMORY_SYNC_NO_GH": "1"}, **(extra or {}))))
        return p.returncode, p.stdout + p.stderr

    def squash_merge():
        m = os.path.join(d, "merger")
        if not os.path.isdir(m):
            git(d, "clone", "-q", bare, m)
        git(m, "fetch", "-q", "origin")
        git(m, "reset", "-q", "--hard", "origin/main")
        git(m, "merge", "-q", "--squash", "origin/memory/alex")
        git(m, "commit", "-qm", "memory: notes from alex (squashed)")
        git(m, "push", "-q", "origin", "main", env=clean_env({"ALLOW_MAIN": "1"}))

    append(note, "\nFirst edit.\n")
    run_disp("post")
    append(note, "\nSecond edit.\n")
    rc, out = run_disp("post")
    two = remote_count(bare, "main..memory/alex") == 2
    squash_merge()
    rc, out = run_disp("pre")
    ok("P1: after a squash merge of two edits to ONE file, pre does not conflict and nothing stays unpushed",
       two and rc == 0 and git(a, "rev-list", "--count", "@{u}..HEAD") == "0"
       and "Second edit." in open(note).read(), (rc, out[-300:]))
    append(note, "\nThird edit.\n")
    before = subprocess.run(["git", "--git-dir", bare, "rev-parse", "memory/alex"], stdout=subprocess.PIPE, text=True).stdout.strip()
    rc, out = run_disp("post")
    after = subprocess.run(["git", "--git-dir", bare, "rev-parse", "memory/alex"], stdout=subprocess.PIPE, text=True).stdout.strip()
    ok("P2: the branch the squashed pull request left behind is reused, not a wall",
       rc == 0 and after != before and after == git(a, "rev-parse", "HEAD") and "not overwriting" not in out, (rc, out[-300:]))
    append(note, "\nFourth edit, local only.\n")
    run_disp("post", extra={"MEMORY_SYNC_NO_PUSH": "1"})
    squash_merge()   # merges the third edit only
    rc, out = run_disp("pre")
    ok("P1: with one more local commit on top, pre replays only that one",
       rc == 0 and git(a, "rev-list", "--count", "@{u}..HEAD") == "1" and "Fourth edit" in open(note).read()
       and "Third edit." in open(note).read(), (rc, out[-300:], git(a, "log", "--oneline", "-5")))

    # the person's branch name: two addresses with the same local part never share a branch
    probe = ("import importlib.util, sys\n"
             "spec = importlib.util.spec_from_file_location('sm', %r)\n"
             "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
             "print(m.who())\n" % disp)
    names = []
    for email in ("alex@example.test", "alex@one.test", "alex@two.test"):
        git(a, "config", "user.email", email)
        names.append(subprocess.run([sys.executable, "-c", probe], cwd=nr, stdout=subprocess.PIPE, text=True,
                                    env=clean_env()).stdout.strip())
    git(a, "config", "user.email", EMAIL)
    ok("who(): a registered person is their handle; two unregistered alex@ addresses get different branches",
       names[0] == "alex" and names[1].startswith("alex-") and names[2].startswith("alex-") and names[1] != names[2], names)

    # N1: the pull's autostash must not unstage what the person staged outside the tier
    d2 = os.path.join(tmp, "index")
    os.makedirs(d2)
    bare2, a2, nr2 = make_remote(d2, "r", prefix="memory")
    b2, _bn = clone(d2, bare2, "b", prefix="memory")
    os.makedirs(os.path.join(a2, "app"), exist_ok=True)
    with open(os.path.join(a2, "app", "code.py"), "w") as fh:
        fh.write("print('committed')\n")
    git(a2, "add", "app/code.py")
    git(a2, "commit", "-qm", "app code")
    git(a2, "push", "-q")
    git(b2, "pull", "-q")
    with open(os.path.join(a2, "app", "code.py"), "a") as fh:
        fh.write("print('a staged edit')\n")
    git(a2, "add", "app/code.py")
    new_note(os.path.join(b2, "memory"), "2026-10-20-teammate")
    git(b2, "add", "-A")
    git(b2, "commit", "-qm", "teammate note")
    git(b2, "push", "-q")
    new_note(nr2, "2026-10-21-mine")
    disp2 = os.path.join(nr2, "scripts", "sync-memory.py")
    p = subprocess.run([sys.executable, disp2, "post", "--agent"], cwd=nr2, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, env=clean_env())
    staged = git(a2, "diff", "--cached", "--name-only")
    ok("N1: post with a teammate's push to pull keeps app/code.py staged", p.returncode == 0 and staged == "app/code.py",
       (p.returncode, staged, (p.stdout + p.stderr)[-200:]))
    new_note(os.path.join(b2, "memory"), "2026-10-22-teammate")
    git(b2, "add", "-A")
    git(b2, "commit", "-qm", "teammate note 2")
    git(b2, "push", "-q")
    p = subprocess.run([sys.executable, disp2, "pre"], cwd=nr2, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, env=clean_env())
    ok("N1: ...and so does pre", p.returncode == 0 and git(a2, "diff", "--cached", "--name-only") == "app/code.py"
       and "a staged edit" in git(a2, "diff", "--cached"),
       (p.returncode, git(a2, "diff", "--cached", "--name-only")))

    # the lock: judged by its owner, not by its age alone
    lock = os.path.join(git(a, "rev-parse", "--absolute-git-dir"), "sync-memory.lock")
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    os.mkdir(lock)
    with open(os.path.join(lock, "owner"), "w") as fh:
        fh.write("pid=%d host=%s started=x\n" % (dead.pid, socket.gethostname()))
    old = time.time() - 60
    os.utime(lock, (old, old))
    rc, out = run_disp("pre")
    ok("06-F7: a lock whose owner process is gone is taken over at once", rc == 0 and not os.path.isdir(lock), (rc, out[-200:]))
    os.mkdir(lock)
    with open(os.path.join(lock, "owner"), "w") as fh:
        fh.write("pid=%d host=%s started=x\n" % (os.getpid(), socket.gethostname()))
    old = time.time() - 7200
    os.utime(lock, (old, old))
    rc, out = run_disp("pre")
    ok("06-F7: a two-hour-old lock whose owner is still running is NOT stolen (exit 75)", rc == 75 and os.path.isdir(lock), rc)
    shutil.rmtree(lock, ignore_errors=True)
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if os.name == "nt" and ps:
        native = [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                  os.path.join(nr, "scripts", "sync-memory.ps1"), "pre"]
        host = os.environ.get("COMPUTERNAME", socket.gethostname())   # what [Environment]::MachineName reports
    elif os.name != "nt" and shutil.which("bash"):
        native = [shutil.which("bash"), os.path.join(nr, "scripts", "sync-memory.sh"), "pre"]
        host = subprocess.run(["hostname"], stdout=subprocess.PIPE, text=True).stdout.strip() or socket.gethostname()
    else:
        native = None
    if native:
        res = []
        for pid, age in ((dead.pid, 60), (os.getpid(), 7200)):
            os.mkdir(lock)
            with open(os.path.join(lock, "owner"), "w") as fh:
                fh.write("pid=%d host=%s started=x\n" % (pid, host))
            os.utime(lock, (time.time() - age, time.time() - age))
            p = subprocess.run(native, cwd=nr, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=clean_env())
            res.append(p.returncode)
            shutil.rmtree(lock, ignore_errors=True)
        ok("06-F7: the native script judges its lock the same way (dead owner taken, live owner kept)", res == [0, 75], res)
    else:
        ok("06-F7: the native script judges its lock the same way (no native shell found: counted as a failure)", False)


def static_tests():
    print("\n=== static ===")
    raw = open(os.path.join(SCRIPTS, "sync-memory.ps1"), "rb").read()
    nonascii = sum(1 for b in raw if b > 127)
    ok("06-F2: sync-memory.ps1 is pure ASCII (Windows PowerShell 5.1 reads BOM-less files as ANSI)", nonascii == 0,
       "%d non-ASCII bytes" % nonascii)
    raw = open(os.path.join(SCRIPTS, "new-project-memory.ps1"), "rb").read()
    ok("new-project-memory.ps1 is pure ASCII too", sum(1 for b in raw if b > 127) == 0)


def main(argv):
    """--impl selects the implementation columns. The default is the one the dispatcher uses on this
    platform: PowerShell on Windows, bash elsewhere. Direct Git Bash on Windows is not a supported
    path (06-F12), and requiring it made the Windows check red although PowerShell passed (06-F13).
    A missing required implementation is a FAILURE, never a skip."""
    impl = "powershell" if os.name == "nt" else "bash"
    for i, arg in enumerate(argv):
        if arg.startswith("--impl="):
            impl = arg.split("=", 1)[1]
        elif arg == "--impl" and i + 1 < len(argv):
            impl = argv[i + 1]
    if impl not in ("bash", "powershell", "all"):
        print("usage: test_sync.py [--impl bash|powershell|all]")
        return 64
    cols = ["bash", "powershell"] if impl == "all" else [impl]
    print("implementations under test: %s" % ", ".join(cols))
    static_tests()
    tmp = tempfile.mkdtemp()
    try:
        for c in cols:
            if c == "powershell" and not ps_shell():
                ok("PowerShell (powershell or pwsh) is on PATH, as --impl requires", False)
                continue
            if c == "bash" and not shutil.which("bash"):
                ok("bash is on PATH, as --impl requires", False)
                continue
            scenarios(c, tmp)
        dispatcher_tests(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(RESULTS)
    print("\n%d passed, %d failed (implementations: %s)" % (passed, len(RESULTS) - passed, ", ".join(cols)))
    expected = 2 + 13 * len(cols) + 20
    return 0 if passed == len(RESULTS) == expected else 1  # a run that stops early is red


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
