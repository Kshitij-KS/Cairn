#!/usr/bin/env python3
"""
test_claims.py - claim ids keep naming the same fact (recheck area 02, F1-F9).

The rule the fixes follow: a LOST id is visible (the guard warns, `mem why` says so) and can be put
back by hand; a TRANSFERRED id is silent, and every pin, eval and trial then points at the wrong
fact. So carrying an id forward must be close and unambiguous, or it does not happen.

    python3 tools/test_claims.py
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_guard import GUARD, guard, make_repo, read, sh, write  # noqa: E402

EXPECTED = 14
RESULTS = []
MEM = os.path.join(os.path.dirname(GUARD), "mem.py")


def ok(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + str(detail)[:300]) if detail and not cond else ""))


def load_guard():
    spec = importlib.util.spec_from_file_location("mg_claims", GUARD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def mk(lines):
    return "## Observations\n" + "\n".join(lines) + "\n"


PAIRS = [   # the recheck's own paraphrases, all edited at once
    ("Retries use exponential backoff capped at 30 seconds", "Retry delay doubles each attempt, up to a 30 second maximum"),
    ("Invoices are dated in UTC, not local time", "Invoice timestamps use UTC rather than the customer's timezone"),
    ("Uploads above 8 MB switch to multipart", "Files larger than 8 MB are sent as multipart uploads"),
    ("Idle sessions expire after 15 minutes", "A token with no activity for 15 minutes is revoked"),
    ("The cache is invalidated on every deploy", "Each deployment clears the cache"),
    ("The primary database lives in eu-west-1", "Our main Postgres instance is hosted in eu-west-1"),
    ("Incoming payloads are validated against the JSON schema", "Request bodies must pass JSON schema validation"),
    ("Exports run at most 4 jobs concurrently", "No more than four export jobs execute at the same time"),
    ("Logs are retained for 90 days", "We keep log data for ninety days"),
    ("Search falls back to substring match when the index is down", "If the search index is unavailable, a substring scan is used instead"),
    ("PDF rendering embeds the Inter font", "Generated PDFs include Inter as an embedded font"),
    ("Deleted accounts are purged after 30 days", "Account data is permanently removed 30 days after deletion"),
    ("The analytics filter excludes internal traffic", "The analytics filter now excludes internal and bot traffic"),
    ("Build artifacts are stored in S3", "Build artifacts are stored in the S3 bucket"),
    ("Feature flags are read at startup", "Feature flags are read once at process startup"),
    ("Emails are sent through SES", "Outgoing email goes through Amazon SES"),
    ("The API rate limit is 100 requests per minute", "The API rate limit is 120 requests per minute"),
    ("Thumbnails are generated asynchronously", "Thumbnail generation happens in a background worker"),
    ("Passwords are hashed with bcrypt", "User passwords are stored as bcrypt hashes"),
    ("The nightly report runs at 02:00 UTC", "The nightly report now runs at 03:00 UTC"),
]
BASELINE_KEPT = 9   # a ratchet: raise it when matching improves, never lower it


def unit(g):
    S = g.stamp_claim_ids
    ids = lambda b: [c[3] for c in g.parse_claims(b)]
    print("\nunit: matching")
    old, _s, _c = S("context/x", mk(["- [fact] " + a for a, _b in PAIRS]))
    new, _s, _c = S("context/x", mk(["- [fact] " + b for _a, b in PAIRS]), old)
    o, n = ids(old), ids(new)
    kept = sum(1 for x, y in zip(o, n) if x == y)
    swapped = sum(1 for i, y in enumerate(n) if y in o and o.index(y) != i)
    ok("02-F1: 20 paraphrases edited at once: no id moves to another fact, and at least %d are kept" % BASELINE_KEPT,
       swapped == 0 and kept >= BASELINE_KEPT, "kept %d, swapped %d" % (kept, swapped))
    o2, _s, _c = S("context/r", mk(["- [fact] EU requests time out after 30 seconds",
                                    "- [fact] US requests time out after 20 seconds"]))
    eu, us = ids(o2)
    n2, _s, _c = S("context/r", mk(["- [fact] US requests time out after 25 seconds",
                                    "- [fact] EU requests time out after 35 seconds"]), o2)
    ok("02-F2: two edited, reordered lines keep their OWN ids", ids(n2) == [us, eu], (eu, us, ids(n2)))
    o3, _s, _c = S("context/b", mk(["- [fact] The database backup runs nightly", "- [fact] Keep this line ^aaaaaa"]))
    gone = ids(o3)[0]
    n3, _s, _c = S("context/b", mk(["- [decision] The marketing site uses a blue footer", "- [fact] Keep this line ^aaaaaa"]), o3)
    ok("02-F3: a deleted claim's id is not handed to an unrelated new line", ids(n3)[0] != gone, ids(n3))
    t1 = unicodedata.normalize("NFC", "Café menus list the résumé")
    t2 = unicodedata.normalize("NFD", t1)
    ok("02-F7: NFC and NFD spellings, and case, give the same id",
       g.new_claim_id("n", t1, set()) == g.new_claim_id("n", t2, set())
       and g.new_claim_id("n", "Straße", set()) == g.new_claim_id("n", "STRASSE", set()))
    out = []
    for tok in ("^zzzzzz", "^ABCDEF", "^12345g", "^abcde", "^abcdef1"):
        b, _s, _c = S("context/m", mk(["- [fact] malformed marker " + tok]))
        line = [l for l in b.split("\n") if l.startswith("- ")][0]
        out.append(line)
    ok("02-F9: an id-shaped tail is normalised (^ABCDEF -> ^abcdef) or replaced, never left beside a new id",
       out[1].endswith(" ^abcdef") and all(len(re.findall(r"\^", l)) == 1 for l in out)
       and all(re.search(r" \^[0-9a-f]{6}$", l) for l in out), out)
    taken = {g.new_claim_id("context/a", "- [fact] same words", set())}
    ok("02-F6: a new id is never one already used anywhere in the tier",
       g.new_claim_id("context/a", "- [fact] same words", taken) not in taken)
    ret = mk(["- [fact] Keep ^111111"]) + "\n## Retired\n- [fact] Old thing ^994f02 (retired 2026-09-01: by alex)\n"
    b, _s, _c = S("context/t", ret, ret)
    b2, _s, _c = S("context/t", b, b)
    ok("02-F5: a retired line is never stamped again, so its id appears once",
       b2.count("994f02") == 1 and b2 == ret, b2)


def cli(tmp):
    print("\ncli: moves, collisions, retirements")
    root, notes = make_repo(tmp)
    a = os.path.join(notes, "context", "a.md")
    b = os.path.join(notes, "context", "b.md")
    note = lambda t, lines: "---\ntitle: %s\ntype: context\ntags: [t]\n---\n\n# %s\n\nx.\n\n%s\n## Relations\n- relates_to [[Core]]\n" % (t, t, mk(lines))
    write(a, note("A", ["- [fact] The export queue has four workers", "- [fact] Reports go out at seven"]))
    write(b, note("B", ["- [fact] Something else entirely"]))
    guard(notes, "stamp", "--all")
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", "base")
    moved_id = re.search(r"four workers \^([0-9a-f]{6})", read(a)).group(1)
    write(a, note("A", ["- [fact] Reports go out at seven ^" + re.search(r"seven \^([0-9a-f]{6})", read(a)).group(1)]))
    write(b, note("B", ["- [fact] Something else entirely ^" + re.search(r"entirely \^([0-9a-f]{6})", read(b)).group(1),
                        "- [fact] The export queue has four workers"]))
    guard(notes, "stamp", "--all")
    ok("02-F4: a claim moved to another note in the same change keeps its id", ("four workers ^" + moved_id) in read(b),
       read(b))
    rc, out = sh(notes, sys.executable, MEM, "why", "^" + moved_id)
    ok("02-F4: `mem why` finds it in its new note", rc == 0 and "context/b.md" in out, out[-200:])
    sh(root, "git", "add", "-A")
    rc, out = guard(notes, "check", "--staged")
    ok("...and the guard does not call it gone", "gone from this note" not in out, out[-300:])
    sh(root, "git", "commit", "-qm", "move")

    # a collision: committed claim in a.md, a NEW line in b.md ending with the same id
    seven = re.search(r"seven \^([0-9a-f]{6})", read(a)).group(1)
    write(b, read(b).replace("## Relations", "- [fact] A different fact entirely ^%s\n\n## Relations" % seven))
    sh(root, "git", "add", "-A")
    rc, out = guard(notes, "check", "--staged")
    ok("02-F6: the collision fails check, and the hint names the repair that works",
       rc == 5 and "stamp --all" in out, out[-300:])
    guard(notes, "stamp", "--all")
    ok("02-F6: the repair keeps the committed claim's id and gives the NEWCOMER a new one",
       ("seven ^" + seven) in read(a) and ("entirely ^" + seven) not in read(b)
       and re.search(r"A different fact entirely \^[0-9a-f]{6}$", read(b), re.M), read(b)[-300:])

    # an id that disappears is reported
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", "repaired")
    write(a, read(a).replace("Reports go out at seven ^" + seven, "Reports are delivered each morning"))
    guard(notes, "stamp", "--all")
    sh(root, "git", "add", "-A")
    rc, out = guard(notes, "check", "--staged")
    ok("02-F1: a reworded line that lost its id is WARNED about, naming the id", "^" + seven in out and "gone" in out, out[-300:])
    rc, out = sh(notes, sys.executable, MEM, "why", "^")
    rc2, out2 = sh(notes, sys.executable, MEM, "why", "^ffffff")
    ok("`mem why ^` is a usage error (5); an id that never existed is exit 1", rc == 5 and rc2 == 1, (rc, rc2))


def main():
    g = load_guard()
    unit(g)
    tmp = tempfile.mkdtemp()
    try:
        cli(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(RESULTS)
    print("\n%d passed, %d failed (%d of %d expected checks ran)" % (passed, len(RESULTS) - passed, len(RESULTS), EXPECTED))
    return 0 if passed == len(RESULTS) == EXPECTED else 1


if __name__ == "__main__":
    sys.exit(main())
