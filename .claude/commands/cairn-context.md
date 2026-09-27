---
description: 'Load the team memory for an ask: core first, then the feature and its neighbourhood'
argument-hint: '[the ask] [--mode M] [--feature NAME] [--ref REF]'
allowed-tools: 'Bash(uv run -q --script scripts/mem.py:*)'
---

Run the entry protocol for this ask and read what it loads.

1. Run `uv run -q --script scripts/mem.py load "$ARGUMENTS"`. If $ARGUMENTS is empty, use the person's most recent request as the ask. Add `--touching <path>` for each file you already know you will edit.
2. Exit code 2: `mem` is asking the person which kind of task and/or which feature. Run the same command with `--json`, show its `ask_the_person` questions with the AskUserQuestion tool (each option's label and description; the person can also type their own answer), then re-run with the chosen options' `args`. Never pick for them.
3. Read the bundle file named in the output, once.
4. Reply with the receipt's first line, then a three-line summary of what matters for the ask. Mention any `review_needed` note and any gap it reported.
