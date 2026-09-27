---
description: 'Record or list what the memory could not answer'
argument-hint: '[what was missing] [--feature NAME]'
allowed-tools: 'Bash(uv run -q --script scripts/mem.py:*)'
---

If $ARGUMENTS is non-empty, run `uv run -q --script scripts/mem.py gap "$ARGUMENTS"` and confirm in one line. Otherwise run `uv run -q --script scripts/mem.py gaps` and show the open gaps grouped by feature, most frequent first.
