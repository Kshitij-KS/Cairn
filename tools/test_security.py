#!/usr/bin/env python3
"""
test_security.py - regression tests for the 2026-09 audit's access and attribution BLOCKERs.

Each test is the audit's reproduction, turned into an assertion that the attack now FAILS. Finding
ids (01-F1 ...) refer to the 2026-09 independent audit. Standard library only; throwaway git repos.

    python3 tools/test_security.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_guard import GUARD, NOTE, RESULTS, guard, make_repo, ok, read, sh, write  # noqa: E402

AGENT = {"MEMORY_ACTOR_KIND": "agent"}


def fresh():
    tmp = tempfile.mkdtemp()
    root, notes = make_repo(tmp)
    # a committed L2 note and a canonical skill with its derived copy, for the rename/derived cases
    write(os.path.join(notes, "context", "high.md"), NOTE)
    write(os.path.join(notes, ".agents", "skills", "s", "SKILL.md"), "two\n")
    write(os.path.join(notes, ".claude", "skills", "s", "SKILL.md"), "two\n")
    guard(notes, "stamp", "--all")
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", "base")
    return tmp, root, notes


def policy(notes):
    return json.load(open(os.path.join(notes, "governance", "roles.json")))


def save_policy(notes, d):
    json.dump(d, open(os.path.join(notes, "governance", "roles.json"), "w"), indent=2)


def test_policy_self_demotion():
    print("\n01-F1 / 10-F1: a staged policy change cannot authorise itself")
    tmp, root, notes = fresh()
    try:
        d = policy(notes)
        d["paths"]["rules"].insert(0, {"glob": "scripts/**", "level": "L0"})
        save_policy(notes, d)
        write(os.path.join(notes, "scripts", "payload.py"), "print(1)\n")
        sh(root, "git", "add", "-A")
        rc, out = guard(notes, "check", "--staged", "--no-attribution", env=AGENT)
        ok("negative: demoting scripts/** in the same commit as a script edit is DENIED (exit 4)",
           rc == 4 and "ACCESS-LEVEL" in out, "rc=%d" % rc)
        ok("the policy file itself is L3 under the trusted policy", "governance/roles.json" in out)
        sh(root, "git", "reset", "-q", "--hard")
        sh(root, "git", "clean", "-qfd")

        d = policy(notes)
        d["paths"]["rules"].insert(0, {"glob": "**", "level": "L0"})
        save_policy(notes, d)
        sh(root, "git", "add", "-A")
        rc, out = guard(notes, "check", "--staged", "--no-attribution", env=AGENT)
        ok("negative: a catch-all rule makes the policy unusable (exit 6, nothing checked)", rc == 6, "rc=%d" % rc)
        sh(root, "git", "reset", "-q", "--hard")

        # the floor holds even when the TRUSTED policy is wrong: commit a demotion as the owner first
        d = policy(notes)
        d["paths"]["rules"] = [r for r in d["paths"]["rules"] if r["glob"] != "scripts/**"]
        save_policy(notes, d)
        sh(root, "git", "commit", "-qam", "owner removes the scripts rule")
        write(os.path.join(notes, "scripts", "payload.py"), "print(1)\n")
        sh(root, "git", "add", "-A")
        rc, out = guard(notes, "check", "--staged", "--no-attribution", env=AGENT)
        ok("negative: with no scripts/** rule at all, the protected floor still makes it L3", rc == 4, "rc=%d" % rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_empty_policy():
    print("\n01-F2: an empty policy fails closed")
    tmp, root, notes = fresh()
    try:
        save_policy(notes, {})
        write(os.path.join(notes, "scripts", "p.py"), "x\n")
        sh(root, "git", "add", "-A")
        rc, out = guard(notes, "check", "--staged", "--no-attribution", env=AGENT)
        ok("negative: roles.json = {} exits 6 instead of treating everything as L0", rc == 6, "rc=%d" % rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rename_and_case():
    print("\n01-F3 / 01-F4 / 10-F4: renames and case tricks")
    tmp, root, notes = fresh()
    try:
        os.makedirs(os.path.join(notes, "log", "journal"), exist_ok=True)
        sh(root, "git", "mv", "context/high.md", "log/journal/lowered.md")
        rc, out = guard(notes, "check", "--staged", "--no-attribution", env=AGENT)
        ok("negative: moving L2 canon into log/journal is DENIED (the source deletion is L2)", rc == 4, "rc=%d" % rc)
        sh(root, "git", "reset", "-q", "--hard")

        write(os.path.join(notes, "Context", "cold.md"), NOTE.replace("Export Notes", "Cold"))
        sh(root, "git", "add", "-A")
        rc, out = guard(notes, "check", "--staged", "--no-attribution", env=AGENT)
        ok("negative: a new Context/ (capital C) note is L2, not L0", rc == 4, "rc=%d" % rc)
        sh(root, "git", "reset", "-q", "--hard")
        sh(root, "git", "clean", "-qfd")

        # Never import the guard under test into this process: an attacker's guard that calls
        # sys.exit(0) at import time would end this test run GREEN (found building test_gate.py).
        probe = ("import importlib.util, json, sys, os\n"
                 "spec = importlib.util.spec_from_file_location('mg', sys.argv[1])\n"
                 "mg = importlib.util.module_from_spec(spec); spec.loader.exec_module(mg)\n"
                 "ctx = mg.Ctx(sys.argv[2])\n"
                 "print('LEVELS=' + json.dumps({p: ctx.path_level(p) for p in sys.argv[3:]}))\n")
        paths = ["Context/x.md", "CONTEXT/x.md", "./context/x.md", "context\\x.md", "log/../context/x.md",
                 "\u017fcripts/x.py", "Scripts/x.py", "web/app.js", "tools/test_guard.py"]
        p = subprocess.run([sys.executable, "-c", probe, GUARD, notes, *paths], cwd=notes,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = [l for l in p.stdout.splitlines() if l.startswith("LEVELS=")]
        got = json.loads(line[0][7:]) if line else {"<no output from the guard>": None}
        bad = {p: l for p, l in got.items() if l in (None, "L0", "L1")}
        ok("every case, separator, dot-segment and long-s spelling of a protected path is L2+", not bad, str(bad or got))

        # the same demoting rename, committed on a branch, judged as a range (the CI shape)
        sh(root, "git", "checkout", "-qb", "pr")
        sh(root, "git", "mv", "context/high.md", "log/journal/lowered.md")
        sh(root, "git", "commit", "-qm", "demote")
        base = sh(root, "git", "rev-parse", "HEAD~1")[1].strip()
        rc, out = guard(notes, "check", "--range", "%s...HEAD" % base, "--no-attribution", env=AGENT)
        ok("negative: the demoting rename is DENIED in range mode too", rc == 4, "rc=%d" % rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_attribution():
    print("\n01-F5 / 01-F6: attribution comes from git, for new notes too")
    tmp, root, notes = fresh()
    try:
        d = policy(notes)
        d["people"]["ana"] = {"name": "Ana", "email": "ana@corp.test", "github": "ana", "role": "contributor"}
        save_policy(notes, d)
        sh(root, "git", "commit", "-qam", "add ana")
        path = os.path.join(notes, "log", "journal", "forged.md")
        write(path, NOTE.replace("title: Export Notes", "title: Forged\nauthor: ana").replace("# Export Notes", "# Forged"))
        sh(root, "git", "add", "-A")
        rc, out = guard(notes, "check", "--staged")
        ok("negative: a new note claiming another registered author FAILS before stamping", rc != 0 and "ATTRIBUTION" in out, "rc=%d" % rc)
        guard(notes, "stamp", "--staged")
        ok("stamp sets a new note author from git (alex), not from the note", "author: alex" in read(path))
        rc, out = guard(notes, "check", "--staged")
        ok("after stamping, the note passes", rc == 0, out.strip()[-200:])
        sh(root, "git", "commit", "-qm", "note")

        # range mode: a note introduced by an unregistered author
        sh(root, "git", "checkout", "-qb", "pr2")
        sh(root, "git", "config", "user.email", "stranger@corp.test")
        write(os.path.join(notes, "log", "journal", "x.md"),
              NOTE.replace("title: Export Notes", "title: X\nauthor: alex\nupdated_by: alex").replace("# Export Notes", "# X"))
        sh(root, "git", "add", "-A")
        sh(root, "git", "commit", "-qm", "stranger")
        base = sh(root, "git", "rev-parse", "HEAD~1")[1].strip()
        rc, out = guard(notes, "check", "--range", "%s...HEAD" % base)
        ok("negative: in range mode, a note introduced by an unregistered author FAILS", rc != 0 and "not a registered person" in out, "rc=%d" % rc)

        sh(root, "git", "config", "user.email", "")
        write(os.path.join(notes, "log", "journal", "y.md"), NOTE.replace("Export Notes", "Y"))
        sh(root, "git", "add", "-A")
        # Also pin the identity the guard sees to blank: on some machines an inherited global or
        # system email survives the empty repo-level value (seen on Windows).
        blank_env = {"MEMORY_ACTOR_EMAIL": " "}
        guard(notes, "stamp", "--staged", env=blank_env)
        rc, out = guard(notes, "check", "--staged", env=blank_env)
        ok("negative: a blank git email is a blocking IDENTITY failure, never a placeholder person",
           rc != 0 and "IDENTITY" in out and "__TODO" not in read(os.path.join(notes, "log", "journal", "y.md")), "rc=%d" % rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_derived_bytes():
    print("\n01-F7: derived copies are compared byte for byte")
    tmp, root, notes = fresh()
    try:
        with open(os.path.join(notes, ".claude", "skills", "s", "SKILL.md"), "wb") as fh:
            fh.write(b"two\r")
        sh(root, "git", "add", "-A")
        rc, out = guard(notes, "check", "--staged", "--no-attribution")
        ok("negative: a derived copy differing only by LF -> CR is DENIED", rc == 4 and "ACCESS-DERIVED" in out, "rc=%d" % rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_public_paths():
    print("\n10-F10: public site, tests and generated map are not L0")
    tmp, root, notes = fresh()
    try:
        for rel in ("web/app.js", "tools/test_guard.py", "web/data/graph.json"):
            write(os.path.join(notes, rel), "x\n")
            sh(root, "git", "add", "-A")
            rc, out = guard(notes, "check", "--staged", "--no-attribution", env=AGENT)
            ok("negative: an agent writing %s is DENIED" % rel, rc == 4, "rc=%d" % rc)
            sh(root, "git", "reset", "-q", "--hard")
            sh(root, "git", "clean", "-qfd")
        write(os.path.join(notes, "web/data/graph.json"), "x\n")
        sh(root, "git", "add", "-A")
        rc, out = guard(notes, "check", "--staged", "--no-attribution")
        ok("negative: even the owner cannot hand-edit the generated map (bot only)", rc == 4 and "ACCESS-BOT" in out, "rc=%d" % rc)
        rc, out = guard(notes, "check", "--staged", "--no-attribution", env={"MEMORY_ACTOR_KIND": "bot"})
        ok("the bot itself may write the generated map", rc == 0 and "ACCESS" not in out, "rc=%d %s" % (rc, out[-120:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_codeowners():
    print("\n10-F2: CODEOWNERS names real owners or refuses")
    tmp, root, notes = fresh()
    try:
        d = policy(notes)
        d["people"]["alex"]["github"] = "__TODO_GITHUB_LOGIN__"  # the state of a fresh, unfilled policy
        save_policy(notes, d)
        sh(root, "git", "commit", "-qam", "placeholder login")
        rc, out = guard(notes, "codeowners", "--write")
        ok("negative: a placeholder GitHub login is refused (exit 5), nothing written", rc == 5 and
           not os.path.exists(os.path.join(root, ".github", "CODEOWNERS")), "rc=%d" % rc)
        d = policy(notes)
        d["people"]["alex"]["github"] = "alex-gh"
        save_policy(notes, d)
        sh(root, "git", "commit", "-qam", "login")
        rc, out = guard(notes, "codeowners", "--write")
        rc2, out2 = guard(notes, "codeowners")
        ok("with a real login it writes `* @login` and the check agrees",
           rc == 0 and rc2 == 0 and "*    @alex-gh" in read(os.path.join(root, ".github", "CODEOWNERS")), out + out2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_open_under_restricted():
    print("\n07-F7: the restricted folder beats an `open` label")
    tmp, root, notes = fresh()
    try:
        write(os.path.join(notes, "context", "restricted", "x.md"),
              NOTE.replace("title: Export Notes", "title: X\nconfidentiality: open").replace("# Export Notes", "# X"))
        sh(root, "git", "add", "-A")
        rc, out = guard(notes, "check", "--staged", "--no-attribution")
        ok("negative: an `open` note under context/restricted/ FAILS", rc == 5 and "SENSITIVITY" in out, "rc=%d" % rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


EXPECTED = 23  # a run that silently stops early must not pass (expected-count check)


def main():
    test_policy_self_demotion()
    test_empty_policy()
    test_rename_and_case()
    test_attribution()
    test_derived_bytes()
    test_public_paths()
    test_codeowners()
    test_open_under_restricted()


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:  # including SystemExit raised by anything the tests touch
        print("  FAIL the run was interrupted: %r" % (e,))
        RESULTS.append(False)
    passed = sum(RESULTS)
    print("\n%d passed, %d failed (%d of %d expected checks ran)" % (passed, len(RESULTS) - passed, len(RESULTS), EXPECTED))
    sys.exit(0 if passed == len(RESULTS) == EXPECTED else 1)
