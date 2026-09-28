#!/usr/bin/env bash
# Every offline check in this repo. No network, no key.
#
# A skipped suite is a FAILED run: the UI suite needs `npm ci` in web, and a run that quietly
# skipped it once reported green (recheck 11-F2). CAIRN_SKIP_UI=1 skips it on purpose and says so.
set -u
cd "$(dirname "$0")/.."
PY=""
# `command -v python3` finds the Windows Store alias, which runs nothing: every suite then printed
# "Python was not found" and the loop still reached the end (recheck 11-F2). Try each, for real.
for c in ${PYTHON:-} python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || { echo "run_tests: no working Python 3.9+ (tried ${PYTHON:-} python3 python py)" >&2; exit 1; }
fail=0
for t in tools/test_parsers.py tools/test_guard.py tools/test_security.py tools/test_claims.py tools/test_mem.py \
         tools/test_protocol.py tools/test_localstate.py tools/test_atlas.py tools/test_gate.py tools/test_sync.py \
         tools/test_init.py tools/test_scaffold.py tools/test_playbooks.py; do
  printf '\n=== %s\n' "$t"
  out="$("$PY" "$t" 2>&1)"; rc=$?
  printf '%s\n' "$out" | tail -1
  [ "$rc" -eq 0 ] || { fail=1; printf '%s\n' "$out" | grep -E "^  FAIL|Traceback|Error" | head -20; }
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
# Every Python file compiles with warnings as errors. Python 3.12 prints a SyntaxWarning for an
# invalid escape like "\\`" in a docstring; mem.py carried one, the warning landed in the JSON the
# suites parse, and 12 checks failed on CI's Python while 3.10 stayed silent and green.
import subprocess, warnings
for f in subprocess.run(["git", "ls-files", "*.py"], stdout=subprocess.PIPE, text=True).stdout.split():
    with open(f, encoding="utf-8") as fh:
        src = fh.read()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            compile(src, f, "exec")
        except (SyntaxError, SyntaxWarning, DeprecationWarning) as e:
            bad.append("%s does not compile cleanly: %s" % (f, e))
print("\n".join(bad) or "all parse; skill copies byte-identical; every .py compiles with warnings as errors"); sys.exit(1 if bad else 0)
PY
if [ -d web/node_modules ]; then
  # The committed page must be what its source builds to, then the page is driven at every size.
  printf '\n=== UI build is current\n'; (cd web && node app/check-build.mjs) || fail=1
  for t in suite sky negative; do
    printf '\n=== UI %s\n' "$t"; (cd web && node "test/$t.mjs" | tail -1; exit "${PIPESTATUS[0]}") || fail=1
  done
  printf '\n=== UI in a real browser\n'; (cd web && node test/browser.mjs | tail -1; exit "${PIPESTATUS[0]}") || fail=1
elif [ "${CAIRN_SKIP_UI:-0}" = "1" ]; then
  printf '\n=== UI skipped on purpose (CAIRN_SKIP_UI=1)\n'
else
  printf '\n=== UI NOT RUN: cd web && npm ci   (or CAIRN_SKIP_UI=1 to skip on purpose) - counted as a failure\n'
  fail=1
fi
[ "$fail" = 0 ] && printf '\nall checks passed\n' || printf '\nSOME CHECKS FAILED\n'
exit $fail
