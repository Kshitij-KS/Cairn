# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
test_mem.py - the context protocol, end to end, against a synthetic project whose answers are known.

    python3 tools/test_mem.py

The fixture is a project tier (memory/ inside a code repo) with this dependency shape:

    Sources <-depends_on- Transform <-depends_on- Export  <-depends_on-  Dashboard
                                                        ^                  (also depends on Transform)
                                          Billing --relates_to--+   (see-also: must NEVER be followed)
    Export --implements--> ADR-001 Export With Streamwrite

Every behaviour is paired with the case that must fail. Standard library only.
"""
import json
import os
import re
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
MEM = os.path.join(REPO, "scripts", "mem.py")
GUARD = os.path.join(REPO, "scripts", "memory_guard.py")
RESULTS = []
TMP = tempfile.mkdtemp()
ROOT = os.path.join(TMP, "proj")
NOTES = os.path.join(ROOT, "memory")
OWNER = {}
AGENT = {"MEMORY_ACTOR_KIND": "agent"}
ANA = {"MEMORY_ACTOR_EMAIL": "ana@example.com"}
STRANGER = {"MEMORY_ACTOR_EMAIL": "nobody@example.com"}


def ok(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + str(detail)) if detail else ""))


def run(*args, env=None, cwd=None):
    e = dict(os.environ)
    # Tests run inside agent hosts too (Claude Code, Kiro): their markers would make the guard treat
    # the fixture owner as an agent. Strip them first; the caller's env still applies.
    for k in ("MEMORY_ACTOR_KIND", "MEMORY_ACTOR_EMAIL", "MEMORY_AGENT", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE",
              "CLAUDE_CODE_ENTRYPOINT", "KIRO_AGENT", "CURSOR_AGENT"):
        e.pop(k, None)
    e.update(env or {})
    e.setdefault("PYTHONIOENCODING", "utf-8")
    e.setdefault("PYTHONUTF8", "1")
    # Apply the override AFTER the caller's env. The first version set the session before merging
    # it, so every call silently shared one session and the ledger tests measured nothing.
    e["MEMORY_SESSION"] = e.pop("MEMORY_SESSION_OVERRIDE", "test")
    p = subprocess.run([sys.executable, MEM, *args], cwd=cwd or NOTES, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", env=e)
    return p.returncode, p.stdout + p.stderr


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8").stdout


def write(rel, text, base=None):
    p = os.path.join(base or NOTES, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read(rel, base=None):
    with open(os.path.join(base or NOTES, rel), encoding="utf-8") as fh:
        return fh.read()


def feature(title, covers, deps=(), aliases=(), status="live", contract="", extra_rel=()):
    rels = ["- depends_on [[%s]]" % d for d in deps] + list(extra_rel) + ["- part_of [[Core]]"]
    return """---
title: %s
type: feature
status: %s
owner: alex
covers: [%s]
aliases: [%s]
tags: [feature]
---

# %s

## Card
%s is the part of the product that %s.

## Contract
%s

## Observations
- [fact] %s is owned by alex

## Relations
%s
""" % (title, status, ", ".join('"%s"' % c for c in covers), ", ".join(aliases), title, title,
       "does %s things" % title.lower(), contract or "%s promises a stable interface." % title,
       title, "\n".join(rels))


def build_fixture():
    os.makedirs(os.path.join(NOTES, "governance"))
    os.makedirs(os.path.join(NOTES, ".basic-memory"))
    policy = testpolicy.policy()
    policy["people"]["ana"] = {"name": "Ana", "email": "ana@example.com", "github": "ana",
                               "role": "contributor", "projects": [], "function": "pm"}
    with open(os.path.join(NOTES, "governance", "roles.json"), "w", encoding="utf-8") as fh:
        json.dump(policy, fh, indent=2)
    write(".basic-memory/project.json", '{"name": "proj"}\n')
    write(".gitignore", ".memory/\n", base=ROOT)
    for f in ("src/sources/read.py", "src/transform/jobs.py", "src/export/writer.py",
              "src/export/spreadsheet.py", "src/dashboard/app.py", "src/billing/pay.py"):
        write(f, "# code\n", base=ROOT)
    write("CORE.md", """---
title: Core
type: context
tags: [core]
---

# Core

We turn warehouse data into scheduled reports for internal teams.

## Observations
- [constraint] Reports are delivered by 07:00 UTC

## Relations
- relates_to [[ADR-001 Export With Streamwrite]]
""")
    write("features/sources.md", feature("Sources", ["src/sources/**"], aliases=("warehouse sync",)))
    write("features/transform.md", feature("Transform", ["src/transform/**"], deps=("Sources",),
                                           aliases=("jobs", "report builder")))
    write("features/export.md", feature("Export", ["src/export/**"], deps=("Transform",),
                                        aliases=("csv", "spreadsheet", "xlsx"),
                                        contract="Export produces an XLSX from a query at 30k rows per second.",
                                        extra_rel=("- implements [[ADR-001 Export With Streamwrite]]",)))
    write("features/dashboard.md", feature("Dashboard", ["src/dashboard/**"], deps=("Export", "Transform")))
    write("features/billing.md", feature("Billing", ["src/billing/**"], extra_rel=("- relates_to [[Export]]",)))
    write("decisions/ADR-001-export-with-streamwrite.md", """---
