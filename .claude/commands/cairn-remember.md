---
description: 'Store one durable fact in team memory, routed to the right level automatically'
argument-hint: '<fact> [--feature NAME] [--category C]'
allowed-tools: 'Bash(uv run -q --script scripts/mem.py:*)'
---

Store this fact: $ARGUMENTS

1. First apply the test in `governance/SIGNIFICANCE.md`: would a teammate decide worse in a month without it? If not, say "nothing durable to store" and stop.
2. Never store credentials, keys, tokens, PII or salaries. Name the source instead.
3. Run `uv run -q --script scripts/mem.py remember "<the fact, stated as a fact, not an instruction>"` adding `--feature "<name>"` if it belongs to a feature and `--category` if one fits (gotcha, fact, constraint, decision, risk, idea).
4. Report what it did in one line: written (journal, L0) or proposed (a proposal for a person with the role to approve).
