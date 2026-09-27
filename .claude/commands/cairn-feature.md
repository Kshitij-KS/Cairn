---
description: 'List features, or propose a new one with the code paths it covers'
argument-hint: '[list] | new "<name>" --covers <glob> [--owner handle] [--depends NAME]'
allowed-tools: 'Bash(uv run -q --script scripts/mem.py features:*), Bash(uv run -q --script scripts/mem.py feature:*)'
---

Arguments: $ARGUMENTS

- `list` or nothing: run `uv run -q --script scripts/mem.py features` and show each feature's status, owner, what it relies on, and what relies on it.
- `new ...`: run `uv run -q --script scripts/mem.py feature new` with the rest of the arguments. Features are L1: as an agent this writes a proposal. Every feature must `--covers` at least one real path; the guard checks the globs match files.
