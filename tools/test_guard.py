# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
test_guard.py - the guard's claim, feature and write-back checks, run against throwaway git repos.

    python3 tools/test_guard.py

Every check here is paired with a case that must FAIL, because a gate nobody has seen fail is not a
gate. Standard library only; builds its repos under the system temp directory and deletes them.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testpolicy  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
# MEMORY_GUARD_UNDER_TEST lets CI run the TRUSTED base revision's tests against the PR's guard.
GUARD = os.environ.get("MEMORY_GUARD_UNDER_TEST") or os.path.join(REPO, "scripts", "memory_guard.py")
RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))


def sh(cwd, *cmd, env=None):
    e = dict(os.environ)
    for k in ("MEMORY_ACTOR_KIND", "MEMORY_ACTOR_EMAIL", "MEMORY_AGENT", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE",
              "CLAUDE_CODE_ENTRYPOINT", "KIRO_AGENT", "CURSOR_AGENT"):
        e.pop(k, None)
    e.update(env or {})
    p = subprocess.run(list(cmd), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, env=e)
    return p.returncode, p.stdout + p.stderr


def make_repo(tmp, prefix=""):
    """A git repo with this project's policy. prefix='memory' makes a project tier inside code."""
    root = os.path.join(tmp, "repo")
    notes = os.path.join(root, prefix) if prefix else root
    os.makedirs(os.path.join(notes, "governance"))
    os.makedirs(os.path.join(notes, ".basic-memory"))
    testpolicy.install(os.path.join(notes, "governance"))
    with open(os.path.join(notes, ".basic-memory", "project.json"), "w") as fh:
        fh.write('{"name": "test-memory"}\n')
    sh(root, "git", "init", "-q")
    sh(root, "git", "config", "user.email", "alex@example.test")
    sh(root, "git", "config", "user.name", "Alex Tester")
    # Commit the policy itself. Left untracked, it counts as a change in every check, and an agent
    # is then (correctly) denied for "editing" roles.json - which once made this suite blame the
    # guard for a fixture bug.
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", "policy")
    return root, notes


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def guard(notes, *args, env=None):
    return sh(notes, sys.executable, GUARD, *args, env=env)


NOTE = """---
title: Export Notes
type: context
tags: [export]
---

# Export Notes

How exporting works.

## Observations
- [decision] Exporting uses Streamwrite, not the Gridkit writer
- [fact] Exports run on a job queue with 4 workers
- [fact] The write step targets XLSX at 30k rows per second
- [constraint] Reports are delivered by 07:00 UTC
- [risk] Postgres upgrades have changed collation order twice this year

## Relations
- relates_to [[Core]]
"""


def test_claim_ids():
    print("\nclaim ids")
    tmp = tempfile.mkdtemp()
    try:
        root, notes = make_repo(tmp)
        p = os.path.join(notes, "context", "export.md")
        write(p, NOTE)
        guard(notes, "stamp", "--all")
        first = re.findall(r"\^([0-9a-f]{6})\s*$", read(p), re.M)
        ok("every claim gets an id", len(first) == 5 and len(set(first)) == 5, str(first))
        sh(root, "git", "add", "-A")
        sh(root, "git", "commit", "-qm", "base")

        # Five realistic agent edits, each dropping the id - the failure this exists to catch.
        text = read(p)
        edits = [
            (r"- \[decision\] Exporting uses Streamwrite, not the Gridkit writer \^\w+",
             "- [decision] Exporting uses Streamwrite, not Gridkit's writer (ADR-1)"),
            (r"- \[fact\] Exports run on a job queue with 4 workers \^\w+",
             "- [fact] Exports run on a job queue with 8 workers"),
            (r"- \[fact\] The write step targets XLSX at 30k rows per second \^\w+",
             "- [fact] The write step targets XLSX at 30k rows per second, one sheet by default"),
            (r"- \[constraint\] Reports are delivered by 07:00 UTC \^\w+",
             "- [constraint] Reports are delivered by 07:00 UTC on working days"),
            (r"- \[risk\] Postgres upgrades have changed collation order twice this year \^\w+",
             "- [risk] Collation order shifted after two Postgres upgrades in 2026"),
        ]
        for pat, rep in edits:
            text = re.sub(pat, rep, text)
        write(p, text)
        guard(notes, "stamp", "--all")
        after = re.findall(r"\^([0-9a-f]{6})\s*$", read(p), re.M)
        kept = len(set(first) & set(after))
        ok("ids survive realistic edits: at least 4 of 5 (claim-id tripwire)", kept >= 4,
           "%d of 5 kept" % kept)
        ok("no claim is left without an id after edits", len(after) == 5)

        # A copy-pasted line must not share an identity.
        text = read(p)
        dup_line = [ln for ln in text.split("\n") if ln.startswith("- [fact] Exports run")][0]
        write(p, text.replace(dup_line, dup_line + "\n" + dup_line))
        rc, out = guard(notes, "check", "--no-attribution")
        ok("negative: a duplicated id FAILS check before stamping", "CLAIM-ID" in out and rc != 0,
           "rc=%d" % rc)
        guard(notes, "stamp", "--all")
        ids = re.findall(r"\^([0-9a-f]{6})\s*$", read(p), re.M)
        ok("stamp gives the copy a fresh id", len(ids) == 6 and len(set(ids)) == 6)

        # Claims inside a code example are not claims.
        write(p, read(p) + "\n```\n- [fact] example inside a fence\n```\n")
        guard(notes, "stamp", "--all")
        ok("a claim inside a code fence gets no id",
           "- [fact] example inside a fence\n" in read(p))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


