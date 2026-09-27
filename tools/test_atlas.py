#!/usr/bin/env python3
"""
test_atlas.py - the published atlas carries features, gaps and trials, and leaks none of what it
withholds. Every redaction rule in build_atlas.verify_public is shown to FAIL on a tampered file,
because a check that has never failed has not been shown to check anything.

    python3 tools/test_atlas.py

Standard library only; builds a throwaway git repo with this project's policy.
"""
import copy
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
GUARD = os.path.join(REPO, "scripts", "memory_guard.py")
ATLAS = os.path.join(REPO, "scripts", "build_atlas.py")
RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + str(detail)) if detail else ""))


def sh(cwd, *cmd, env=None):
    e = dict(os.environ)
    for k in ("MEMORY_ACTOR_KIND", "MEMORY_ACTOR_EMAIL", "MEMORY_AGENT", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE",
              "CLAUDE_CODE_ENTRYPOINT", "KIRO_AGENT", "CURSOR_AGENT"):
        e.pop(k, None)
    e.update(env or {})
    e.setdefault("PYTHONIOENCODING", "utf-8")
    e.setdefault("PYTHONUTF8", "1")
    p = subprocess.run(list(cmd), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", env=e)
    return p.returncode, p.stdout + p.stderr


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def note(title, body, extra="", rel_to="Core", ntype="note"):
    return "---\ntitle: %s\ntype: %s\ntags: [t]\n%s---\n\n# %s\n\n%s\n\n## Relations\n- relates_to [[%s]]\n" % (
        title, ntype, extra, title, body, rel_to)


def fixture(tmp):
    root = os.path.join(tmp, "cairn")
    os.makedirs(os.path.join(root, "governance"))
    os.makedirs(os.path.join(root, ".basic-memory"))
    testpolicy.install(os.path.join(root, "governance"))
    write(root, ".basic-memory/project.json", '{"name": "atlas-test"}\n')
    os.makedirs(os.path.join(root, "scripts"))
    write(root, "scripts/tool.py", "print('covered')\n")
    write(root, "CORE.md", note("Core", "The big picture.\n\n## Observations\n- [fact] We build a thing", rel_to="Export"))
    write(root, "features/export.md", """---
title: Export
type: feature
status: live
owner: alex
covers: ["scripts/tool.py"]
tags: [feature]
---

# Export

## Card
Export turns queries into spreadsheets.

## Contract
Export promises SECRET-CONTRACT-TEXT.

## Observations
- [fact] Export is owned by alex

## Relations
- part_of [[Core]]
""")
    write(root, "trials/doubt.md", note("Trial - the export card is wrong", "## Observations\n- [trial] SECRET-HYPOTHESIS-BODY",
                                        extra="status: live\nhypothesis: SECRET-HYPOTHESIS\nowner: alex\n"
                                              "for: [alex]\nexpires: 2099-01-01\n", ntype="trial"))
    write(root, "evals/export.md", note("Export Evals", "## Observations\n- [eval] recall \"SECRET-EVAL-QUESTION\" includes (^abcdef)"))
    write(root, "log/gaps/export.md", note("Gaps - Export", "What agents needed.\n\n## Observations\n- [gap] SECRET-GAP-TEXT",
                                           rel_to="Export", ntype="gaps"))
    write(root, "context/restricted/deal.md", note("Deal", "## Observations\n- [fact] SECRET-RESTRICTED",
                                                   extra="confidentiality: restricted\n"))
    write(root, "context/restricted/leaky.md", note("Leaky Open", "## Observations\n- [fact] SECRET-OPEN-RESTRICTED-BODY",
                                                    extra="confidentiality: open\n"))
    write(root, "context/strategy.md", note("Strategy", "SECRET-L2-BRIEF sentence here.\n\n## Observations\n- [fact] x\n\n"
                                            "## Relations\n- relates_to [[Deal]]", rel_to="Core"))
    write(root, ".memory/session/s1.json", json.dumps({"session": "s1", "ref": "main@abc", "turn": 2,
                                                       "started": "2026-09-23T10:00:00", "loaded": {
                                                           "CORE": {"depth": "full", "turn": 1, "hash": "x"}}}))
    sh(root, "git", "init", "-q")
    sh(root, "git", "config", "user.email", "alex@example.test")
    sh(root, "git", "config", "user.name", "Alex Tester")
    sh(root, sys.executable, GUARD, "stamp", "--all")
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", "fixture")
    return root


def main():
    tmp = tempfile.mkdtemp()
    try:
        root = fixture(tmp)
        pub_path = os.path.join(tmp, "graph.json")
        full_path = os.path.join(tmp, "graph.full.json")
        rc, out = sh(root, sys.executable, ATLAS, "--out", pub_path)
        ok("public build succeeds", rc == 0, out.strip()[-300:])
        rc2, out2 = sh(root, sys.executable, ATLAS, "--full", "--out", full_path)
        pub = json.load(open(pub_path))
        full = json.load(open(full_path))
        raw = open(pub_path).read()

        print("\ncontent")
        ok("features are listed with status and owner",
           [(f["title"], f["status"], f["owner"]) for f in pub["features"]] == [("Export", "live", "alex")],
           pub["features"])
        ok("a gap is counted against its feature", pub["features"][0]["gaps"] == 1 and len(pub["gaps"]) == 1)
        ok("a live trial is listed with its expiry", pub["trials"] and pub["trials"][0]["status"] == "live"
           and pub["trials"][0]["expires"] == "2099-01-01", pub["trials"])
        ok("stats count features, gaps, live trials",
           (pub["stats"]["features"], pub["stats"]["gaps"], pub["stats"]["live_trials"]) == (1, 1, 1), pub["stats"])
        ok("the full build carries the hypothesis, covers and the local session", (
            full["trials"][0]["hypothesis"] == "SECRET-HYPOTHESIS" and full["features"][0]["covers"] == ["scripts/tool.py"]
            and full["sessions"] and full["sessions"][0]["session"] == "s1"))

        print("\nredaction (public)")
        for secret in ("SECRET-HYPOTHESIS", "SECRET-EVAL-QUESTION", "SECRET-GAP-TEXT", "SECRET-RESTRICTED",
                       "SECRET-CONTRACT-TEXT", "scripts/tool.py", "SECRET-OPEN-RESTRICTED-BODY", "SECRET-L2-BRIEF",
                       "Deal", "context/restricted", "Leaky Open"):
            ok("%s appears nowhere in the public file" % secret, secret not in raw)
        ok("no local session ledger in the public file", pub["sessions"] == [])
        rc, out = sh(root, sys.executable, ATLAS, "--verify", pub_path)
        ok("verify passes on the real public build", rc == 0, out.strip())

        print("\nevery rule can fail")
        tamper = [
            ("mode", lambda d: d.update(mode="full")),
            ("restricted note", lambda d: d["nodes"].append(dict(d["nodes"][0], id="x", confidentiality="restricted"))),
            ("internal body", lambda d: next(n for n in d["nodes"] if n["confidentiality"] != "open"
                                             and not n["path"].startswith(("trials/", "evals/"))).update(body="x")),
            ("trial hypothesis", lambda d: d["trials"][0].update(hypothesis="x")),
            ("trial audience names", lambda d: d["trials"][0].update(audience=["alex"])),
            ("experiment brief", lambda d: [n.update(brief="x") for n in d["nodes"] if n["path"].startswith("evals/")]),
            ("feature covers", lambda d: d["features"][0].update(covers=["a"])),
            ("gap text", lambda d: d["gaps"][0].update(text="x")),
            ("session ledger", lambda d: d.update(sessions=[{"session": "s"}])),
            ("commit message", lambda d: d["activity"].append({"sha": "abc", "message": "x"})),
            # audit 07-F2 / 07-F3 / 07-F4
            ("L2 summary (brief above brief_levels)", lambda d: next(n for n in d["nodes"] if n["level"] == "L2").update(brief="SECRET")),
            ("unknown top-level field", lambda d: d.update(extra="SECRET")),
            ("unknown nested node field", lambda d: d["nodes"][0].update(secret_notes="SECRET")),
            ("wrong schema version", lambda d: d.update(schema=2)),
            ("missing required section", lambda d: d.pop("health")),
            ("duplicate node id", lambda d: d["nodes"].append(dict(d["nodes"][0]))),
            ("edge to a note that is not public", lambda d: d["edges"].append({"source": d["nodes"][0]["id"], "target": "context/restricted/deal", "type": "relates_to", "dependency": False})),
            ("sessions as an object", lambda d: d.update(sessions={})),
            ("javascript: repo_url", lambda d: d.update(repo_url="javascript:alert(1)")),
            ("feature card above brief_levels", lambda d: d["features"][0].update(card="SECRET")),
            ("queue proposal summary above L0", lambda d: d["queue"]["proposals"].append({"id": d["nodes"][0]["id"], "title": "t", "status": "open", "author": None, "age_days": 1, "level": "L2", "brief": "SECRET"})),
            ("identity with publish_authors false", lambda d: (d["publication"].update(publish_authors=False), d["nodes"][0].update(author="someone"))),
            ("restricted path in activity", lambda d: d["activity"][0]["paths"].append("context/restricted/deal.md")),
            ("health issue naming a non-public note", lambda d: d["health"]["issues"].append({"kind": "broken_link", "severity": "minor", "id": "context/restricted/deal", "title": "Deal", "detail": "x"})),
        ]
        for name, fn in tamper:
            d = copy.deepcopy(pub)
            fn(d)
            p = os.path.join(tmp, "tampered.json")
            json.dump(d, open(p, "w"))
            rc, out = sh(root, sys.executable, ATLAS, "--verify", p)
            ok("negative: verify FAILS on a leaked %s" % name, rc == 1, out.strip().splitlines()[-1] if out.strip() else "")
        p = os.path.join(tmp, "dupkey.json")
        raw_pub = open(pub_path).read()
        open(p, "w").write(raw_pub.replace('"schema": 3,', '"schema": 3, "schema": 3,', 1))
        rc, out = sh(root, sys.executable, ATLAS, "--verify", p)
        ok("negative: verify FAILS on a duplicate JSON key", rc == 1, out.strip()[-80:])
        d = copy.deepcopy(pub)
        d["stats"]["notes"] += 1  # schema-valid, redaction-valid, but not what the notes produce
        p = os.path.join(tmp, "drift.json")
        json.dump(d, open(p, "w"))
        rc, out = sh(root, sys.executable, ATLAS, "--verify", pub_path, "--against-source")
        rc2, out2 = sh(root, sys.executable, ATLAS, "--verify", p, "--against-source")
        ok("--against-source: the real build matches its source; a hand-edited file does not",
           rc == 0 and rc2 == 1, (out + out2).strip()[-160:])

        print("\npublish_authors false (07-F4)")
        pol_path = os.path.join(root, "governance", "roles.json")
        pol = json.load(open(pol_path))
        pol["publication"]["publish_authors"] = False
        json.dump(pol, open(pol_path, "w"), indent=2)
        sh(root, "git", "commit", "-qam", "no authors")
        p = os.path.join(tmp, "noauth.json")
        rc, out = sh(root, sys.executable, ATLAS, "--out", p)
        d = json.load(open(p))
        ids = [n.get(k) for n in d["nodes"] for k in ("author", "updated_by", "agent")] + \
              [a.get(k) for a in d["activity"] for k in ("author", "agent")]
        ok("no author, editor or agent anywhere when publish_authors is false", rc == 0 and not any(ids), out.strip()[-160:])

        print("\ncli (07-F10)")
        rc, out = sh(root, sys.executable, ATLAS, "--out", "bare.json")
        ok("--out with a bare filename works", rc == 0 and os.path.isfile(os.path.join(root, "bare.json")), out.strip()[-120:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(RESULTS)
    print("\n%d passed, %d failed" % (passed, len(RESULTS) - passed))
    return 0 if passed == len(RESULTS) == 47 else 1  # expected-count check: a run that stops early is red


if __name__ == "__main__":
    sys.exit(main())
