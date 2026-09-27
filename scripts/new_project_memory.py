#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# ///
"""
new_project_memory.py - give a code repository its own governed memory tier (memory/).

    python3 scripts/new_project_memory.py <path-to-project-repo> [project-name] [--update]

scripts/new-project-memory.sh and .ps1 are thin wrappers that find Python and run this file, so
there is ONE implementation on every platform. The two shell versions drifted apart and each had
its own bugs (recheck 08-F3/F4/F6-F10): a name with `/` or `&` broke sed, a `.claude` that was a
file produced 24 silent write errors reported as "created", a changed company policy was never
noticed, and the PowerShell copy could not be tested on Linux at all.

What it does, never overwriting a file that differs from what it would write:

  memory/                 notes from templates/project-memory/memory, stamped so the tier starts
                          clean under its own guard (08-F2)
  memory/scripts/         the engine, copied from this repository (sync, guard, mem)
  memory/governance/      roles.json, copied from this repository (people and roles are company-wide)
  .claude/ .kiro/ .cursor/  the SAME hooks and commands the company tier has, with every script path
                          pointed at memory/scripts/ - derived, so the two can never drift (recheck D8)
  .github/                the memory-gate workflow, and the memory block of CODEOWNERS (which also
                          owns the gate workflow and CODEOWNERS itself, recheck D4)
  .git/hooks/pre-commit   a local guard for commits that touch memory/ (per machine; never replaces
                          an existing hook or a configured core.hooksPath)

An existing file that differs gets a `<file>.team-memory.suggested` sibling to merge by hand; the
report lists every one. `--update` refreshes the copied ENGINE files (memory/scripts/*, the skill)
from this repository; it never touches notes or roles.json. Differences in roles.json are reported
as DRIFT for a person to review.

Exit codes: 0 ok, 1 usage or environment error, 5 the new tier does not pass its own guard,
6 the tier's policy (memory/governance/roles.json) is invalid, 7 some files could not be written.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CAIRN = os.path.dirname(HERE)
TPL = os.path.join(CAIRN, "templates", "project-memory")
ENGINE = ("sync-memory.sh", "sync-memory.ps1", "sync-memory.py", "memory_guard.py", "mem.py")
NAME_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# Script paths in the company tier's hooks and commands, rewritten to point into memory/.
SCRIPT_RX = re.compile(r"(?<![\w./-])scripts/(sync-memory\.(?:py|sh|ps1)|memory_guard\.py|mem\.py)")
HOOK_MARK = "# cairn memory guard (installed by new_project_memory.py)"


class Report:
    def __init__(self, target):
        self.target = target
        self.created, self.skipped, self.suggested, self.updated = [], [], [], []
        self.drift, self.errors, self.notes = [], [], []

    def rel(self, p):
        return os.path.relpath(p, self.target).replace(os.sep, "/")


def git(cwd, *args):
    p = subprocess.run(["git", "-c", "core.quotePath=false", "-C", cwd, *args], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout.strip()


def same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def read_bytes(p):
    try:
        with open(p, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def blocked_by_file(dest, target):
    """The first existing ancestor of dest (inside target) that is a FILE, or None."""
    d = os.path.dirname(dest)
    while d and not same_path(d, target) and d != os.path.dirname(d):
        if os.path.exists(d) and not os.path.isdir(d):
            return d
        d = os.path.dirname(d)
    return None


def put(rep, dest, data, suggest=True, overwrite=False, mode=None):
    """Write bytes at dest unless something is already there. Identical -> skipped; different ->
    a .team-memory.suggested sibling (or overwritten, for --update of engine files)."""
    bad = blocked_by_file(dest, rep.target)
    if bad:
        rep.errors.append("%s: %s exists and is a file, not a folder" % (rep.rel(dest), rep.rel(bad)))
        return False
    have = read_bytes(dest)
    if os.path.isdir(dest):
        rep.errors.append("%s: a folder is in the way" % rep.rel(dest))
        return False
    if have is not None:
        if have == data:
            rep.skipped.append(rep.rel(dest))
            return True
        if overwrite:
            target, bucket = dest, rep.updated
        elif suggest:
            target, bucket = dest + ".team-memory.suggested", rep.suggested
            if read_bytes(target) == data:
                rep.suggested.append(rep.rel(dest))
                return True
        else:
            rep.skipped.append(rep.rel(dest) + " (kept; differs from the template)")
            return True
    else:
        target, bucket = dest, rep.created
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(data)
        if mode:
            os.chmod(target, mode)
    except OSError as e:
        rep.errors.append("%s: %s" % (rep.rel(target), e.strerror or e))
        return False
    bucket.append(rep.rel(dest))
    return True


def render(text, values, as_json=False):
    """Plain replacement, never sed: `/`, `&` and quotes in a value are just characters (08-F4).
    In a JSON template each value is inserted JSON-escaped, and the result must parse."""
    for k, v in values.items():
        text = text.replace(k, json.dumps(v)[1:-1] if as_json else v)
    if as_json:
        json.loads(text)
    return text


def project_paths(text):
    return SCRIPT_RX.sub(r"memory/scripts/\1", text)


def derived_json(src):
    """A company-tier hook or settings file, with every script path pointed at memory/scripts/."""
    with open(src, encoding="utf-8") as fh:
        d = json.load(fh)
    out = json.loads(project_paths(json.dumps(d)))
    return (json.dumps(out, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def slug(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def python_cmd():
    for c in ("python3", "python", "py"):
        exe = shutil.which(c)
        if not exe:
            continue
        # The Windows Store alias is on PATH and exits 9009 without running anything.
        p = subprocess.run([exe, "-c", "import sys; print(sys.version_info[0])"], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True)
        if p.returncode == 0 and p.stdout.strip() == "3":
            return exe
    return sys.executable


def install_hook(rep, target):
    rc, hooks_path = git(target, "config", "--get", "core.hooksPath")
    if rc == 0 and hooks_path:
        rep.notes.append("core.hooksPath is set (%s): add a pre-commit step that runs "
                         "`python memory/scripts/memory_guard.py --notes-root memory check --staged` "
                         "for commits touching memory/" % hooks_path)
        return
    rc, gitdir = git(target, "rev-parse", "--absolute-git-dir")
    if rc != 0:
        return
    hook = os.path.join(gitdir, "hooks", "pre-commit")
    body = ("#!/bin/sh\n%s\n"
            "# Checks only commits that touch memory/; the memory-gate workflow is the authority on GitHub.\n"
            "top=\"$(git rev-parse --show-toplevel)\" || exit 0\n"
            "[ -n \"$(git diff --cached --name-only -- memory)\" ] || exit 0\n"
            "for py in python3 python py; do\n"
            "  if command -v \"$py\" >/dev/null 2>&1 && \"$py\" -c 'import sys' >/dev/null 2>&1; then\n"
            "    exec \"$py\" \"$top/memory/scripts/memory_guard.py\" --notes-root \"$top/memory\" check --staged\n"
            "  fi\n"
            "done\n"
            "echo 'memory guard: no Python found, so this memory change was not checked here (memory-gate still checks it)' >&2\n"
            "exit 1\n") % HOOK_MARK
    have = read_bytes(hook)
    if have is not None and HOOK_MARK.encode() not in have:
        rep.notes.append(".git/hooks/pre-commit already exists: add the memory guard to it by hand "
                         "(see memory/README.md)")
        return
    if have == body.encode():
        rep.skipped.append(".git/hooks/pre-commit (memory guard)")
        return
    try:
        os.makedirs(os.path.dirname(hook), exist_ok=True)
        with open(hook, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        os.chmod(hook, os.stat(hook).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        rep.created.append(".git/hooks/pre-commit (memory guard, this machine only)")
    except OSError as e:
        rep.errors.append(".git/hooks/pre-commit: %s" % (e.strerror or e))


def run_guard(py, target, *args):
    p = subprocess.run([py, os.path.join(target, "memory", "scripts", "memory_guard.py"), "--notes-root",
                        os.path.join(target, "memory"), *args], cwd=target, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, MEMORY_ACTOR_KIND=os.environ.get("MEMORY_ACTOR_KIND", "human")))
    return p.returncode, p.stdout + p.stderr


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    unknown = flags - {"--update", "--no-hook"}
    if not args or len(args) > 2 or unknown:
        sys.stderr.write("usage: new_project_memory.py <path-to-project-repo> [project-name] [--update] [--no-hook]\n")
        return 1
    target = os.path.abspath(args[0])
    if not os.path.isdir(target):
        sys.stderr.write("ERROR: %s is not a directory\n" % target)
        return 1
    rc, top = git(target, "rev-parse", "--show-toplevel")
    if rc != 0 or not top:
        sys.stderr.write("ERROR: %s is not a git repository (git init first)\n" % target)
        return 1
    if not same_path(top, target):   # realpath + normcase: symlinks, 8.3 names and case on Windows (08-F10)
        sys.stderr.write("ERROR: run against the repository root (%s), not a subfolder\n" % top)
        return 1
    if same_path(target, CAIRN):
        sys.stderr.write("ERROR: this is the company memory itself; run against a code repository\n")
        return 1
    base = os.path.basename(target.rstrip("/\\"))
    name = args[1] if len(args) > 1 else slug(base)
    if not NAME_RX.match(name or ""):
        sys.stderr.write("ERROR: project name %r must be lower-case letters, digits and hyphens (1-63, starting "
                         "with a letter or digit). Pass one explicitly: new_project_memory.py <repo> my-project\n" % name)
        return 1
    if name == "cairn":
        sys.stderr.write("ERROR: project name 'cairn' is reserved\n")
        return 1
    title = re.sub(r"[_-]+", " ", base).strip() or name
    title = re.sub(r"[\r\n\t]+", " ", title)
    values = {"__PROJECT_NAME__": name, "__PROJECT_TITLE__": title,
              "__DATE__": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    rep = Report(target)
    update = "--update" in flags

    # 1. notes and manifest from the template
    mem_tpl = os.path.join(TPL, "memory")
    for dp, _dn, fns in os.walk(mem_tpl):
        for fn in sorted(fns):
            src = os.path.join(dp, fn)
            rel = os.path.relpath(src, mem_tpl)
            dest = os.path.join(target, "memory", rel[:-5] if rel.endswith(".tmpl") else rel)
            with open(src, encoding="utf-8") as fh:
                text = fh.read()
            try:
                data = render(text, values, as_json=dest.endswith(".json")).encode("utf-8")
            except ValueError as e:
                rep.errors.append("%s: the rendered JSON does not parse (%s)" % (rep.rel(dest), e))
                continue
            put(rep, dest, data, suggest=False)

    # 2. the engine and the policy, from this repository
    for s in ENGINE:
        data = read_bytes(os.path.join(HERE, s))
        put(rep, os.path.join(target, "memory", "scripts", s), data, suggest=False, overwrite=update,
            mode=0o755 if s.endswith(".sh") else None)
        have = read_bytes(os.path.join(target, "memory", "scripts", s))
        if have is not None and have != data:
            rep.drift.append("memory/scripts/%s differs from this repository's copy (rerun with --update to refresh it)" % s)
    skill = read_bytes(os.path.join(CAIRN, ".agents", "skills", "team-memory", "SKILL.md"))
    put(rep, os.path.join(target, "memory", ".agents", "skills", "team-memory", "SKILL.md"), skill,
        suggest=False, overwrite=update)
    company_policy = read_bytes(os.path.join(CAIRN, "governance", "roles.json"))
    pol_dest = os.path.join(target, "memory", "governance", "roles.json")
    put(rep, pol_dest, company_policy, suggest=False)
    have = read_bytes(pol_dest)
    if have is not None and have != company_policy:
        rep.drift.append("memory/governance/roles.json differs from the company policy: review the difference "
                         "(people and roles are company-wide) and copy what applies; it is never overwritten")

    # 3. client configuration: the company tier's own hooks and commands, pointed at memory/
    for rel in (".claude/settings.json", ".kiro/hooks/memory-session-start.json",
                ".kiro/hooks/memory-post-task.json", ".kiro/hooks/memory-prompt-moved.json"):
        src = os.path.join(CAIRN, rel)
        if os.path.isfile(src):
            put(rep, os.path.join(target, rel), derived_json(src))
    for d in (".claude/commands", ".cursor/commands"):
        src_dir = os.path.join(CAIRN, d)
        for fn in sorted(os.listdir(src_dir)) if os.path.isdir(src_dir) else []:
            if fn.endswith(".md"):
                with open(os.path.join(src_dir, fn), encoding="utf-8") as fh:
                    put(rep, os.path.join(target, d, fn), project_paths(fh.read()).encode("utf-8"))
    cc = os.path.join(TPL, "client-config")
    for tpl, dest in (("cursor-memory.mdc.tmpl", ".cursor/rules/memory.mdc"),
                      ("kiro-steering-memory.md.tmpl", ".kiro/steering/memory.md"),
                      ("kiro-mcp.json.tmpl", ".kiro/settings/mcp.json"),
                      ("mcp.json.tmpl", ".mcp.json"),
                      ("cursor-mcp.json.tmpl", ".cursor/mcp.json"),
                      ("memory-gate.yml.tmpl", ".github/workflows/memory-gate.yml")):
        with open(os.path.join(cc, tpl), encoding="utf-8") as fh:
            text = fh.read()
        try:
            data = render(text, values, as_json=dest.endswith(".json")).encode("utf-8")
        except ValueError as e:
            rep.errors.append("%s: the rendered JSON does not parse (%s)" % (dest, e))
            continue
        put(rep, os.path.join(target, dest), data)
    for d in (".claude", ".kiro"):
        put(rep, os.path.join(target, d, "skills", "team-memory", "SKILL.md"), skill, overwrite=update)

    # 4. CLAUDE.md imports the tier's rules once
    with open(os.path.join(cc, "CLAUDE-snippet.md.tmpl"), encoding="utf-8") as fh:
        snippet = render(fh.read(), values)
    cm = os.path.join(target, "CLAUDE.md")
    have = read_bytes(cm)
    if os.path.isdir(cm):
        rep.errors.append("CLAUDE.md: a folder is in the way")
    elif have is None:
        put(rep, cm, ("# %s\n%s" % (title, snippet)).encode("utf-8"))
    elif b"@memory/AGENT-RULES.md" in have:
        rep.skipped.append("CLAUDE.md (import already present)")
    else:
        try:
            with open(cm, "ab") as fh:
                fh.write(("\n" if not have.endswith(b"\n") else "").encode() + snippet.encode("utf-8"))
            rep.created.append("CLAUDE.md (appended the memory import)")
        except OSError as e:
            rep.errors.append("CLAUDE.md: %s" % (e.strerror or e))

    # 5. the company tier's location on THIS machine (gitignored), for company playbooks
    put(rep, os.path.join(target, "memory", ".memory", "company-root"), (CAIRN + "\n").encode("utf-8"),
        suggest=False, overwrite=True)

    py = python_cmd()
    # 6. the tier's policy must load before anything is judged by it (08-F8)
    rc, out = run_guard(py, target, "classify", "--quiet")
    if rc == 6:
        sys.stderr.write(out)
        sys.stderr.write("ERROR: memory/governance/roles.json cannot be used (above). Fix or remove it and rerun.\n")
        return 6

    # 7. CODEOWNERS: the memory block, last in the file
    co = os.path.join(target, ".github", "CODEOWNERS")
    rc, block = run_guard(py, target, "codeowners", "--print")
    if rc != 0:
        rep.notes.append("CODEOWNERS not written: %s. Fill the owner's GitHub login in memory/governance/roles.json, "
                         "then run: python memory/scripts/memory_guard.py --notes-root memory codeowners --write"
                         % (block.strip().splitlines() or ["?"])[-1])
    elif blocked_by_file(co, target):
        rep.errors.append(".github/CODEOWNERS: .github exists and is a file")
    elif not os.path.exists(co):
        put(rep, co, block.encode("utf-8"))
    else:
        rc2, _o = run_guard(py, target, "codeowners")
        if rc2 == 0:
            rep.skipped.append(".github/CODEOWNERS (memory block current)")
        else:
            put(rep, co, block.encode("utf-8"))
            rep.notes.append(".github/CODEOWNERS: the memory block must be its LAST lines (GitHub applies the last "
                             "match). Append the .suggested block, or run: python memory/scripts/memory_guard.py "
                             "--notes-root memory codeowners --write")

    # 8. start clean: stamp the new notes from the git identity, then run the tier's own guard (08-F2)
    rc_e, email = git(target, "config", "user.email")
    if not email:
        rep.errors.append("git user.email is not set here, so the new notes cannot be attributed: "
                          "git config user.email <your address in roles.json>, then rerun")
    else:
        run_guard(py, target, "stamp", "--all")
        rc, out = run_guard(py, target, "check")
        if rc not in (0,):
            rep.errors.append("the new tier does not pass its own guard:\n" + out.strip()[-1500:])
            rep.guard_rc = rc

    if "--no-hook" not in flags:
        install_hook(rep, target)
    # A .suggested file is for a person to merge, never to commit: the printed `git add -A .claude`
    # swept one into the product repository. Excluded locally (this clone only, nothing committed).
    rc, gitdir = git(target, "rev-parse", "--absolute-git-dir")
    if rc == 0 and gitdir:
        ex = os.path.join(gitdir, "info", "exclude")
        have = (read_bytes(ex) or b"").decode("utf-8", "replace")
        if "*.team-memory.suggested" not in have.split("\n"):
            try:
                os.makedirs(os.path.dirname(ex), exist_ok=True)
                with open(ex, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(("" if not have or have.endswith("\n") else "\n") + "*.team-memory.suggested\n")
            except OSError as e:
                rep.errors.append(".git/info/exclude: %s" % (e.strerror or e))

    # 9. Basic Memory registration (optional)
    reg = "skipped (basic-memory not on PATH)"
    bm = shutil.which("basic-memory")
    if bm:
        p = subprocess.run([bm, "project", "list", "--json"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if re.search(r'"name"\s*:\s*"%s"' % re.escape(name), p.stdout or ""):
            reg = "already registered"
        elif subprocess.run([bm, "project", "add", name, os.path.join(target, "memory")],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            reg = "registered -> %s" % os.path.join(target, "memory")
        else:
            reg = "FAILED: run basic-memory project add %s \"%s\"" % (name, os.path.join(target, "memory"))

    # report: only what actually happened
    print('\nproject memory for "%s" (%s)' % (name, target))
    for label, items, mark in (("created", rep.created, "+"), ("updated (--update)", rep.updated, "~"),
                               ("left untouched", rep.skipped, "=")):
        if items:
            print("  %s (%d):" % (label, len(items)))
            for x in items:
                print("    %s %s" % (mark, x))
    if rep.suggested:
        print("  MERGE BY HAND - these already existed; see the .team-memory.suggested file next to each:")
        for x in rep.suggested:
            print("    ! %s" % x)
    for x in rep.drift:
        print("  DRIFT %s" % x)
    for x in rep.notes:
        print("  NOTE %s" % x)
    print("  Basic Memory: %s" % reg)
    if rep.errors:
        print("\n  FAILED (%d) - nothing above is complete until these are fixed:" % len(rep.errors))
        for x in rep.errors:
            print("    x " + x.replace("\n", "\n      "))
        return getattr(rep, "guard_rc", None) and 5 or 7
    q = '"%s"' % target if " " in target else target
    print("\nnext:\n  cd %s\n  git add -A memory .claude .cursor .kiro .github .mcp.json CLAUDE.md\n"
          "  git add --chmod=+x memory/scripts/sync-memory.sh\n"
          "  git commit -m \"memory: add project memory tier (%s)\"" % (q, name))
    print("  then fill memory/context/overview.md and run: python memory/scripts/sync-memory.py pre")
    print("  The pull request that adds memory/ is the one the memory-gate cannot judge (the base has no "
          "guard yet): have an owner review it.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
