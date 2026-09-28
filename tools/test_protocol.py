#!/usr/bin/env python3
"""
test_protocol.py - the context protocol, trials and agent wiring (recheck areas 03, 05, 09).

Each case is a reproduction from the recheck, turned into an assertion, on a throwaway project tier
(memory/ inside a code repository) under the fictional test policy.

    python3 tools/test_protocol.py
"""
import datetime
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testpolicy  # noqa: E402

REPO = os.path.dirname(HERE)
EXPECTED = 30
RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + str(detail)[:300]) if detail and not cond else ""))


def write(base, rel, text):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def feat(title, covers, deps=(), aliases=(), contract="", body="", rels=()):
    r = ["- depends_on [[%s]]" % d for d in deps] + list(rels) + ["- part_of [[Core]]"]
    return ("---\ntitle: %s\ntype: feature\nstatus: live\ncovers: [%s]\naliases: [%s]\ntags: [feature]\n---\n\n# %s\n\n"
            "## Card\n%s is the part of the product that does %s things.\n\n## Contract\n%s\n\n%s\n"
            "## Observations\n- [fact] %s is owned by alex\n\n## Relations\n%s\n") % (
        title, ", ".join('"%s"' % c for c in covers), ", ".join(aliases), title, title, title.lower(),
        contract or "%s promises a stable interface." % title, body, title, "\n".join(r))


def dec(title, rels):
    return ("---\ntitle: %s\ntype: decision\nstatus: accepted\ntags: [adr]\n---\n\n# %s\n\nWe decided %s.\n\n"
            "## Observations\n- [decision] %s holds\n\n## Relations\n%s\n") % (title, title, title.lower(), title, "\n".join(rels))


def journal(title, updated, rel):
    u = "updated: %s\n" % updated if updated else ""
    return ("---\ntitle: %s\ntype: note\ntags: [journal]\n%s---\n\n# %s\n\nSomething about %s.\n\n"
            "## Observations\n- [gotcha] %s mentions target\n\n## Relations\n- relates_to [[%s]]\n") % (title, u, title, rel, title, rel)


def env(extra=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("MEMORY_", "CLAUDE", "KIRO_", "CURSOR_"))}
    e.update({"MEMORY_ACTOR_KIND": "human", "PYTHONIOENCODING": "utf-8"})
    e.update(extra or {})
    return e


