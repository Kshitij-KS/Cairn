#!/usr/bin/env python3
"""
test_gate.py - the memory-gate workflow's commands, run locally in its two-checkout shape.

The audit's 10-F1 PR replaced the guard with an always-success script, replaced the test runner,
demoted every path to L0 and added an L3 payload - and every repository-owned gate returned
success. This test builds that PR (and quieter variants) and runs the gate the way
.github/workflows/memory-gate.yml does: the BASE revision's guard and tests judge the PR checkout.
The PR must never come out green AND classified below L3.

    python3 tools/test_gate.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
# A Windows console defaults to cp1252: one non-ASCII character in a check's detail crashed the
# whole run with UnicodeEncodeError (Windows CI). Print it escaped instead.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="backslashreplace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testpolicy  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + str(detail)) if detail else ""))


def run(cmd, cwd, env=None):
    e = {k: v for k, v in os.environ.items()
         if k not in ("MEMORY_ACTOR_KIND", "MEMORY_ACTOR_EMAIL", "MEMORY_AGENT", "CLAUDE_CODE_SESSION_ID",
                      "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "KIRO_AGENT", "CURSOR_AGENT",
                      "MEMORY_POLICY_REF", "MEMORY_GUARD_UNDER_TEST")}
    e.update(env or {})
    e.setdefault("PYTHONIOENCODING", "utf-8")
    e.setdefault("PYTHONUTF8", "1")
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", env=e)
    return p.returncode, p.stdout + p.stderr


def git(cwd, *a):
    return run(["git", *a], cwd)[1].strip()


def make_base(tmp):
    src = os.path.join(tmp, "src")
    shutil.copytree(REPO, src, ignore=shutil.ignore_patterns("node_modules", ".memory", "__pycache__",
                                                             "fixtures", ".work", ".git"))
    testpolicy.install(os.path.join(src, "governance"))
    git(src, "init", "-q")
    git(src, "config", "user.email", "alex@example.test")
    git(src, "config", "user.name", "Alex Tester")
    run([sys.executable, "scripts/memory_guard.py", "stamp", "--all"], src)
    git(src, "add", "-A")
    git(src, "commit", "-qm", "base")
    return src


def gate(src, base_sha, head_sha, tmp):
    """The gate job, step for step: base checkout judges head checkout."""
    base = os.path.join(tmp, "base-%s" % head_sha[:7])
    head = os.path.join(tmp, "head-%s" % head_sha[:7])
    git(src, "worktree", "add", "-q", "--detach", base, base_sha)
    git(src, "worktree", "add", "-q", "--detach", head, head_sha)
    env = {"MEMORY_POLICY_REF": base_sha, "MEMORY_ACTOR_KIND": "human"}
    rng = "%s...%s" % (base_sha, head_sha)
    steps = {}
    steps["check"] = run([sys.executable, os.path.join(base, "scripts", "memory_guard.py"), "--notes-root", head,
                          "check", "--range", rng, "--policy-ref", base_sha, "--no-access"], tmp, env)
    steps["security-tests"] = run([sys.executable, os.path.join(base, "tools", "test_security.py")], tmp,
                                  dict(env, MEMORY_GUARD_UNDER_TEST=os.path.join(head, "scripts", "memory_guard.py")))
    steps["classify"] = run([sys.executable, os.path.join(base, "scripts", "memory_guard.py"), "--notes-root", head,
                             "classify", "--range", rng, "--policy-ref", base_sha, "--quiet", "--require-owned"], tmp, env)
    green = all(rc == 0 for name, (rc, _o) in steps.items() if name != "classify")
    level = steps["classify"][1].strip().splitlines()[0] if steps["classify"][0] == 0 else "ERROR"
    return green, level, steps


def pr(src, name, mutate):
    git(src, "checkout", "-q", "-b", name, "master") if git(src, "rev-parse", "--verify", "-q", "master") else \
        git(src, "checkout", "-q", "-b", name, "main")
    mutate(src)
    git(src, "add", "-A")
    git(src, "commit", "-qm", name)
    head = git(src, "rev-parse", "HEAD")
    git(src, "checkout", "-q", "-")
    return head


def main():
    tmp = tempfile.mkdtemp()
    try:
        src = make_base(tmp)
        base_sha = git(src, "rev-parse", "HEAD")

        def full_attack(d):
            with open(os.path.join(d, "scripts", "memory_guard.py"), "w") as fh:
                fh.write("import sys\nsys.exit(0)\n")
            with open(os.path.join(d, "tools", "run_tests.sh"), "w") as fh:
                fh.write("exit 0\n")
            pol = json.load(open(os.path.join(d, "governance", "roles.json")))
            pol["paths"]["rules"].insert(0, {"glob": "scripts/**", "level": "L0"})
            pol["paths"]["rules"].insert(0, {"glob": "governance/**", "level": "L0"})
            json.dump(pol, open(os.path.join(d, "governance", "roles.json"), "w"), indent=2)
            with open(os.path.join(d, "scripts", "payload.py"), "w") as fh:
                fh.write("print('pwned')\n")

        def quiet_demotion(d):
            pol = json.load(open(os.path.join(d, "governance", "roles.json")))
            pol["paths"]["rules"].insert(0, {"glob": "features/**", "level": "L0"})
            json.dump(pol, open(os.path.join(d, "governance", "roles.json"), "w"), indent=2)

        def demoting_rename(d):
            os.makedirs(os.path.join(d, "log", "journal"), exist_ok=True)
            subprocess.run(["git", "mv", "context/company.md", "log/journal/company.md"], cwd=d)

        def honest_l0(d):
            with open(os.path.join(d, "log", "journal", "2026-09-25-honest.md"), "w", newline="\n") as fh:
                fh.write("---\ntitle: 2026-09-25 honest note\ntype: gotcha\ntags: [gotcha]\n---\n\n"
                         "# 2026-09-25 honest note\n\nA plain observation.\n\n## Observations\n"
                         "- [gotcha] The gate judges pull requests with the base revision's guard\n\n"
                         "## Relations\n- relates_to [[Core]]\n")
            subprocess.run(["git", "add", "-A"], cwd=d)
            run([sys.executable, "scripts/memory_guard.py", "stamp", "--staged"], d)

        cases = [("the audit's 10-F1 PR (guard, tests and policy replaced, L3 payload)", full_attack),
                 ("a quiet policy demotion of features/", quiet_demotion),
                 ("an L2 note renamed into log/journal", demoting_rename)]
        print("\nattacks: never green-and-below-L3")
        for label, fn in cases:
            head_sha = pr(src, "pr-%d" % cases.index((label, fn)), fn)
            green, level, steps = gate(src, base_sha, head_sha, tmp)
            ok("%s -> gate %s, classified %s" % (label, "GREEN" if green else "RED", level),
               (not green) or level == "L3" or (level == "L2" and fn is demoting_rename),
               "" if (not green) or level in ("L2", "L3") else steps)
            if fn is full_attack:
                ok("  ...and the base security tests catch the replaced guard", steps["security-tests"][0] != 0,
                   steps["security-tests"][1][-400:] if steps["security-tests"][0] == 0 else "")
                ok("  ...and the classifier says L3", level == "L3", level)

        print("\ncontrol: an honest L0 note")
        git(src, "checkout", "-q", "-b", "pr-honest")
        honest_l0(src)
        git(src, "add", "-A")
        git(src, "commit", "-qm", "honest")
        head_sha = git(src, "rev-parse", "HEAD")
        green, level, steps = gate(src, base_sha, head_sha, tmp)
        ok("an honest L0 note is green and classified L0", green and level == "L0",
           "" if green and level == "L0" else {k: (rc, o[-300:]) for k, (rc, o) in steps.items()})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(RESULTS)
    print("\n%d passed, %d failed" % (passed, len(RESULTS) - passed))
    return 0 if passed == len(RESULTS) == 6 else 1  # expected-count check: a run that stops early is red


if __name__ == "__main__":
    sys.exit(main())
