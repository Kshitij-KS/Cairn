#!/usr/bin/env bash
# new-project-memory.sh - give a code repository its own memory tier (templates/project-memory/README.md)
#
#   scripts/new-project-memory.sh <path-to-project-repo> [project-name] [--update] [--no-hook]
#
# A thin wrapper: the scaffold itself is scripts/new_project_memory.py, one implementation for every
# platform (the shell and PowerShell copies drifted apart, recheck 08-F3..F10). Python 3 is needed
# anyway: the memory guard is Python.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
for py in python3 python py; do
  # `command -v` alone is not enough: the Windows Store alias for python3 is on PATH and runs nothing.
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then
    exec "$py" "$HERE/new_project_memory.py" "$@"
  fi
done
echo "ERROR: Python 3 is required (install it, then rerun)" >&2
exit 1