class Tier:
    def __init__(self, tmp, name, n_extra=0):
        self.root = os.path.join(tmp, name)
        self.notes = os.path.join(self.root, "memory")
        n = self.notes
        os.makedirs(os.path.join(n, "scripts"))
        for s in ("mem.py", "memory_guard.py", "sync-memory.py", "sync-memory.sh", "sync-memory.ps1"):
            shutil.copy(os.path.join(REPO, "scripts", s), os.path.join(n, "scripts", s))
        d = testpolicy.policy()
        d["people"]["ana"] = {"name": "Ana", "email": "ana@example.test", "github": "ana-gh", "role": "contributor",
                              "projects": [], "function": "eng"}
        write(n, "governance/roles.json", json.dumps(d, indent=2))
        write(n, ".basic-memory/project.json", '{"name": "proj", "kind": "project"}\n')
        write(self.root, ".gitignore", ".memory/\n__pycache__/\n")
        for f in ("src/alpha/a.py", "src/beta/b.py", "src/target/t.py", "src/middle/m.py", "src/found/f.py",
                  "src/down1/d.py", "src/explainer/e.py", "src/export/export_layouts.mjs", "src/lib/compose_helper.py"):
            write(self.root, f, "# code\n")
        write(n, "CORE.md", "---\ntitle: Core\ntype: context\ntags: [core]\n---\n\n# Core\n\nWe make things.\n\n"
                            "## Observations\n- [constraint] Things ship daily\n\n## Relations\n- relates_to [[Alpha]]\n")
        write(n, "features/alpha.md", feat("Alpha", ["src/alpha/**"], aliases=("shared",)))
        write(n, "features/beta.md", feat("Beta", ["src/beta/**"], aliases=("shared",)))
        write(n, "features/foundation.md", feat("Foundation", ["src/found/**"]))
        write(n, "features/middle.md", feat("Middle", ["src/middle/**"], deps=("Foundation",)))
        write(n, "features/target.md", feat("Target", ["src/target/**"], deps=("Middle",),
                                            contract="CONTRACT_ONLY_target promises X.",
                                            body="## Details\nREVIEW_BODY_LEAK_MARKER internal detail.\n"))
        write(n, "features/down-one.md", feat("Down One", ["src/down1/**"], deps=("Target",)))
        write(n, "features/explainer.md", feat("Explainer", ["src/explainer/**"], rels=("- implements [[Decision Four]]",)))
        # the file's owner is NOT named like the path; a feature that IS (Render) owns other code
        write(n, "features/layout-engine.md", feat("Layout Engine", ["src/export/**"]))
        write(n, "features/exporter.md", feat("Export", ["src/lib/**"]))
        write(n, "decisions/decision-one.md", dec("Decision One", ["- relates_to [[Core]]"]))
        write(n, "decisions/decision-two.md", dec("Decision Two", ["- supersedes [[Decision One]]"]))
        write(n, "decisions/decision-three.md", dec("Decision Three", ["- supersedes [[Decision Two]]"]))
        write(n, "decisions/decision-four.md", dec("Decision Four", ["- supersedes [[Decision Three]]"]))
        today = datetime.date.today().isoformat()
        write(n, "log/journal/recent.md", journal("Recent Target Note", today, "Target"))
        write(n, "context/restricted/pricing.md", "---\ntitle: Pricing Terms\ntype: context\nconfidentiality: restricted\n"
                                                   "tags: [deal]\n---\n\n# Pricing Terms\n\nSecret.\n\n## Observations\n"
                                                   "- [fact] a secret price\n\n## Relations\n- relates_to [[Core]]\n")
        write(n, "context/shared-a.md", "---\ntitle: Shared Target\ntype: context\ntags: [x]\n---\n\n# Shared Target\n\nA.\n\n"
                                         "## Observations\n- [fact] one\n\n## Relations\n- relates_to [[Core]]\n")
        write(n, "context/shared-b.md", "---\ntitle: Shared Target\ntype: context\ntags: [x]\n---\n\n# Shared Target\n\nB.\n\n"
                                         "## Observations\n- [fact] two\n\n## Relations\n- relates_to [[Core]]\n")
        for i in range(n_extra):
            write(self.root, "src/x%03d/x.py" % i, "# c\n")
            write(n, "features/audit-%03d.md" % i, feat("Audit %03d" % i, ["src/x%03d/**" % i]))
        for c in (["init", "-q", "-b", "main"], ["config", "user.name", "Alex Tester"], ["config", "user.email", testpolicy.EMAIL]):
            subprocess.run(["git", *c], cwd=self.root, check=True)
        self.guard("stamp", "--all")
        # written after stamping, as a note that never went through the sync would be
        write(n, "log/journal/undated.md", journal("Undated Target Note", None, "Target"))
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "fx"], cwd=self.root, check=True)

    def run(self, script, *args, extra=None, stdin=None, sess="s"):
        e = env(dict({"MEMORY_SESSION": sess}, **(extra or {})))
        p = subprocess.run([sys.executable, os.path.join(self.notes, "scripts", script), *args], cwd=self.notes,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                           errors="replace", env=e, input=stdin)
        return p.returncode, p.stdout + p.stderr

    def mem(self, *args, **kw):
        return self.run("mem.py", *args, **kw)

    def guard(self, *args, **kw):
        return self.run("memory_guard.py", *args, **kw)

    def load(self, *args, sess):
        rc, out = self.mem("load", "--json", *args, sess=sess)
        try:
            return rc, json.loads(out[out.index("{"):])
        except ValueError:
            return rc, {"_raw": out}


def notes_of(d):
    return {n["id"]: (n.get("role"), n.get("depth")) for n in d.get("notes", [])}


