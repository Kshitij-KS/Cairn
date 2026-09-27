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
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testpolicy  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PER_IMPL = 7
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


def scaffold(impl, cairn, target):
    if impl == "bash":
        return run([shutil.which("bash"), os.path.join(cairn, "scripts", "new-project-memory.sh"), target], cairn)
    return run([ps_shell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                os.path.join(cairn, "scripts", "new-project-memory.ps1"), target], cairn)


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


def cases(impl, tmp):
    print("\n=== %s ===" % impl)
    cairn = os.path.join(tmp, impl + "-cairn")
    shutil.copytree(REPO, cairn, ignore=shutil.ignore_patterns(".git", "node_modules", ".memory", "__pycache__", ".work"))
    testpolicy.install(os.path.join(cairn, "governance"))

    a = product(tmp, impl + "-plain")
    rc, out = scaffold(impl, cairn, a)
    ok("the scaffold exits 0 and creates memory/ with its guard and policy", rc == 0 and all(
        os.path.isfile(os.path.join(a, "memory", *p)) for p in (("scripts", "memory_guard.py"), ("governance", "roles.json"))),
       (rc, out[-300:]))
    wf = os.path.join(a, ".github", "workflows", "memory-gate.yml")
    text = open(wf).read() if os.path.isfile(wf) else ""
    ok("it installs a memory-gate workflow scoped to memory/, judged by the base revision's guard",
       '"memory/**"' in text and "base/memory/scripts/memory_guard.py" in text and "--notes-root head/memory" in text, text[:200])
    co = os.path.join(a, ".github", "CODEOWNERS")
    body = open(co).read() if os.path.isfile(co) else ""
    lines = [l for l in body.splitlines() if l.strip() and not l.startswith("#")]
    ok("with no CODEOWNERS it writes one holding only memory lines, naming the owner",
       lines and all(l.startswith("/memory/") for l in lines) and "@" + testpolicy.GITHUB in body, body)
    rc, out = run([sys.executable, os.path.join(a, "memory", "scripts", "memory_guard.py"), "--notes-root",
                   os.path.join(a, "memory"), "codeowners"], a)
    ok("the tier's guard agrees with the CODEOWNERS it wrote", rc == 0, out[-200:])

    before = snapshot(a)
    rc, out = scaffold(impl, cairn, a)
    ok("a second run changes no file", rc == 0 and snapshot(a) == before,
       sorted(k for k in set(before) | set(snapshot(a)) if before.get(k) != snapshot(a).get(k))[:5])

    b = product(tmp, impl + "-owned", codeowners="* @product-team\n")
    rc, out = scaffold(impl, cairn, b)
    kept = open(os.path.join(b, ".github", "CODEOWNERS")).read() == "* @product-team\n"
    sugg = os.path.join(b, ".github", "CODEOWNERS.team-memory.suggested")
    ok("an existing CODEOWNERS is left exactly as it was; the memory block goes to a .suggested file",
       rc == 0 and kept and os.path.isfile(sugg) and "/memory/" in open(sugg).read(), (rc, out[-200:]))

    run([sys.executable, os.path.join(a, "memory", "scripts", "memory_guard.py"), "--notes-root",
         os.path.join(a, "memory"), "stamp", "--all"], a)
    run(["git", "add", "-A"], a)
    rc, out = run([sys.executable, os.path.join(a, "memory", "scripts", "memory_guard.py"), "--notes-root",
                   os.path.join(a, "memory"), "check", "--staged"], a)
    ok("after stamping, the new tier passes its own guard", rc == 0, out[-300:])


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
