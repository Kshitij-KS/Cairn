# /cairn-feature: List features, or propose a new one with the code paths it covers

Arguments: <the text after the command>

- `list` or nothing: run `uv run -q --script scripts/mem.py features` and show each feature's status, owner, what it relies on, and what relies on it.
- `new ...`: run `uv run -q --script scripts/mem.py feature new` with the rest of the arguments. Features are L1: as an agent this writes a proposal. Every feature must `--covers` at least one real path; the guard checks the globs match files.