def test_protocol(t):
    print("\ncontext protocol (area 03)")
    rc, d = t.load("what should we prioritise for shared", sess="f1")
    ok("03-F1: a plan ask that ties two features asks which one (exit 2), loading neither", rc == 2 and "ask_the_person" in d, (rc, d)[:1])
    rc, d = t.load("review the Target changes", sess="f2")
    b = open(d["bundle"], encoding="utf-8").read() if d.get("bundle") else ""
    ok("03-F2: review loads the target's card and full contract, not its implementation body",
       rc == 0 and notes_of(d).get("features/target", (None, None))[1] == "contract" and "CONTRACT_ONLY_target" in b
       and "REVIEW_BODY_LEAK_MARKER" not in b, notes_of(d))
    rc, d = t.load("catch me up on Alpha and Beta", sess="f3")
    ok("03-F3: an orient tie shows both cards", rc == 0 and notes_of(d).get("features/alpha", (0,))[0] == "about"
       and notes_of(d).get("features/beta", (0,))[0] == "about", notes_of(d))
    rc, d = t.load("explain why Explainer works this way", sess="f4")
    got = [k for k in notes_of(d) if k.startswith("decisions/")]
    ok("03-F4: explain follows the whole supersede chain", sorted(got) == ["decisions/decision-four", "decisions/decision-one",
                                                                           "decisions/decision-three", "decisions/decision-two"], got)
    rc, d = t.load('fix the shared $HOME `id` "x" thing', sess="f5")
    rerun = d.get("rerun", "")
    ok("03-F5: the rerun line carries no $, backtick, or inner double quote", rc == 2 and rerun and not any(c in rerun[10:-12] for c in '$`\\"!%')
       and "$HOME" not in rerun, rerun)
    rc, d = t.load("fix D:\\work\\repo\\src\\export\\export_layouts.mjs", sess="f6")
    tg = d.get("targets") or []
    ok("03-F6: a Windows path in the ask resolves to the one feature that covers the file", rc == 0 and tg == ["features/layout-engine"], (rc, tg))
    rc2, out2 = t.mem("resolve", "--json", "compose_helper is failing on spaces")
    ok("a bare identifier (compose_helper) still resolves to the feature owning that file", '"title": "Export"' in out2
       and '"confident": true' in out2, out2[-300:])
    rc, d = t.load("Target is broken", sess="f7")
    ok("03-F7: an undated journal note is not 'recent history'", rc == 0 and "log/journal/recent" in notes_of(d)
       and "log/journal/undated" not in notes_of(d), notes_of(d))
    rc, out = t.mem("resolve", "--json", "debug the Target encode step")
    ok("'debug', 'investigate', 'troubleshoot' and 'diagnose' are debug words",
       '"mode": "debug"' in out and all('"mode": "debug"' in t.mem("resolve", "--json", w + " the Target step")[1]
                                        for w in ("investigate", "troubleshoot", "diagnose")), out[-200:])
    write(t.notes, "evals/e.md", "---\ntitle: E Evals\ntype: note\ntags: [eval]\n---\n\n# E Evals\n\n## Observations\n"
                                 "- [eval] resolve \"implement the Target thing\" feature \"Target\"\n"
                                 "- [eval] resolve \"implement the Target thing\" feature \"Target\"\n\n## Relations\n- relates_to [[Core]]\n")
    t.guard("stamp", "--all")
    rc, out = t.mem("eval")
    ok("05-F8: the same eval twice counts once", rc == 0 and "1/1" in out, out[-200:])
    rc1, _o = t.mem("mute", "Target")
    rc, out2 = t.mem("eval")
    t.mem("unmute", "Target")
    ok("an eval's result does not depend on the runner's pins and mutes", rc1 == 0 and rc == 0, out2[-200:])
    rc, out = t.mem("eval", "--file", "evals/nope.md")
    ok("`mem eval --file` of a missing file is an error, not 'no evals found' and exit 0", rc == 5, (rc, out[-120:]))
    rc, out = t.mem("pin", "")
    rc2, out2 = t.mem("pin", "No Such Note At All")
    ok("`mem pin` refuses an empty or unknown target", rc == 5 and rc2 == 5, (rc, rc2))
    write(t.notes, "evals/g.md", "---\ntitle: G Evals\ntype: note\ntags: [eval]\n---\n\n# G Evals\n\n## Observations\n"
                                 "- [eval] resolve \"implement the Alpha thing\" feature \"Alpha\" TRAILING GARBAGE\n\n## Relations\n- relates_to [[Core]]\n")
    t.guard("stamp", "--all")
    rc, out = t.mem("eval", "--file", "evals/g.md")
    ok("05-F3: an eval with trailing garbage is unreadable, not a pass", rc == 1 and "unreadable" in out, out[-200:])
    os.remove(os.path.join(t.notes, "evals", "g.md"))


