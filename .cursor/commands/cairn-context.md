# /cairn-context: Load the team memory for an ask: core first, then the feature and its neighbourhood

Run the entry protocol for this ask and read what it loads.

1. Run `uv run -q --script scripts/mem.py load "<the text after the command>"`. If <the text after the command> is empty, use the person's most recent request as the ask. Add `--touching <path>` for each file you already know you will edit.
2. Exit code 2: it could not tell which feature. Show the candidate features it listed and ask the person which one, in one question. Then re-run with `--feature "<name>"`.
3. Read the bundle file named in the output, once.
4. Reply with the receipt's first line, then a three-line summary of what matters for the ask. Mention any `review_needed` note and any gap it reported.
