---
description: 'Team memory status: who you act as, what is loaded, trials, gaps, proposals waiting'
allowed-tools: 'Bash(uv run -q --script scripts/mem.py:*)'
---

Run `uv run -q --script scripts/mem.py status` and `uv run -q --script scripts/mem.py context`, then show in under ten lines: who this session acts as and its write cap, the ref being read, notes loaded this session, live trials that apply to this person, open gaps, proposals waiting for review. End with the three verbs most likely to help next.