def test_scale(tmp):
    t = Tier(tmp, "big", n_extra=200)
    rc, d = t.load("implement the Target thing", sess="big")
    b = open(d["bundle"], encoding="utf-8").read() if d.get("bundle") else ""
    lines = [l for l in b.splitlines() if l.startswith("- **")]
    ok("03-F9: with 208 features the map is capped (<= 40 lines) and the load stays under 3,000 tokens",
       rc == 0 and len(lines) <= 40 and d.get("tokens_estimate", 1e9) < 3000 and "more features" in b,
       (len(lines), d.get("tokens_estimate")))


def test_trials(t):
    print("\ntrials (area 05)")
    ag = {"MEMORY_ACTOR_KIND": "agent"}
    rc, out = t.mem("try", "shared target wording", "--change", 'add to "Shared Target": [fact] x', "--slug", "amb")
    ok("05-F4: `add to` a title two notes share is refused, naming both paths", rc == 5 and "shared-a.md" in out and "shared-b.md" in out, out[-200:])
    rc1, o1 = t.mem("try", "pricing", "--change", 'add to "Pricing Terms": [fact] x', "--slug", "p1", extra=dict(ag, MEMORY_ACTOR_EMAIL="ana@example.test"))
    rc2, o2 = t.mem("try", "missing", "--change", 'add to "No Such Note": [fact] x', "--slug", "p2", extra=dict(ag, MEMORY_ACTOR_EMAIL="ana@example.test"))
    ok("05-F5: a restricted note answers exactly like a missing one (no existence oracle)",
       rc1 == rc2 == 5 and o1.replace("Pricing Terms", "X") == o2.replace("No Such Note", "X"), (o1[-120:], o2[-120:]))
    bad = [t.mem("try", "h", "--change", 'add to "Alpha": [fact] y', "--slug", "s%d" % i, "--for", who)[0]
           for i, who in enumerate(("Ana", "ghost", ""))]
    ok("05-F6: --for takes registered handles exactly ('Ana', 'ghost' and '' are refused)", bad == [5, 5, 5], bad)
    rc, out = t.mem("try", "canary one", "--change", 'add to "Alpha": [fact] canary one', "--slug", "c1", "--for", "ana")
    rc2, out2 = t.mem("try", "canary two", "--change", 'add to "Beta": [fact] canary two', "--slug", "c2", "--for", "ana")
    ok("05-F6: a person is in one canary at a time", rc == 0 and rc2 == 5 and "c1" in out2, (rc, rc2, out2[-150:]))
    write(t.notes, "evals/t.md", "---\ntitle: T Evals\ntype: note\ntags: [eval]\n---\n\n# T Evals\n\n## Observations\n"
                                 "- [eval] resolve \"implement the Middle thing\" feature \"Middle\"\n\n## Relations\n- relates_to [[Core]]\n")
    t.guard("stamp", "--all")
    subprocess.run(["git", "add", "-A"], cwd=t.root)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "evals"], cwd=t.root)
    eval_id = [l for l in open(os.path.join(t.notes, "evals", "t.md")).read().splitlines() if l.startswith("- [eval]")][0].split("^")[-1]
    rc, out = t.mem("try", "add a failing eval", "--change", 'add to "T Evals": [eval] resolve "nothing here matches" feature "Alpha"', "--slug", "fe")
    rc2, out2 = t.mem("eval", "--trial", "fe")
    ok("05-F1: a trial that ADDS a failing eval does not pass `eval --trial`", rc == 0 and rc2 == 1 and "failing new" in out2, (rc, rc2, out2[-200:]))
    rc, out = t.mem("try", "retire an eval", "--change", "retire ^" + eval_id, "--slug", "re")
    rc2, out2 = t.mem("eval", "--trial", "re")
    ok("05-F1: a trial that RETIRES a passing eval fails (no IndexError)", rc == 0 and rc2 == 1 and "REMOVED" in out2
       and "Traceback" not in out2, (rc, rc2, out2[-200:]))
    tr = os.path.join(t.notes, "trials", "re.md")
    txt = open(tr).read()
    import re as _re
    open(tr, "w").write(_re.sub(r"(?m)^expires: .*$", "expires: 2000-01-01", txt))
    rc, out = t.mem("load", "implement the Alpha thing", "--ref", "trial/re")
    ok("05-F7: an expired trial no longer applies through --ref", rc == 5 and "expired" in out, (rc, out[-150:]))
    rc, out = t.mem("keep", "c1", extra=ag)
    ok("05-F2: an agent's keep writes a proposal and changes nothing",
       rc == 0 and os.path.isfile(os.path.join(t.notes, "log", "proposals", "PROPOSAL - keep trial c1.md"))
       and "canary one" not in open(os.path.join(t.notes, "features", "alpha.md")).read(), out[-200:])


