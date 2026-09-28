#!/usr/bin/env python3
"""test_init.py - scripts/init.py turns the template into a working, guard-clean instance.

Every case runs on a fresh copy of this repository, never on the repository itself. It checks that
the owner row, CODEOWNERS, stamps and a clean guard check all result, and that bad input, a missing
argument and a second run are refused without changing anything.

In an initialised instance (roles.json "instance": true) there is no template to initialise, so the
suite says so and exits 0 with zero checks. That zero is explained, not silent.
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED = 16
results = []


def ok(name, cond, detail=""):
    results.append(bool(cond))
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name, "" if cond or not detail else "  (" + detail + ")"))


def env():
    drop = ("CLAUDE", "CURSOR", "KIRO", "CODEX", "MEMORY_", "GIT_")
    e = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
    e["PYTHONIOENCODING"] = "utf-8"
    return e


def run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env(), stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout + p.stderr


def fresh(tmp, name):
    dst = os.path.join(tmp, name)
    shutil.copytree(REPO, dst, ignore=shutil.ignore_patterns("node_modules", ".memory", "__pycache__",
                                                             "fixtures", ".work", ".git"))
    return dst


def roles(root):
    return json.load(open(os.path.join(root, "governance", "roles.json"), encoding="utf-8"))


ARGS = ["--name", "Ada Lovelace", "--email", "ada@example.test", "--github", "ada-l",
        "--handle", "ada", "--org", "acme", "--repo", "acme-memory", "--yes"]


def init(root, args):
    return run([sys.executable, "scripts/init.py"] + args, root)


def main():
    tmp = tempfile.mkdtemp(prefix="cairn-init-")
    try:
        root = fresh(tmp, "a")
        ok("template: roles.json carries the __OWNER__ placeholder row, and the project README exists",
           "__OWNER__" in roles(root)["people"] and os.path.exists(os.path.join(root, ".github", "README.md")))
        rc, out = init(root, ARGS)
        ok("init exits 0", rc == 0, out[-400:])
        r = roles(root)
        ada = r.get("people", {}).get("ada", {})
        ok("owner row written", ada.get("role") == "owner" and ada.get("email") == "ada@example.test"
           and ada.get("github") == "ada-l", json.dumps(ada))
        ok("placeholder row removed", "__OWNER__" not in r.get("people", {}))
        ok("marked as an instance with org and repo",
           r.get("instance") is True and r.get("org") == "acme" and r.get("repo") == "acme-memory")
        co = open(os.path.join(root, ".github", "CODEOWNERS"), encoding="utf-8").read()
        ok("CODEOWNERS names the owner's login", "@ada-l" in co and "Not generated yet" not in co, co[:200])
        company = open(os.path.join(root, "context", "company.md"), encoding="utf-8").read()
        ok("owner placeholders filled in notes", "__OWNER_NAME__" not in company and "Ada Lovelace" in company)
        core = open(os.path.join(root, "CORE.md"), encoding="utf-8").read()
        ok("notes stamped with the owner as author", "author: ada" in core, core[:300])
        ok("template-only files removed, LICENSE, LICENSE-NOTES and NOTICE kept",
           not any(os.path.exists(os.path.join(root, ".github", f)) for f in ("README.md", "CONTRIBUTING.md", "SECURITY.md",
                                                                          "ISSUE_TEMPLATE", "pull_request_template.md", "assets"))
           and all(os.path.exists(os.path.join(root, f)) for f in ("LICENSE", "LICENSE-NOTES", "NOTICE")))
        _, email = run(["git", "config", "--local", "user.email"], root)
        ok("repository git identity set to the owner", email.strip() == "ada@example.test", email)
        run(["git", "add", "-A"], root)
        rc, out = run([sys.executable, "scripts/memory_guard.py", "check", "--staged"], root)
        ok("guard check on the initialised tree is clean", rc == 0, out[-400:])
        rc, out = run(["git", "commit", "-qm", "init"], root)
        ok("first commit succeeds", rc == 0, out[-300:])

        rc, out = init(root, ARGS)
        ok("negative: a second run is refused (exit 5)", rc == 5, "rc=%d %s" % (rc, out[-200:]))

        b = fresh(tmp, "b")
        bad = list(ARGS)
        bad[bad.index("--email") + 1] = "not-an-email"
        rc, _ = init(b, bad)
        ok("negative: an invalid email is refused, nothing changed",
           rc == 5 and "__OWNER__" in roles(b)["people"], "rc=%d" % rc)
        rc, out = init(b, ["--name", "Ada Lovelace", "--email", "ada@example.test", "--yes"])
        ok("negative: --yes without --github is refused (exit 5)", rc == 5, "rc=%d %s" % (rc, out[-200:]))
        bad = list(ARGS)
        bad[bad.index("--github") + 1] = "bad_login!"
        rc, _ = init(b, bad)
        ok("negative: an invalid GitHub login is refused (exit 5)", rc == 5, "rc=%d" % rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if roles(REPO).get("instance"):
        print("SKIP: this repository is an initialised instance; init is a template-only command.")
        print("\n0 passed, 0 failed (template-only suite skipped in an instance)")
        sys.exit(0)
    main()
    passed = sum(results)
    print("\n%d passed, %d failed (%d of %d expected checks ran)" % (passed, len(results) - passed,
                                                                    len(results), EXPECTED))
    sys.exit(0 if passed == len(results) == EXPECTED else 1)
