# /playbook-save: Save the task you just finished as a playbook a teammate's AI can walk them through

Save what this session just did as a playbook: <the text after the command>

1. Reconstruct from this session, and from `uv run -q --script scripts/mem.py playbook since` if a start was marked: the goal, what must be true before starting, the steps that actually worked in order, each step's command and how to check it worked, and every problem hit with its fix. Leave out dead ends, except as caveats.
2. Replace secrets and anything specific to this machine or person with placeholders: `<YOUR_AWS_PROFILE>`, `<REPO_PATH>`, `<YOUR_EMAIL>`. Never write a key, token or password, even redacted in part.
3. Write the draft to a temporary file in this format (a heading and an `## Relations` line are added if missing):

   ```markdown
   ---
   title: <what someone would search for, Title Case>
   tags: [setup, <tool>]
   ---
   <one or two sentences: what you end up with>

   ## Before you start
   - [prereq] <what must already be true>

   ## Steps

   ### 1. <step> [local]
   Run: `<command>`
   Check: <how to tell it worked>

   ## Caveats
   - [blocker] (step 1) <what went wrong>
   - [fix] (step 1) <what fixed it>

   ## Verify
   - <how to tell the whole thing worked>
   ```

   Mark every step: `[check]` only reads, `[local]` changes this machine, `[external]` changes anything shared (cloud, accounts, git push, money). Every step gets a `Check:`.
4. Show the person the draft and ask once: "Save as is, or change something?"
5. Run `uv run -q --script scripts/mem.py playbook save <draft-file>`. Exit 2 means a similar playbook exists: show it and ask whether to update it (`--update <ID>`) or save a new one (`--new`). Exit 3 means a secret: replace it and retry. Exit 5: fix the findings it printed.
6. Report the id in one line. It is committed with the rest of the notes at the end of the turn.
