# /cairn-gaps: Record or list what the memory could not answer

If <the text after the command> is non-empty, run `uv run -q --script scripts/mem.py gap "<the text after the command>"` and confirm in one line. Otherwise run `uv run -q --script scripts/mem.py gaps` and show the open gaps grouped by feature, most frequent first.