FEATURE = """---
title: Export Pipeline
type: feature
status: {status}
owner: alex
covers: [{covers}]
tags: [feature]
---

# Export Pipeline
{card}
## Contract
Produces an XLSX from a query.

## Observations
- [fact] Owns the write step

## Relations
- relates_to [[Core]]
"""


def test_features_and_writeback():
    print("\nfeatures and write-back (project tier: memory inside a code repo)")
    tmp = tempfile.mkdtemp()
    try:
        root, notes = make_repo(tmp, prefix="memory")
        write(os.path.join(root, "src", "export", "writer.py"), "x = 1\n")
        write(os.path.join(root, "src", "billing", "pay.py"), "y = 1\n")
        fp = os.path.join(notes, "features", "export-pipeline.md")
        good_card = "\n## Card\nTurns a query into an XLSX. Live. In flight: retries.\n"
        write(fp, FEATURE.format(status="live", covers='"src/export/**"', card=good_card))
        sh(root, "git", "add", "-A")
        sh(root, "git", "commit", "-qm", "base")
        rc, out = guard(notes, "check", "--no-attribution", "--range", "HEAD~0")
        rc, out = guard(notes, "check", "--no-attribution", "--staged")

        # a valid feature, checked directly
        sh(root, "git", "commit", "--allow-empty", "-qm", "noop")
        write(fp, read(fp).replace("Live. In flight: retries.", "Live. In flight: retries and backoff."))
        rc, out = guard(notes, "check", "--no-attribution")
        ok("a valid feature passes", "FEATURE" not in out.replace("FEATURE-COVERS", ""), out.strip()[-160:])

        # negatives
        write(fp, FEATURE.format(status="shipping", covers='"src/export/**"', card=""))
        rc, out = guard(notes, "check", "--no-attribution")
        ok("negative: bad status FAILS", "feature status 'shipping'" in out and rc != 0)
        ok("negative: missing card FAILS", "no `## Card` section" in out)
        write(fp, FEATURE.format(status="live", covers='"src/exporter/**"', card=good_card))
        rc, out = guard(notes, "check", "--no-attribution")
        ok("negative: a covers glob matching no file WARNS", "matches no file" in out)
        long_card = "\n## Card\n" + " ".join(["word"] * 200) + "\n"
        write(fp, FEATURE.format(status="live", covers='"src/export/**"', card=long_card))
        rc, out = guard(notes, "check", "--no-attribution")
        ok("negative: a 200-word card WARNS", "card is 200 words" in out)
        sh(root, "git", "checkout", "-q", "--", ".")

        # write-back
        write(os.path.join(root, "src", "export", "writer.py"), "x = 2\n")
        rc, out = guard(notes, "check", "--no-attribution")
        ok("negative: covered code changed, feature untouched -> WRITEBACK warns",
           "WRITEBACK" in out and "Export Pipeline" in out)
        write(fp, read(fp).replace("Owns the write step", "Owns the write step and its retries"))
        rc, out = guard(notes, "check", "--no-attribution")
        ok("covered code changed WITH the feature note -> no WRITEBACK", "WRITEBACK" not in out)
        sh(root, "git", "checkout", "-q", "--", ".")
        write(os.path.join(root, "src", "billing", "pay.py"), "y = 2\n")
        rc, out = guard(notes, "check", "--no-attribution")
        ok("uncovered code changed -> no WRITEBACK", "WRITEBACK" not in out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_levels_for_new_folders():
    print("\nlevels for the new folders")
    tmp = tempfile.mkdtemp()
    try:
        root, notes = make_repo(tmp)
        write(os.path.join(notes, "features", "x.md"),
              FEATURE.format(status="planned", covers="", card="\n## Card\nA thing.\n"))
        env = {"MEMORY_ACTOR_KIND": "agent"}
        rc, out = guard(notes, "check", "--no-attribution", env=env)
        ok("negative: an agent writing a feature (L1) is DENIED", "ACCESS-LEVEL" in out and rc == 4,
           "rc=%d" % rc)
        os.remove(os.path.join(notes, "features", "x.md"))
        write(os.path.join(notes, "trials", "t.md"), """---
title: Trial t
type: trial
status: live
hypothesis: The architecture note is too vague
owner: alex
expires: 2099-01-01
tags: [trial]
---
# Trial t
## Relations
- relates_to [[Core]]
""")
        rc, out = guard(notes, "check", "--no-attribution", env=env)
        ok("an agent MAY open a trial (L0)", "ACCESS-LEVEL" not in out, "rc=%d" % rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_agent_marker_defaults_to_agent():
    print("\nan agent committing from its own shell")
    tmp = tempfile.mkdtemp()
    try:
        root, notes = make_repo(tmp)
        write(os.path.join(notes, "features", "x.md"),
              FEATURE.format(status="planned", covers="", card="\n## Card\nA thing.\n"))
        rc, out = guard(notes, "check", "--no-attribution", env={"CLAUDE_CODE_SESSION_ID": "abc"})
        ok("negative: no MEMORY_ACTOR_KIND but a Claude Code session marker -> treated as agent, DENIED",
           "ACCESS-LEVEL" in out and rc == 4, "rc=%d" % rc)
        rc, out = guard(notes, "check", "--no-attribution")
        ok("the same change by the owner in a plain terminal passes the level gate", "ACCESS-LEVEL" not in out,
           "rc=%d" % rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_project_tier_from_repo_root():
    print("\nproject tier found from the code repo's root")
    tmp = tempfile.mkdtemp()
    try:
        root, notes = make_repo(tmp, prefix="memory")
        write(os.path.join(notes, "context", "export.md"), NOTE)
        # (A "guard check from the repo root passes" assertion was dropped: it also passed with the fix
        # reverted, because check walks git changes, so it measured nothing.)
        spec = __import__("importlib.util").util.spec_from_file_location("mg", GUARD)
        mg = __import__("importlib.util").util.module_from_spec(spec); spec.loader.exec_module(mg)
        ok("Ctx resolves notes_root to <repo>/memory", os.path.realpath(mg.Ctx._find_notes_root(root)) ==
           os.path.realpath(notes))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_trailing_reference():
    print("\na claim that ENDS with a reference to another claim")
    tmp = tempfile.mkdtemp()
    try:
        root, notes = make_repo(tmp)
        write(os.path.join(notes, "context", "export.md"), NOTE)
        guard(notes, "stamp", "--all")
        target = re.findall(r"\^([0-9a-f]{6})\s*$", read(os.path.join(notes, "context", "export.md")), re.M)[0]
        sh(root, "git", "add", "-A"); sh(root, "git", "commit", "-qm", "base")
        ep = os.path.join(notes, "evals", "e.md")
        write(ep, "---\ntitle: E\ntype: note\ntags: [eval]\n---\n# E\n## Observations\n"
                  "- [eval] recall \"writer\" includes ^%s\n## Relations\n- relates_to [[Export Notes]]\n" % target)
        rc, out = guard(notes, "check", "--no-attribution")
        ok("negative: before stamping, the shared id FAILS check", "is the id of claims in 2 notes" in out and rc != 0)
        guard(notes, "stamp", "--all")
        line = [l for l in read(ep).splitlines() if l.startswith("- [eval]")][0]
        ok("stamp keeps the reference and appends the eval's own id",
           re.search(r"includes \^%s \^[0-9a-f]{6}$" % target, line) is not None, line)
        rc, out = guard(notes, "check", "--no-attribution")
        ok("after stamping, no collision", "is the id of claims" not in out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_claim_ids()
    test_features_and_writeback()
    test_levels_for_new_folders()
    test_agent_marker_defaults_to_agent()
    test_project_tier_from_repo_root()
    test_trailing_reference()
    passed = sum(RESULTS)
    print("\n%d passed, %d failed" % (passed, len(RESULTS) - passed))
    sys.exit(0 if passed == len(RESULTS) == 22 else 1)  # a run that stops early is red
