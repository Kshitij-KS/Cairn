#!/usr/bin/env python3
"""
test_scaffold.py - scripts/new-project-memory.{sh,ps1} give a code repository a governed memory tier.

Runs the scaffold of a copy of this repository (with the fictional test owner) against throwaway
git repositories and checks what a project needs on GitHub, not only on laptops: a memory-gate
workflow scoped to memory/, and the memory block of CODEOWNERS, while the product's own files are
never overwritten.

    python3 tools/test_scaffold.py                 # the platform's scaffold (PowerShell on Windows)
    python3 tools/test_scaffold.py --impl all      # both; a missing implementation is a failure
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
PER_IMPL = 22
RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + str(detail)) if detail and not cond else ""))


def env():
    e = {k: v for k, v in os.environ.items() if not k.startswith(("MEMORY_", "CLAUDE", "KIRO_", "CURSOR_", "GIT_"))}
    e.update({"GIT_AUTHOR_NAME": "Alex Tester", "GIT_COMMITTER_NAME": "Alex Tester",
              "GIT_AUTHOR_EMAIL": testpolicy.EMAIL, "GIT_COMMITTER_EMAIL": testpolicy.EMAIL,
              "MEMORY_ACTOR_KIND": "human", "PYTHONIOENCODING": "utf-8"})
    return e


def run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                       encoding="utf-8", errors="replace", env=env(), stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout + p.stderr


def ps_shell():
    return shutil.which("powershell") or shutil.which("pwsh")


def scaffold(impl, cairn, target, *extra):
    if impl == "bash":
        return run([shutil.which("bash"), os.path.join(cairn, "scripts", "new-project-memory.sh"), target, *extra], cairn)
    return run([ps_shell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                os.path.join(cairn, "scripts", "new-project-memory.ps1"), target, *extra], cairn)


def product(tmp, name, codeowners=None):
    d = os.path.join(tmp, name)
    os.makedirs(os.path.join(d, "src"))
    open(os.path.join(d, "src", "app.py"), "w").write("print('hi')\n")
    if codeowners is not None:
        os.makedirs(os.path.join(d, ".github"))
        open(os.path.join(d, ".github", "CODEOWNERS"), "w", newline="\n").write(codeowners)
    run(["git", "init", "-q", "-b", "main"], d)
    run(["git", "config", "user.email", testpolicy.EMAIL], d)   # the guard attributes notes to this identity
    run(["git", "config", "user.name", testpolicy.NAME], d)
    run(["git", "add", "-A"], d)
    run(["git", "commit", "-qm", "product"], d)
    return d


def snapshot(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x != ".git"]
        for f in fn:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root)] = open(p, "rb").read()
    return out


def guard(tier_repo, *args, env=None):
    e = dict(env or {})
    p = subprocess.run([sys.executable, os.path.join(tier_repo, "memory", "scripts", "memory_guard.py"), "--notes-root",
                        os.path.join(tier_repo, "memory"), *args], cwd=tier_repo, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                       env=dict(globals()["env"](), **e))
    return p.returncode, p.stdout + p.stderr


def printed_commands(out):
    """The `next:` commands the scaffold printed, to run exactly as a person would."""
    lines = out.split("next:", 1)[-1].splitlines()
    return [l.strip() for l in lines if l.strip().startswith("git ")]


def cases(impl, tmp):
    print("\n=== %s ===" % impl)
    cairn = os.path.join(tmp, impl + "-cairn")
    shutil.copytree(REPO, cairn, ignore=shutil.ignore_patterns(".git", "node_modules", ".memory", "__pycache__", ".work"))
    testpolicy.install(os.path.join(cairn, "governance"))

    a = product(tmp, impl + "-plain")
    rc, out = scaffold(impl, cairn, a)
    ok("the scaffold exits 0 and creates memory/ with its guard and policy", rc == 0 and all(
        os.path.isfile(os.path.join(a, "memory", *p)) for p in (("scripts", "memory_guard.py"), ("governance", "roles.json"))),
       (rc, out[-400:]))
    rc2, out2 = guard(a, "check")
    ok("08-F2: an untouched new tier passes its own guard (it starts clean)", rc2 == 0, out2[-300:])
    wf = os.path.join(a, ".github", "workflows", "memory-gate.yml")
    text = open(wf).read() if os.path.isfile(wf) else ""
    ok("it installs a memory-gate workflow scoped to memory/, judged by the base revision's guard",
       '"memory/**"' in text and "base/memory/scripts/memory_guard.py" in text and "--notes-root head/memory" in text
       and "--require-owned" in text, text[:200])
    co = os.path.join(a, ".github", "CODEOWNERS")
    body = open(co).read() if os.path.isfile(co) else ""
    lines = [l.split() for l in body.splitlines() if l.strip() and not l.startswith("#")]
    paths = [l[0] for l in lines]
    ok("D4: with no CODEOWNERS it writes the memory block, which also owns the gate and CODEOWNERS itself",
       paths == ["/memory/**", "/.github/workflows/memory-gate.yml", "/.github/CODEOWNERS"]
       and all(l[1:] == ["@" + testpolicy.GITHUB] for l in lines), body)
    rc, out3 = guard(a, "codeowners")
    ok("the tier's guard agrees with the CODEOWNERS it wrote", rc == 0, out3[-200:])

    cmds = printed_commands(out)
    for c in cmds:
        subprocess.run(c, shell=True, cwd=a, env=env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    st = subprocess.run(["git", "status", "--porcelain"], cwd=a, stdout=subprocess.PIPE, text=True).stdout
    mode = subprocess.run(["git", "ls-files", "-s", "memory/scripts/sync-memory.sh"], cwd=a, stdout=subprocess.PIPE, text=True).stdout
    ok("D3/08-F9: running the printed commands commits everything, .github included, sync-memory.sh executable",
       len(cmds) >= 3 and st.strip() == "" and mode.startswith("100755"), (cmds, st[:300], mode))

    before = snapshot(a)
    rc, out = scaffold(impl, cairn, a)
    after = snapshot(a)
    ok("a second run changes no file", rc == 0 and after == before,
       sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))[:5])

    # parity with the company tier (recheck D8): the same hook events and commands, pointed at memory/
    def hooks(path):
        d = json.load(open(path))
        return sorted((ev, h["command"]) for ev, groups in d.get("hooks", {}).items() for g in groups for h in g["hooks"])
    comp = [(ev, c.replace("scripts/", "memory/scripts/")) for ev, c in hooks(os.path.join(cairn, ".claude", "settings.json"))]
    ok("the project's Claude hooks are the company's, pointed at memory/scripts (Stop significance included)",
       hooks(os.path.join(a, ".claude", "settings.json")) == sorted(comp)
       and any("significance" in c for _e, c in comp), hooks(os.path.join(a, ".claude", "settings.json")))
    kiro = sorted(os.listdir(os.path.join(a, ".kiro", "hooks")))
    ok("...and its Kiro hooks and Cursor commands match the company tier's",
       kiro == sorted(os.listdir(os.path.join(cairn, ".kiro", "hooks")))
       and sorted(os.listdir(os.path.join(a, ".cursor", "commands"))) == sorted(os.listdir(os.path.join(cairn, ".cursor", "commands")))
       and all("memory/scripts/" in open(os.path.join(a, ".kiro", "hooks", f)).read() for f in kiro), kiro)
    hook = os.path.join(a, ".git", "hooks", "pre-commit")
    ok("a local pre-commit guard is installed for commits that touch memory/", os.path.isfile(hook)
       and os.access(hook, os.X_OK), hook)
    with open(os.path.join(a, "memory", "scripts", "evil.py"), "w") as fh:
        fh.write("print(1)\n")
    subprocess.run(["git", "add", "-A"], cwd=a, env=env())
    p = subprocess.run(["git", "commit", "-qm", "agent"], cwd=a, env=dict(env(), MEMORY_ACTOR_KIND="agent"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(["git", "reset", "-q", "--hard"], cwd=a, env=env())
    subprocess.run(["git", "clean", "-qfd"], cwd=a, env=env())
    with open(os.path.join(a, "src", "app.py"), "a") as fh:
        fh.write("print(2)\n")
    p2 = subprocess.run(["git", "commit", "-qam", "product"], cwd=a, env=env(), stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True)
    ok("negative: the hook blocks an agent's memory/scripts change; a product-only commit is untouched",
       p.returncode != 0 and p2.returncode == 0 and "memory-guard" not in p2.stderr, (p.returncode, p2.returncode, p2.stderr[-200:]))

    # 11-F5: a project tier plans one project
    levels = {}
    for rel in ("memory/context/x.md", "memory/decisions/x.md", "memory/features/x.md", "memory/CORE.md",
                "memory/context/restricted/x.md", "memory/log/journal/x.md"):
        probe = ("import sys; sys.path.insert(0, %r); import memory_guard as g; c = g.Ctx(%r); print(c.path_level(%r))"
                 % (os.path.join(a, "memory", "scripts"), os.path.join(a, "memory"), rel))
        levels[rel] = subprocess.run([sys.executable, "-c", probe], cwd=a, stdout=subprocess.PIPE, text=True, env=env()).stdout.strip()
    ok("11-F5: in a project tier context/, decisions/, features/ and CORE.md are L1; restricted stays L2",
       levels == {"memory/context/x.md": "L1", "memory/decisions/x.md": "L1", "memory/features/x.md": "L1",
                  "memory/CORE.md": "L1", "memory/context/restricted/x.md": "L2", "memory/log/journal/x.md": "L0"}, levels)

    b = product(tmp, impl + "-owned", codeowners="* @product-team\n")
    os.makedirs(os.path.join(b, ".kiro", "hooks"))
    open(os.path.join(b, ".kiro", "hooks", "memory-post-task.json"), "w").write('{"theirs": true}\n')
    os.makedirs(os.path.join(b, ".claude", "commands"))
    open(os.path.join(b, ".claude", "commands", "cairn.md"), "w").write("their command\n")
    rc, out = scaffold(impl, cairn, b)
    kept = open(os.path.join(b, ".github", "CODEOWNERS")).read() == "* @product-team\n"
    sugg = os.path.join(b, ".github", "CODEOWNERS.team-memory.suggested")
    ok("an existing CODEOWNERS is left exactly as it was; the memory block goes to a .suggested file",
       rc == 0 and kept and os.path.isfile(sugg) and "/memory/" in open(sugg).read(), (rc, out[-300:]))
    for c in printed_commands(out):
        subprocess.run(c, shell=True, cwd=b, env=env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tracked = subprocess.run(["git", "ls-files"], cwd=b, stdout=subprocess.PIPE, text=True).stdout
    ok("a .suggested file is never swept into the commit by the printed commands", ".team-memory.suggested" not in tracked
       and "memory/scripts/mem.py" in tracked, [l for l in tracked.splitlines() if "suggested" in l])
    ok("08-F7: an existing Kiro hook and command are kept, with .suggested files the report names",
       open(os.path.join(b, ".kiro", "hooks", "memory-post-task.json")).read() == '{"theirs": true}\n'
       and os.path.isfile(os.path.join(b, ".kiro", "hooks", "memory-post-task.json.team-memory.suggested"))
       and os.path.isfile(os.path.join(b, ".claude", "commands", "cairn.md.team-memory.suggested"))
       and ".kiro/hooks/memory-post-task.json" in out and ".claude/commands/cairn.md" in out, out[-400:])

    c = product(tmp, impl + "-blocked")
    open(os.path.join(c, ".claude"), "w").write("a file, not a folder\n")
    rc, out = scaffold(impl, cairn, c)
    ok("08-F3: a `.claude` FILE is an error (exit 7), and nothing under it is reported as created",
       rc == 7 and "+ .claude/" not in out and "is a file" in out, (rc, out[-300:]))

    bad_names = ["a/b", "x&y", 'na"me', "\u9879\u76ee", "UPPER"]
    if impl == "bash":
        bad_names.append("")   # Windows PowerShell drops an empty argument before it reaches Python
    res = []
    for i, n in enumerate(bad_names):
        d = product(tmp, "%s-name%d" % (impl, i))
        rc, out = scaffold(impl, cairn, d, n)
        res.append((n, rc, os.path.exists(os.path.join(d, "memory"))))
    ok("08-F4: a name with /, &, a quote, non-ASCII, capitals or nothing is refused before anything is written",
       all(rc == 1 and not made for _n, rc, made in res), res)
    d = product(tmp, "My App & Co")
    rc, out = scaffold(impl, cairn, d)
    pj = os.path.join(d, "memory", ".basic-memory", "project.json")
    try:
        name = json.load(open(pj))["name"]
    except (OSError, ValueError):
        name = None
    core = open(os.path.join(d, "memory", "CORE.md")).read() if os.path.isfile(os.path.join(d, "memory", "CORE.md")) else ""
    ok("08-F4: a folder called 'My App & Co' gives name my-app-co, valid JSON, and the title kept literally",
       rc == 0 and name == "my-app-co" and "My App & Co" in core and "__PROJECT" not in core, (rc, name, out[-200:]))
    d = product(tmp, "\u9879\u76ee")
    rc, out = scaffold(impl, cairn, d)
    ok("08-F4: a folder name with no usable letters asks for an explicit name (exit 1)", rc == 1 and "explicit" in out, out[-200:])

    # 08-F6 drift and --update; 08-F8 an invalid retained policy
    pol = os.path.join(cairn, "governance", "roles.json")
    orig = open(pol).read()
    open(pol, "w").write(orig.replace('"default": "L0"', '"default": "L0", "$drift": "DRIFT-SENTINEL"', 1))
    with open(os.path.join(cairn, "scripts", "mem.py"), "a") as fh:
        fh.write("\n# engine change\n")
    rc, out = scaffold(impl, cairn, a)
    ok("08-F6: a changed company policy and engine are reported as DRIFT on rerun", rc == 0
       and "DRIFT memory/governance/roles.json" in out and "DRIFT memory/scripts/mem.py" in out, out[-500:])
    rc, out = scaffold(impl, cairn, a, "--update")
    ok("--update refreshes the engine but never the policy",
       open(os.path.join(a, "memory", "scripts", "mem.py")).read().endswith("# engine change\n")
       and "DRIFT-SENTINEL" not in open(os.path.join(a, "memory", "governance", "roles.json")).read(), out[-300:])
    open(pol, "w").write(orig)
    open(os.path.join(a, "memory", "governance", "roles.json"), "w").write("{}\n")
    rc, out = scaffold(impl, cairn, a)
    ok("08-F8: an invalid project roles.json stops the scaffold (exit 6) and says so", rc == 6 and "roles.json" in out, (rc, out[-300:]))


def main(argv):
    impl = "powershell" if os.name == "nt" else "bash"
    for i, arg in enumerate(argv):
        if arg.startswith("--impl="):
            impl = arg.split("=", 1)[1]
        elif arg == "--impl" and i + 1 < len(argv):
            impl = argv[i + 1]
    cols = ["bash", "powershell"] if impl == "all" else [impl]
    tmp = tempfile.mkdtemp(prefix="cairn-scaffold-")
    try:
        for c in cols:
            if (c == "bash" and not shutil.which("bash")) or (c == "powershell" and not ps_shell()):
                ok("%s is on PATH, as --impl requires" % c, False)
                continue
            cases(c, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(RESULTS)
    expected = PER_IMPL * len(cols)
    print("\n%d passed, %d failed (%d of %d expected checks ran; implementations: %s)"
          % (passed, len(RESULTS) - passed, len(RESULTS), expected, ", ".join(cols)))
    return 0 if passed == len(RESULTS) == expected else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
