# /cairn-try: Open, list, keep or drop a context trial (an experiment on the memory)

Work with context trials. Arguments: <the text after the command>

- `list` (or nothing): run `uv run -q --script scripts/mem.py trials` and show each trial's slug, hypothesis, who sees it, and days left.
- `keep <slug>`: run `uv run -q --script scripts/mem.py eval --trial <slug>` first and show the comparison. Then run `uv run -q --script scripts/mem.py keep <slug>`. If you are an agent and the change is above L0, this produces a proposal, which is correct: say so.
- `drop <slug> --result "..."`: run `uv run -q --script scripts/mem.py drop <slug> --result "..."`. The result is written to the journal; make it say what was learned.
- anything else: treat it as a new trial and run `uv run -q --script scripts/mem.py try <the text after the command>`. A trial needs a hypothesis and at least one `--change`, in one of three forms: `add to "Note title": [fact] text`, `replace ^id with: [category] text`, `retire ^id`. Report the slug and who will see it.
