#!/usr/bin/env python3
"""
test_sync.py - end-to-end tests for the sync chain, against BOTH native implementations.

Every scenario is one of the audit's area-06 reproductions, run against local bare remotes:

  bash        sync-memory.sh  - the default on macOS / Linux
  powershell  sync-memory.ps1 - the default on Windows (what the dispatcher runs there)
  --impl all  both; a requested implementation that is missing is a failure, not a skip

On Windows this is THE check that lifts the containment on agent auto-commit: when it passes with
`powershell` (5.1), set MEMORY_SYNC_WINDOWS_POST=1. The builder's sandbox had no PowerShell, so the
PowerShell column has never been run there - see REMEDIATION.md.

    py tools/test_sync.py            # Windows
    python3 tools/test_sync.py       # macOS / Linux
"""
import json
import os
import shutil
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


def append(path, text):
    with open(path, "a", newline="\n") as fh:
        fh.write(text)


def scenarios(impl, tmp):
    print("\n=== %s ===" % impl)
    T = lambda n: os.path.join(tmp, impl + "-" + n)
    for n in ("happy", "scope", "fail", "conflict", "autostash", "ahead", "detached", "upstream", "staging", "secret"):
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
    expected = 2 + 11 * len(cols) + 5
    return 0 if passed == len(RESULTS) == expected else 1  # a run that stops early is red


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
