#!/usr/bin/env bash
# Every offline check in this repo. No network, no key. The UI suite needs `npm install` in web/test.
set -u
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"; command -v "$PY" >/dev/null 2>&1 || PY=py
fail=0
for t in tools/test_parsers.py tools/test_guard.py tools/test_security.py tools/test_mem.py tools/test_atlas.py tools/test_gate.py tools/test_sync.py tools/test_init.py tools/test_scaffold.py tools/test_playbooks.py; do
  printf '\n=== %s\n' "$t"
  out="$("$PY" "$t" 2>&1)"; rc=$?
  printf '%s\n' "$out" | tail -1
  [ "$rc" -eq 0 ] || { fail=1; printf '%s\n' "$out" | grep -E "^  FAIL" | head -20; }
done
printf '\n=== config files parse\n'
"$PY" - <<'PY' || fail=1
import json, glob, sys
bad = []
for f in [".claude/settings.json", ".mcp.json", ".cursor/mcp.json", ".kiro/settings/mcp.json", "governance/roles.json",
          *glob.glob(".kiro/hooks/*.json"), *glob.glob("templates/project-memory/client-config/*.json.tmpl")]:
    try: json.load(open(f))
    except Exception as e: bad.append("%s: %s" % (f, e))
a = open(".agents/skills/team-memory/SKILL.md", "rb").read()
for c in (".claude/skills/team-memory/SKILL.md", ".kiro/skills/team-memory/SKILL.md"):
    if open(c, "rb").read() != a: bad.append(c + " differs from the canonical skill")
print("\n".join(bad) or "all parse; skill copies byte-identical"); sys.exit(1 if bad else 0)
PY
if [ -d web/test/node_modules ]; then
  printf '\n=== UI\n'; (cd web/test && node suite.mjs | tail -1 && node negative.mjs | tail -1) || fail=1
else
  printf '\n=== UI skipped (run: cd web/test && npm install)\n'
fi
exit $fail
