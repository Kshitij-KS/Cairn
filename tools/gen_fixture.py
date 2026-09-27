#!/usr/bin/env python3
"""Grow a synthetic cairn to N notes with a realistic shape, so the scaling
limits can be measured instead of guessed.

Distribution is an assumed growth mix: the journal dominates
(every significant change writes one), projects and context grow slowly, decisions
slowest of all.
"""
import os, random, shutil, sys, datetime

N = int(sys.argv[1]); DEST = sys.argv[2]
# The base corpus is this repository's own notes (a git checkout), so the synthetic fixtures carry
# nothing that is not already public here. Pass another base as the third argument if you like.
BASE = sys.argv[3] if len(sys.argv) > 3 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
random.seed(20260922 + N)                      # deterministic: same N, same corpus

if os.path.exists(DEST): shutil.rmtree(DEST)
shutil.copytree(BASE, DEST, symlinks=True,
                ignore=shutil.ignore_patterns(".git", "node_modules", ".memory", "__pycache__", "web", "tools"))

VERBS = ["stale index after a path change", "rebuild drops the cache", "retry storm on timeout",
         "duplicate rows after a resync", "slow query on the changes feed", "flaky gate on Windows",
         "rate limit hit on the export API", "webhook retries arrive out of order",
         "cascade stamps too widely", "export drops the header row"]
AREAS = ["billing", "search", "checkout", "catalog", "auth", "notifications", "reports",
         "onboarding", "api", "gate", "atlas", "sync"]
PEOPLE = ["alex", "sam", "jordan", "priya", "lee"]

mix = {"log/journal": .70, "context": .10, "projects": .10, "decisions": .06, "log/proposals": .04}
counts = {k: max(1, int(N * v)) for k, v in mix.items()}
titles = []

def rel_block(pool, k):
    if not pool or k == 0: return ""
    picks = random.sample(pool, min(k, len(pool)))
    kinds = ["depends_on", "implements", "part_of", "relates_to", "relates_to"]
    return "\n## Relations\n" + "".join(
        "- %s [[%s]]\n" % (random.choice(kinds), p) for p in picks)

def obs_block(k):
    return "\n## Observations\n" + "".join(
        "- [%s] %s in %s, seen %d time(s) this week\n"
        % (random.choice(["fact", "risk", "decision", "measure", "gotcha"]),
           random.choice(VERBS), random.choice(AREAS), random.randint(1, 9))
        for _ in range(k))

day0 = datetime.date(2026, 1, 5)
i = 0
for folder, n in counts.items():
    os.makedirs(os.path.join(DEST, folder), exist_ok=True)
    for j in range(n):
        i += 1
        d = day0 + datetime.timedelta(days=random.randint(0, 260))
        area = random.choice(AREAS)
        title = "%s %s %03d" % (area, random.choice(VERBS), j)
        level = {"log/journal": "L0", "context": "L2", "projects": "L1",
                 "decisions": "L2", "log/proposals": "L0"}[folder]
        name = ("%s-%s.md" % (d.isoformat(), title.replace(" ", "-")) if folder == "log/journal"
                else "%s.md" % title.replace(" ", "-"))
        body = (
            "---\ntitle: %s\ntype: note\ntags: [%s, synthetic]\nlevel: %s\n"
            "confidentiality: internal\npermalink: %s\ncreated: %s\nupdated: %s\n"
            "changed_by: %s\nchanged_at: %sT10:00:00Z\n---\n\n"
            % (title, area, level, title.replace(" ", "-").lower(), d.isoformat(),
               d.isoformat(), random.choice(PEOPLE), d.isoformat()))
        body += "%s.\n" % random.choice(VERBS).capitalize()
        body += obs_block(random.randint(3, 11))
        body += rel_block(titles, random.randint(0, 4))
        open(os.path.join(DEST, folder, name), "w", encoding="utf-8").write(body)
        titles.append(title)

print("generated %d notes into %s" % (i, DEST))