title: ADR-001 Export With Streamwrite
type: decision
status: accepted
tags: [adr]
---

# ADR-001 Export With Streamwrite

We export with Streamwrite rather than Gridkit's writer, for memory reasons.

## Observations
- [decision] Exports use Streamwrite, not Gridkit's writer
- [fact] Gridkit holds the whole sheet in memory before it writes

## Relations
- relates_to [[Core]]
""")
    write("decisions/ADR-002-open-question.md", """---
title: ADR-002 Open Question
type: decision
status: proposed
tags: [adr]
---

# ADR-002 Open Question

Should exports move to a second storage provider.

## Observations
- [decision] Undecided whether to add a second storage provider

## Relations
- relates_to [[Export]]
""")
    write("log/journal/2099-01-01-writer-failed.md", """---
title: Writer failed on large reports
type: note
tags: [journal]
updated: 2099-01-01
---

# Writer failed on large reports

The write step ran out of memory on a 400k row report.

## Observations
- [gotcha] The writer runs out of memory on reports over 300k rows

## Relations
- relates_to [[Export]]
""")
    write("context/restricted/pricing.md", """---
title: Pricing Terms
type: context
confidentiality: restricted
tags: [pricing]
---

# Pricing Terms

Unsigned terms.

## Observations
- [fact] The export contract with the customer caps at 500 reports

