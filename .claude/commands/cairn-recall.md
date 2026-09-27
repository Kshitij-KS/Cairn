---
description: 'Ranked single facts (claims) from team memory, each with its id and why it ranked'
argument-hint: '<question>'
allowed-tools: 'Bash(uv run -q --script scripts/mem.py:*)'
---

Run `uv run -q --script scripts/mem.py recall "$ARGUMENTS"` and show the top results as a short list: the claim text, its `^id`, the note it lives in, and the reason it ranked. If nothing relevant came back, say so and offer `/cairn-gaps` to record what was missing. Do not paraphrase claims into something stronger than they say.
