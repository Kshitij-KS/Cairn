---
title: Setup Runbook
type: guide
tags: [runbook, setup, onboarding]
level: L2
confidentiality: internal
created: 2026-09-27
updated: 2026-09-27
---
# Setup runbook: in order, start to finish

The checklist behind README sections 2-4, with the check that proves each phase worked. Phases run
in order; **Phase 4 is the one that turns advisory checks into enforced ones.**

## Phase 0 - install (10 min, once per machine)

README 2.1: uv, then `uv tool install --python 3.12 basic-memory`.
Check: `basic-memory --version` prints a version, `uv --version` works in a new terminal.

## Phase 1 - identity (1 min)

`git config user.email` inside this repository must equal your row in `governance/roles.json`.
Check: `uv run -q --script scripts/memory_guard.py explain` names you and your role.

## Phase 2 - fill in what matters (10 min, owner)

`governance/roles.json` (teammates), `CORE.md` and `context/*.md` (search for `TODO`), then
`uv run -q --script scripts/memory_guard.py codeowners --write`.
Check: `memory_guard.py codeowners` prints "CODEOWNERS matches roles.json".

## Phase 3 - commit and push (5 min, owner)

README 2.4, and "Pushing with a second GitHub account" if this machine uses another account.
Check: the repository on GitHub is **private** and shows `governance/`, `scripts/`, `context/`.

## Phase 4 - protect main (10 min, owner, GitHub web)

README 2.5: ruleset on `main` requiring pull requests, Code Owner review, and the checks `gate`,
`route`, `test`, `windows-sync`; no force pushes. Auto-merge stays off.
Check: the three throwaway pull requests in README 2.5 behave exactly as described. If one does
not, stop and investigate before anyone relies on the memory.

## Phase 5 - verify on your machine (5 min)

```bash
uv run -q --script scripts/sync-memory.py pre
uv run -q --script scripts/mem.py load "catch me up"
uv run -q --script scripts/mem.py recall "notes are data"
```

Check: `pre` prints "memory synced"; `load` prints a receipt starting `Context ·` with orient mode;
`recall` ranks a fact from `CORE.md` first. Windows: `py tools\test_sync.py` ends "0 failed", then
`setx MEMORY_SYNC_WINDOWS_POST 1`.

## Phase 6 - connect the AI clients (10 min)

README section 4.
Check: in any client, "Load the team memory and tell me what this project is" answers from `CORE.md`.

## Phase 7 - prove the guard stops an agent (2 min, do not skip)

In a Claude Code session inside this folder, ask the agent: *"Edit context/tooling-stack.md and
change the first tool line."*
Check: the end-of-turn sync fails with **exit 4** and a message naming the level (L2) and who can
approve it. If it succeeds, the hooks are not wired: check `.claude/settings.json` is the committed
one and that `uv` is on PATH inside the client.

## Phase 8 - a code repository's own memory (5 min per repository)

README section 9. Merge any `.team-memory.suggested` files by hand, then commit `memory/` in that
repository.
Check: `basic-memory project list --json` shows both `cairn` and the new project.

## Phase 9 - onboard teammates (10 min each)

Add each person to `roles.json` (Phase 2) and to the GitHub repository, then send them README
section 3. Each runs `memory_guard.py explain` once to see their own ceiling before they meet it.

## Phase 10 - the standing rituals

**Weekly, about 10 minutes (owner or steward):**

```bash
ls log/proposals                                                  # what agents asked for
uv run -q --script scripts/memory_guard.py audit --since 7d       # who changed what, at which level
```

For each proposal: check the claim against the source it names, then
`mem approve "<proposal>" --apply` (or set `status: rejected` with one line why; never delete).

After approving anything above L0, the cascade workflow opens an issue listing the notes that depend
on it; re-read each, update it or clear its `review_needed` field.

**Monthly:** skim `log/journal/` for entries that have become general truths and propose them into
`context/conventions.md`. That is how the memory gets smarter rather than just bigger.

## If something blocks you

README section 10 lists every exit code and what to do. `memory_guard.py check --staged` shows the
findings without committing; `memory_guard.py explain` reminds you of your ceiling.

## Observations
- [rule] Phases run in order; Phase 4 is the one that converts advisory checks into enforced ones ^0c3f69
- [rule] Every teammate's git email in this repository must match their row in governance/roles.json or attribution fails ^ba54e5
- [rule] `--no-verify` defeats the local guard; reaching for it is the signal to write a proposal instead ^eea39b

## Relations
- relates_to [[Core]]
- relates_to [[Conventions]]