def test_agents(t):
    print("\nagent integration (area 09)")
    rc, d = t.load("--add", "Middle", "--full", sess="a2")
    ok("09-F2: `load --add X --full` with no ask loads X in full", rc == 0 and notes_of(d).get("features/middle", (0, 0))[1] == "full", notes_of(d))
    rc, out = t.mem("remember", "We will ship weekly from now on", "--category", "decision", extra={"MEMORY_ACTOR_KIND": "agent"})
    props = os.listdir(os.path.join(t.notes, "log", "proposals"))
    ok("09-F4: `remember --category decision` becomes a proposal, not a journal observation",
       rc == 0 and any("ship weekly" in open(os.path.join(t.notes, "log", "proposals", f)).read() for f in props)
       and not any("ship weekly" in open(os.path.join(t.notes, "log", "journal", f)).read()
                   for f in os.listdir(os.path.join(t.notes, "log", "journal"))), out[-200:])
    rc, d = t.load("fix the Target thing --mode debug --feature Target", sess="a5")
    ok("09-F5: flags written inside the ask are taken as flags", rc == 0 and d.get("mode") == "debug"
       and d.get("targets") == ["features/target"], (rc, d.get("mode"), d.get("targets")))
    rc, out = t.mem("status", extra={"MEMORY_ACTOR_KIND": "agent"})
    ok("09-F7: status says who is acting and how high they may write", "acting as agent" in out and "L0" in out, out[:200])
    kiro = [json.load(open(os.path.join(REPO, ".kiro", "hooks", f))) for f in ("memory-session-start.json", "memory-post-task.json")]
    ok("09-F9: each Kiro event is ONE hook, so its steps run in a fixed order",
       all(len(k["hooks"]) == 1 for k in kiro) and "--then-session" in kiro[0]["hooks"][0]["action"]["command"]
       and "--significance" in kiro[1]["hooks"][0]["action"]["command"], [len(k["hooks"]) for k in kiro])
    cur = os.path.join(t.notes, ".memory", "session", "current")
    if os.path.exists(cur):
        os.remove(cur)
    rc, out = t.run("sync-memory.py", "pre", "--then-session")
    ok("09-F9: `sync-memory.py pre --then-session` pulls, then opens the session ledger", os.path.isfile(cur), (rc, out[-200:]))
    settings = json.load(open(os.path.join(REPO, ".claude", "settings.json")))
    allow = " ".join(settings["permissions"]["allow"])
    ok("09-F8: the allow-list names verbs, never `mem.py:*`, and denies `mem role`",
       "mem.py:*" not in allow and "mem.py load:*" in allow
       and any("mem.py role" in x for x in settings["permissions"]["deny"]), allow[:200])


def main():
    tmp = tempfile.mkdtemp(prefix="cairn-protocol-")
    try:
        t = Tier(tmp, "proj")
        test_protocol(t)
        test_scale(tmp)
        test_trials(t)
        test_agents(t)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(RESULTS)
    print("\n%d passed, %d failed (%d of %d expected checks ran)" % (passed, len(RESULTS) - passed, len(RESULTS), EXPECTED))
    return 0 if passed == len(RESULTS) == EXPECTED else 1


if __name__ == "__main__":
    sys.exit(main())
