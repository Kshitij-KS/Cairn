---
description: 'Find a playbook: a task someone already did with an AI, with their steps and fixes'
argument-hint: '<words> | --regex <pattern>'
allowed-tools: 'Bash(uv run -q --script scripts/mem.py:*)'
---

Find playbooks for: $ARGUMENTS

1. Run `uv run -q --script scripts/mem.py playbook find $ARGUMENTS` (it searches this project and the company memory, tolerates typos; `--regex` for a pattern, `--tag <tag>` to filter).
2. Show the results as they are: id, title, trust (approved, reproduced or unreviewed; stale if no recent success), author, successes and last success.
3. If one fits, offer to walk the person through it with `/playbook-run <ID>`. If none fits, say so; when they finish the task, `/playbook-save` keeps it for the next person.