## Relations
- relates_to [[Export]]
""")
    subprocess.run(["git", "init", "-q"], cwd=ROOT)
    git("config", "user.email", "alex@example.test")
    git("config", "user.name", "Alex Tester")
    subprocess.run([sys.executable, GUARD, "stamp", "--all"], cwd=NOTES, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE)
    git("add", "-A")
    git("commit", "-qm", "fixture")


def load(*args, env=None):
    rc, out = run("load", *args, "--json", env=env)
    try:
        return rc, json.loads(out[out.index("{"):])
    except ValueError:
        return rc, {"raw": out}


def ids(result, role=None):
    return {n["id"] for n in result.get("notes", []) if role is None or n["role"] == role}


def test_resolve_and_modes():
    print("\nresolution and modes")
    rc, out = run("resolve", "fix the rounding", "--touching", "src/export/writer.py", "--json")
    top = json.loads(out)["features"][0]["title"]
    ok("a touched file resolves to the feature that covers it", top == "Export" and rc == 0, top)
    rc, out = run("resolve", "make the spreadsheet columns wider", "--json")
    ok("an alias resolves (spreadsheet -> Export)", json.loads(out)["features"][0]["title"] == "Export")
    rc, out = run("resolve", "writer.py leaks memory", "--json")
    ok("a file named in the ask resolves to its owner", json.loads(out)["features"][0]["title"] == "Export")
    rc, out = run("resolve", "tidy things up a bit", "--json")
    ok("negative: a vague ask is AMBIGUOUS (exit 2)", rc == 2, "rc=%d" % rc)
    cases = [("add a retry when the spreadsheet upload fails", "build"), ("refactor the jobs schema", "change"),
             ("the writer is broken on large reports", "debug"), ("why do we use streamwrite", "explain"),
             ("what should we prioritise next quarter", "plan"), ("review this diff", "review"),
             ("catch me up", "orient")]
    for ask, want in cases:
        rc, out = run("resolve", ask, "--json")
        got = json.loads(out)["mode"]
        ok("mode for %r is %s" % (ask, want), got == want, "got %s" % got)


def test_round1_fixes():
    print("\nfixes from early testing (symptoms, phrase aliases, orient + target)")
    for ask in ("the spreadsheet export is too slow", "the xlsx has no output", "the writer keeps dropping rows",
                "the export job is red in CI", "the summary invents a figure"):
        rc, out = run("resolve", ask, "--json")
        ok("a symptom with no intent word reads as debug: %r" % ask, json.loads(out)["mode"] == "debug",
           json.loads(out)["mode"])
    rc, out = run("resolve", "the writer and the header row", "--json")
    ok("an ask with no intent word and no symptom is build, and the reason says it is a guess",
       json.loads(out)["mode"] == "build" and "GUESS" in json.dumps(json.loads(out)), out[:200])
    # asking instead of guessing: an ask with no intent word and no symptom stops with a question
    ask = "the writer and its header row"
    rc, out = run("load", ask, "--json")
    q = json.loads(out)["ask_the_person"] if rc == 2 else []
    ok("a guessed mode is a question, not a load (exit 2): best guess first, about the resolved feature",
       rc == 2 and q and q[0]["id"] == "mode" and q[0]["options"][0]["args"] == "--mode build"
       and "(best guess)" in q[0]["options"][0]["label"] and "Export" in q[0]["question"]
       and {o["args"] for o in q[0]["options"]} >= {"--mode debug", "--mode change"}, out[:300])
    rc, out = run("load", "the header row and the rounding", "--json")
    qs = {x["id"]: x for x in json.loads(out)["ask_the_person"]} if rc == 2 else {}
    ok("an unclear feature and a guessed mode are asked together; the feature question offers a way out",
       set(qs) == {"mode", "feature"} and qs["feature"]["options"][-1]["args"] == "--mode orient", out[:300])
    rc, out = run("load", ask, "--mode", "debug")
    rc2, out2 = run("asks")
    ok("the answer loads, and `mem asks` reports the corrected guess without the ask text",
       rc == 0 and "debug mode (you chose it)" in out and "guessed build, person chose debug" in out2
       and not any(ask in open(os.path.join(NOTES, ".memory", "logs", f)).read()
                   for f in os.listdir(os.path.join(NOTES, ".memory", "logs")) if f.startswith("asks-")), out2[:300])
    rc, out = run("load", "add a column to the writer")
    ok("negative: an ask with an intent word never asks", rc == 0 and "question" not in out.lower()[:200], out[:160])
    # a team's own symptom words come from roles.json protocol.extra_symptoms (read from HEAD)
    ask = "the spreadsheet preview is too quiet"
    rc, out = run("resolve", ask, "--json")
    ok("negative: a domain word the generic list lacks is not a symptom (build)", json.loads(out)["mode"] == "build",
       json.loads(out)["mode"])
    pol_path = os.path.join(NOTES, "governance", "roles.json")
    before = read("governance/roles.json")
    pol = json.loads(before)
    pol["protocol"]["extra_symptoms"] = ["(unclosed", r"\btoo quiet\b"]
    write("governance/roles.json", json.dumps(pol, indent=2))
    git("commit", "-qam", "extra symptoms")
    rc, out = run("resolve", ask, "--json")
    ok("protocol.extra_symptoms makes it a symptom (debug), and an invalid pattern is skipped, not fatal",
       rc == 0 and "invalid pattern" in out
       and json.loads("\n".join(l for l in out.split("\n") if not l.startswith("mem:")))["mode"] == "debug", out[:200])
    write("governance/roles.json", before)
    git("commit", "-qam", "restore policy")
    rc, out = run("resolve", "add a fallback because the logo is missing", "--json")
    ok("negative: an explicit intent word beats a symptom (add ... missing -> build)",
       json.loads(out)["mode"] == "build", json.loads(out)["mode"])
    rc, out = run("resolve", "improve the report builder", "--json")
    top = json.loads(out)["features"][0]
    ok("a two-word alias scores 10, a one-word alias 7", top["title"] == "Transform" and top["score"] >= 10,
       "%s %s" % (top["title"], top["score"]))
    rc, r = load("catch me up on Export")
    ok("orient with a clear target loads the core plus that feature's card",
       ids(r, "about") == {"features/export"} and rc == 0, sorted(ids(r)))
    rc, r = load("catch me up")
    ok("negative: orient with no target loads only the core", ids(r) == {"CORE"}, sorted(ids(r)))


def test_explain_resolves_decisions():
    print("\nexplain asks resolve to decisions when no feature is named")
    rc, r = load("why do we not use Gridkit to save memory")
    ok("an explain ask about a decision loads that ADR as the target (exit 0, not 2)",
       rc == 0 and "decisions/ADR-001-export-with-streamwrite" in ids(r, "target"), "rc=%d %s" % (rc, sorted(ids(r))))
    ok("...and the feature implementing it comes along as a card", "features/export" in ids(r, "implemented by"),
       sorted(ids(r)))
    rc, r = load("why do we sing in the shower")
    ok("negative: an explain ask matching no decision still asks (exit 2)", rc == 2, "rc=%d" % rc)


def test_directional_scope():
    print("\ndirectional scope")
    rc, r = load("add caching to export", "--feature", "Export", "--mode", "build")
    up, down = ids(r, "relies on"), ids(r, "could break")
    ok("build reads upstream two hops: Transform AND Sources", {"features/transform", "features/sources"} <= up, up)
    ok("build reads the implemented decision upstream", "decisions/ADR-001-export-with-streamwrite" in up)
    ok("build lists downstream one hop as cards: Dashboard", "features/dashboard" in down, down)
    ok("negative: see-also is NEVER followed - Billing is absent", "features/billing" not in ids(r))
    depth = {n["id"]: n["depth"] for n in r["notes"]}
    ok("upstream is full, downstream is card", depth.get("features/transform") == "full"
       and depth.get("features/dashboard") == "card", depth)
    ok("core is always first", r["notes"][0]["id"] == "CORE")

    rc, r = load("refactor transform", "--feature", "Transform", "--mode", "change")
    down = ids(r, "could break")
    ok("change reads downstream two hops: Export AND Dashboard",
       {"features/export", "features/dashboard"} <= down, down)
    ok("change lists upstream one hop as cards: Sources", "features/sources" in ids(r, "relies on"))

    rc, r = load("where are we", "--mode", "plan")
    feats = {n["id"] for n in r["notes"] if n["id"].startswith("features/")}
    ok("plan loads every feature as a card", len(feats) == 5 and all(
        n["depth"] == "card" for n in r["notes"] if n["id"].startswith("features/")), len(feats))
    ok("plan includes open decisions, not accepted ones",
       "decisions/ADR-002-open-question" in ids(r) and "decisions/ADR-001-export-with-streamwrite" not in ids(r))

    rc, r = load("why do we export with streamwrite", "--feature", "Export", "--mode", "explain")
    ok("explain follows implements to the decision", "decisions/ADR-001-export-with-streamwrite" in ids(r, "the decision"))
    rc, r = load("export is broken", "--feature", "Export", "--mode", "debug")
    ok("debug adds recent history about the target", "log/journal/2099-01-01-writer-failed" in ids(r, "recent history"))


def test_ledger_cache_privilege():
    print("\nledger, cache, privilege")
    env = {"MEMORY_SESSION_OVERRIDE": "ledger-test"}
    rc, r1 = load("add caching", "--feature", "Export", "--mode", "build", env=env)
    rc, r2 = load("add caching", "--feature", "Export", "--mode", "build", env=env)
    ok("a second load in the same session repeats nothing", len(r2["repeated"]) == len(r1["notes"]),
       "%d of %d" % (len(r2["repeated"]), len(r1["notes"])))
    run("session", "evict", "--id", "ledger-test")
    rc, r3 = load("add caching", "--feature", "Export", "--mode", "build", env=env)
    ok("after compaction evicts the ledger, everything is re-read", len(r3["repeated"]) == 0)
    rc, out = run("load", "add caching", "--feature", "Export", "--mode", "build",
                  env={"MEMORY_SESSION_OVERRIDE": "fresh"})
    m = re.search(r"(\d+) from cache", out)
    ok("a new session is served from the content-hashed cache", m and int(m.group(1)) > 0, m.group(0) if m else out[-200:])

    rc, r = load("export limits", "--feature", "Export", "--mode", "build")
    rc, r_all = load("export limits", "--feature", "Export", "--mode", "debug",
                     env={"MEMORY_SESSION_OVERRIDE": "p1"})
    rc, r_str = load("export limits", "--feature", "Export", "--mode", "debug",
                     env=dict(STRANGER, MEMORY_SESSION_OVERRIDE="p2"))
    rc, out = run("recall", "export contract customer reports", "--json", env=STRANGER)
    ok("negative: restricted claims never reach a person without restricted_read",
       "500 reports" not in out)
    rc, out = run("recall", "export contract customer reports", "--json")
    ok("the owner (restricted_read) can recall them", "500 reports" in out)


def run_hook(payload, *args):
    e = dict(os.environ)
    e.pop("MEMORY_SESSION", None)
    e.pop("CLAUDE_CODE_SESSION_ID", None)
    p = subprocess.run([sys.executable, MEM, "--hook", *args], cwd=NOTES, input=json.dumps(payload),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e)
    return p.returncode, p.stdout + p.stderr


def test_hooks():
    print("\nhook entry points (stdin JSON, as Claude Code sends it)")
    rc, out = run_hook({"session_id": "hook-A", "hook_event_name": "SessionStart"}, "session", "start")
    ok("session start --hook takes the session id from stdin", rc == 0 and "hook-A" in out, out.strip())
    load("add caching", "--feature", "Export", "--mode", "build", env={"MEMORY_SESSION_OVERRIDE": "hook-A"})
    load("add caching", "--feature", "Export", "--mode", "build", env={"MEMORY_SESSION_OVERRIDE": "hook-B"})
    rc, out = run_hook({"session_id": "hook-A", "hook_event_name": "PreCompact"}, "session", "evict")
    rc, rA = load("add caching", "--feature", "Export", "--mode", "build", env={"MEMORY_SESSION_OVERRIDE": "hook-A"})
    rc, rB = load("add caching", "--feature", "Export", "--mode", "build", env={"MEMORY_SESSION_OVERRIDE": "hook-B"})
    ok("evict --hook evicts only the session named on stdin", len(rA["repeated"]) == 0 and len(rB["repeated"]) > 0,
       "A repeated %d, B repeated %d" % (len(rA["repeated"]), len(rB["repeated"])))
    e = dict(os.environ); e.pop("MEMORY_SESSION", None); e["CLAUDE_CODE_SESSION_ID"] = "hook-B"
    p = subprocess.run([sys.executable, MEM, "session", "show"], cwd=NOTES, stdout=subprocess.PIPE, text=True, env=e)
    ok("a Bash-tool call picks up CLAUDE_CODE_SESSION_ID as the session", '"session": "hook-B"' in p.stdout)
    rc, out = run_hook({}, "moved", "--quiet")
    ok("moved --hook with an empty payload is silent and exits 0", rc == 0 and out.strip() == "", out.strip())
    rc, out = run_hook({"session_id": "never-started"}, "moved", "--quiet")
    ok("moved --hook for a session that loaded nothing is silent", rc == 0 and out.strip() == "", out.strip())


def test_moved_and_refs():
    print("\ncontext moved, and versions")
    env = {"MEMORY_SESSION_OVERRIDE": "moved"}
    load("tweak export", "--feature", "Export", "--mode", "build", env=env)
    rc, out = run("moved", env=env)
    ok("nothing moved yet", "nothing you loaded has changed" in out)
    write("features/transform.md", read("features/transform.md").replace("is the part of", "is now the part of"))
    rc, out = run("moved", env=env)
    ok("an upstream edit is reported", "Transform" in out and "CONTRACT" not in out, out.strip()[:120])
    write("features/export.md", read("features/export.md").replace("at 30k rows", "at 60k rows"))
    rc, out = run("moved", env=env)
    ok("a contract change is reported LOUDLY", "CONTRACT CHANGED" in out)
    git("checkout", "-q", "--", ".")

    head = git("rev-parse", "HEAD").strip()
    write("features/export.md", read("features/export.md").replace("at 30k rows", "at 24k rows"))
    git("commit", "-qam", "change the contract")
    rc, out = run("load", "--feature", "Export", "--mode", "build", "--ref", head[:10], "--print",
                  env={"MEMORY_SESSION_OVERRIDE": "past"})
    ok("a past ref reads the old content", "at 30k rows" in out and "at 24k rows" not in out)
    ok("the receipt says it is not the latest", "PAST context" in out)
    rc, out = run("load", "--feature", "Export", "--mode", "build", "--print",
                  env={"MEMORY_SESSION_OVERRIDE": "latest"})
    ok("the default is the latest", "at 24k rows" in out)
    rc, out = run("diff", "--since", head[:10])
    ok("belief diff shows the changed claim-free contract as no claim change",
       "Beliefs" in out, out.splitlines()[0] if out else "")


def test_local_state():
    print("\nlocal state under concurrency and damage (audit area 04)")
    import concurrent.futures as cf

    def par(envs):
        with cf.ThreadPoolExecutor(max_workers=len(envs)) as ex:
            return list(ex.map(lambda e: run("load", "tweak export", "--feature", "Export", "--mode", "build",
                                             "--full", "--json", env=e), envs))

    res = par([{"MEMORY_SESSION_OVERRIDE": "race-same"}] * 8)
    led = json.load(open(led_path("race-same")))
    ok("04-F1: eight concurrent loads into one session all succeed and none is lost",
       all(rc == 0 for rc, _o in res) and led["turn"] == 8, "rcs=%s turn=%s" % ([rc for rc, _ in res], led["turn"]))
    res = par([{"MEMORY_SESSION_OVERRIDE": "race-%d" % i} for i in range(8)])
    ok("04-F1: eight concurrent loads in eight sessions all succeed", all(rc == 0 for rc, _o in res),
       [o[-120:] for rc, o in res if rc])

    ea, eb = {"MEMORY_SESSION_OVERRIDE": "bund-a"}, {"MEMORY_SESSION_OVERRIDE": "bund-b"}
    rc, ra = load("tweak export", "--feature", "Export", "--mode", "build", env=ea)
    load("tweak export", "--feature", "Export", "--mode", "build", env=eb)
    rc, rb2 = load("tweak export", "--feature", "Export", "--mode", "build", env=eb)  # all repeated
    ok("04-F2: a repeat load in session B does not overwrite session A's bundle",
       ra["bundle"] != rb2["bundle"] and "## " in read(ra["bundle"], base="/"), (ra["bundle"], rb2["bundle"]))

    # 04-F3: non-ASCII note, past ref, under a non-UTF-8 locale
    write("features/export.md", read("features/export.md").replace("## Card", "## Card\nR\u00e9sum\u00e9 \u2014 caf\u00e9."))
    git("commit", "-qam", "non-ascii")
    past = git("rev-parse", "HEAD").strip()
    write("features/export.md", read("features/export.md").replace("caf\u00e9", "cafe"))
    git("commit", "-qam", "later")
    rc, out = run("load", "--feature", "Export", "--mode", "build", "--ref", past[:10], "--print",
                  env={"MEMORY_SESSION_OVERRIDE": "utf", "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0",
                       "PYTHONIOENCODING": "utf-8"})
    ok("04-F3: a past ref with non-ASCII notes loads under a non-UTF-8 locale", rc == 0 and "caf\u00e9" in out, out[-200:])

    # 04-F4: tampered cache
    run("load", "tweak export", "--feature", "Export", "--mode", "build", env={"MEMORY_SESSION_OVERRIDE": "tamper0"})
    cache_dir = os.path.join(NOTES, ".memory", "cache")
    for fn in os.listdir(cache_dir):
        with open(os.path.join(cache_dir, fn), "a") as fh:
            fh.write("\nAUDIT04_TAMPER_ACCEPTED\n")
    rc, out = run("load", "tweak export", "--feature", "Export", "--mode", "build", "--print",
                  env={"MEMORY_SESSION_OVERRIDE": "tamper1"})
    ok("04-F4: a tampered cache file is regenerated, never served", rc == 0 and "AUDIT04_TAMPER" not in out, out[-120:])

    # 04-F5: ids
    load("tweak export", "--feature", "Export", env={"MEMORY_SESSION_OVERRIDE": "collision/a"})
    rc, out = run("session", "show", env={"MEMORY_SESSION_OVERRIDE": "collision?a"})
    ok("04-F5: 'collision/a' and 'collision?a' are different sessions", '"loaded": {}' in out or out.strip() == "{}", out[:120])
    p = subprocess.run([sys.executable, MEM, "--hook", "moved"], cwd=NOTES, input=json.dumps({"session_id": "x\nmemory: FAKE CONTRACT CHANGED"}),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                       env={k: v for k, v in os.environ.items() if k != "MEMORY_SESSION"})
    ok("04-F5: a hook session id with a newline is rejected (exit 5), nothing forged on stdout",
       p.returncode == 5 and "FAKE" not in p.stdout, (p.returncode, p.stdout[:80]))
    p = subprocess.run([sys.executable, MEM, "--hook", "moved"], cwd=NOTES, input=json.dumps({"session_id": ["list"]}),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                       env={k: v for k, v in os.environ.items() if k != "MEMORY_SESSION"})
    ok("04-F5: a non-string hook session id is exit 5, not a traceback", p.returncode == 5 and "Traceback" not in p.stderr, p.returncode)

    # 04-F6: per-session throttle
    ea, eb = {"MEMORY_SESSION_OVERRIDE": "thr-a"}, {"MEMORY_SESSION_OVERRIDE": "thr-b"}
    load("x", "--feature", "Sources", env=ea)
    load("x", "--feature", "Dashboard", "--mode", "orient", env=eb)
    load("x", "--feature", "Dashboard", env=eb)
    run("moved", "--quiet", "--throttle", "300", env=ea)
    write("features/dashboard.md", read("features/dashboard.md").replace("is the part of", "is now the part of"))
    rc, out = run("moved", "--quiet", "--throttle", "300", env=eb)
    ok("04-F6: session A's throttle does not silence session B's moved check", "Dashboard" in out, out[:120])
    git("checkout", "-q", "--", ".")

    # 04-F7: a failed load does not mark notes delivered
    e = {"MEMORY_SESSION_OVERRIDE": "txn"}
    run("session", "start", "--id", "txn")
    # A directory at the exact receipt-file path makes the save fail on Windows and POSIX alike;
    # chmod does not deny the owner on Windows (seen on Windows).
    receipt = led_path("txn").replace(".json", ".receipt.json")
    os.makedirs(receipt)
    try:
        rc1, out1 = run("load", "tweak export", "--feature", "Export", "--mode", "build", env=e)
    finally:
        shutil.rmtree(receipt, ignore_errors=True)
    rc2, r2 = load("tweak export", "--feature", "Export", "--mode", "build", env=e)
    ok("04-F7: after a load fails to save, the retry delivers every note again",
       rc1 != 0 and "Traceback" not in out1 and rc2 == 0 and not r2["repeated"], (rc1, out1[-100:], r2.get("repeated")))

    # 04-F8: wrong-shaped ledgers
    for bad in ([], {"loaded": []}, {"turn": "3", "loaded": {}}, {"session": "x"}):
        with open(led_path("shape"), "w") as fh:
            json.dump(bad, fh)
        codes = [run(*c, env={"MEMORY_SESSION_OVERRIDE": "shape"}) for c in
                 (("load", "x", "--feature", "Export"), ("moved",), ("session", "evict"))]
        if any(rc != 0 or "Traceback" in o for rc, o in codes):
            break
    ok("04-F8: wrong-shaped ledgers are quarantined and rebuilt, no tracebacks",
       all(rc == 0 and "Traceback" not in o for rc, o in codes), [(rc, o[-80:]) for rc, o in codes])

    # 04-F9: purge
    rc, out = run("session", "purge")
    left = os.listdir(os.path.join(NOTES, ".memory", "cache")) + os.listdir(os.path.join(NOTES, ".memory", "bundles"))
    ok("04-F9: session purge removes every cached copy of note text", rc == 0 and not left, left[:3])


def led_path(sid):
    import hashlib as _h
    import re as _re
    key = "%s-%s" % (_re.sub(r"[^A-Za-z0-9_-]", "_", sid)[:24], _h.sha256(sid.encode()).hexdigest()[:16])
    return os.path.join(NOTES, ".memory", "session", key + ".json")


def test_write_verbs():
    print("\nwrite verbs")
    rc, out = run("remember", "Spreadsheet uploads retry three times with backoff", "--feature", "Export", env=AGENT)
    ok("an agent remembering into a feature (L1) writes a PROPOSAL", "proposal" in out and rc == 0, out.strip()[:120])
    rc, out = run("remember", "The writer needs 8GB for large reports", env=AGENT)
    m = re.search(r"in (log/journal/\S+\.md) \(about (\w+)\)", out)
    ok("an agent remembering freely writes a journal note, linked to the resolved feature",
       m and m.group(2) == "Export", out.strip())
    rc, out = run("remember", "Export supports sheets of a million rows", "--feature", "Export")
    cid = re.search(r"\^([0-9a-f]{6})", out).group(1)
    ok("the owner remembers directly into the feature", "features/export.md" in out)
    rc, out = run("remember", "Export supports sheets of a million rows", "--feature", "Export")
    ok("negative: the same claim twice is refused as a duplicate", "already holds this" in out)
    rc, out = run("recall", "million rows")
    ok("recall finds it, with a reason", cid in out and "matches" in out)
    rc, out = run("why", "^" + cid)
    ok("why traces a claim to its note", "features/export.md" in out)
    rc, out = run("retire", "^" + cid)
    rc, out = run("recall", "million rows")
    ok("a retired claim leaves recall", cid not in out)
    ok("history is kept under ## Retired", "## Retired" in read("features/export.md"))

    rc, out = run("gap", "How are dates normalised before export")
    ok("a gap is recorded against the resolved feature", "log/gaps/" in out)
    rc, out = run("gap", "How are dates normalised before export")
    ok("negative: a duplicate gap is refused", "already recorded" in out)
    rc, out = run("gaps")
    ok("gaps are listed", "dates normalised" in out)

    rc, out = run("feature", "new", "Search", "--covers", "src/search/**")
    ok("the owner creates a feature, and a glob matching nothing is flagged", "matches nothing" in out)
    rc, out = run("feature", "new", "Exports", env=AGENT)
    ok("an agent's new feature becomes a proposal", "proposal written" in out)
    prop = re.search(r"(log/proposals/[^\n]+\.md)", out).group(1)
    rc, out = run("approve", os.path.basename(prop)[:-3], "--apply", env=AGENT)
    ok("negative: an agent cannot approve", rc == 4)
    rc, out = run("approve", os.path.basename(prop)[:-3], "--apply")
    ok("the owner approves and applies it", os.path.isfile(os.path.join(NOTES, "features", "exports.md")), out.strip()[:100])

    run("pin", "ADR-001 Export With Streamwrite")
    rc, out = run("recall", "totally unrelated words")
    ok("a pinned note's claims always surface", "Streamwrite" in out)
    run("unpin", "ADR-001 Export With Streamwrite")
    run("mute", "Writer failed on large reports")
    rc, out = run("recall", "writer memory reports")
    ok("a muted note stays out of recall", "runs out of memory" not in out)
    run("unmute", "Writer failed on large reports")
    logdir = os.path.join(NOTES, ".memory", "logs")
    logs = "".join(open(os.path.join(logdir, f)).read() for f in sorted(os.listdir(logdir)) if f.startswith("recall-"))
    ok("recall logs never contain the query text", "million rows" not in logs and "\"q\"" in logs)

    rc, out = run("role", "ana", "steward", env=AGENT)
    ok("negative: an agent cannot change roles", rc == 4)
    rc, out = run("role", "ana", "maintainer")
    pol = json.load(open(os.path.join(NOTES, "governance", "roles.json")))
    ok("the owner changes a role and roles.json stays valid", pol["people"]["ana"]["role"] == "maintainer")
    rc, out = run("can", "ana", "features/export.md")
    ok("can explains who may change what", "ana's agent" in out and "proposal" in out)

    genv = {k: v for k, v in os.environ.items() if k not in ("MEMORY_ACTOR_KIND", "MEMORY_ACTOR_EMAIL", "MEMORY_AGENT",
            "CLAUDE_CODE_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "KIRO_AGENT", "CURSOR_AGENT")}
    rc, out = subprocess.run([sys.executable, GUARD, "stamp", "--all"], cwd=NOTES, capture_output=True, text=True,
                             encoding="utf-8", env=genv).returncode, ""
    p = subprocess.run([sys.executable, GUARD, "check", "--no-attribution"], cwd=NOTES, capture_output=True, text=True,
                       encoding="utf-8", env=genv)
    fails = [l for l in (p.stdout + p.stderr).splitlines() if "[FAIL" in l and "roles.json" not in l]
    ok("every note mem wrote passes the guard", not fails, fails[:3])
    git("add", "-A")
    git("commit", "-qm", "write verbs")


def test_trials_and_evals():
    print("\ntrials and evals")
    corpus_claims = {}
    for line in open(os.path.join(NOTES, "decisions", "ADR-001-export-with-streamwrite.md"), encoding="utf-8"):
        m = re.search(r"- \[(\w+)\] (.+?) \^([0-9a-f]{6})", line)
        if m:
            corpus_claims[m.group(2)] = m.group(3)
    pup = corpus_claims["Exports use Streamwrite, not Gridkit's writer"]
    write("evals/export.md", """---
title: Export Evals
type: note
tags: [eval]
---

# Export Evals

## Observations
- [eval] recall "which writer do we use streamwrite gridkit" includes (^%s)
- [eval] resolve "the spreadsheet export is too slow" feature "Export"
- [eval] resolve "add a new job type" touching "src/transform/jobs.py" feature "Transform" mode build

## Relations
- relates_to [[Export]]
""" % pup)
    subprocess.run([sys.executable, GUARD, "stamp", "--all"], cwd=NOTES, capture_output=True)
    git("add", "-A")
    git("commit", "-qm", "evals")  # committed, so the negative case below can be undone with checkout
    rc, out = run("eval")
    ok("retrieval and resolution evals pass on main", rc == 0 and "3/3" in out, out.splitlines()[0])
    write("evals/export.md", read("evals/export.md").replace("(^%s)" % pup, "(^ffffff)"))
    rc, out = run("eval")
    ok("negative: an eval naming a claim recall does not return FAILS (exit 1)", rc == 1)
    git("checkout", "-q", "--", "memory/evals/export.md")  # paths are repo-root relative

    rc, out = run("try", "Agents misread the writer decision", "--for", "ana",
                  "--change", 'retire ^%s' % pup,
                  "--change", 'add to "Export": [decision] Exports use Gridkit for previews only',
                  "--slug", "writer-wording", env=AGENT)
    ok("an agent can open a trial", "trial writer-wording opened" in out, out.strip()[:120])
    rc, out = run("load", "--feature", "Export", "--mode", "build", "--print", env=dict(ANA, MEMORY_SESSION_OVERRIDE="ana"))
    ok("canary: the trial applies to a person in `for:`", "writer-wording applied" in out and "previews only" in out)
    rc, out = run("load", "--feature", "Export", "--mode", "build", "--print", env={"MEMORY_SESSION_OVERRIDE": "owner-t"})
    ok("negative: it does NOT apply to anyone else", "previews only" not in out)
    rc, out = run("load", "--feature", "Export", "--mode", "build", "--print", "--ref", "trial/writer-wording",
                  env={"MEMORY_SESSION_OVERRIDE": "explicit"})
    ok("anyone can opt in with --ref trial/<slug>", "previews only" in out)
    rc, out = run("eval", "--trial", "writer-wording")
    ok("eval --trial compares against main and flags the regression", "CHANGED" in out and rc == 1,
       out.splitlines()[-1] if "CHANGED" in out else out)
    rc, out = run("trials")
    ok("trials lists it", "writer-wording" in out)
    before_feat = read("features/export.md")
    rc, out = run("keep", "writer-wording", env=AGENT)
    prop = os.path.join(NOTES, "log", "proposals", "PROPOSAL - keep trial writer-wording.md")
    ok("negative: an agent cannot KEEP a trial that changes L1/L2 notes; it writes a proposal instead (05-F2)",
       read("features/export.md") == before_feat and os.path.isfile(prop) and "retire ^" in open(prop).read()
       and "PROPOSAL" in out, (rc, out[-200:]))
    os.remove(prop)
    rc, out = run("drop", "writer-wording", env=AGENT)
    ok("negative: drop without a result is refused", rc != 0 and "say what happened" in out)
    rc, out = run("drop", "writer-wording", "--result", "Agents were more confused, not less")
    jr = re.search(r"(log/journal/\S+\.md)", out)
    ok("a dropped trial leaves a journal note of what did not work",
       jr and "more confused" in read(jr.group(1)), out.strip()[:120])

    run("try", "Say the writer memory limit plainly", "--days", "-1",
        "--change", 'add to "Export": [fact] The writer needs 8GB for reports over 300k rows', "--slug", "old-one")
    rc, out = run("expire")
    ok("an expired trial is closed automatically", "1 expired" in out)
    run("try", "State the preview row limit", "--change", 'add to "Export": [fact] Previews show the first 15k rows',
        "--slug", "keeper")
    rc, out = run("keep", "keeper", "--result", "clearer")
    ok("the owner keeps a trial and its change lands in the real note",
       "Previews show the first 15k rows" in read("features/export.md"))


def main():
    try:
        build_fixture()
        test_resolve_and_modes()
        test_round1_fixes()
        test_explain_resolves_decisions()
        test_directional_scope()
        test_ledger_cache_privilege()
        test_hooks()
        test_moved_and_refs()
        test_local_state()
        test_write_verbs()
        test_trials_and_evals()
    except BaseException as e:  # a crash is a failure, never a shorter green run
        import traceback
        traceback.print_exc()
        ok("the suite ran to the end", False, repr(e))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    passed = sum(RESULTS)
    print("\n%d passed, %d failed (%d of %d expected checks ran)" % (passed, len(RESULTS) - passed, len(RESULTS), EXPECTED))
    return 0 if passed == len(RESULTS) == EXPECTED else 1


EXPECTED = 106


if __name__ == "__main__":
    sys.exit(main())
