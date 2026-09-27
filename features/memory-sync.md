---
title: Memory Sync
type: feature
status: live
owner: __OWNER__
covers: ["scripts/sync-memory.py", "scripts/sync-memory.sh", "scripts/sync-memory.ps1"]
aliases: ["sync", "hooks", "pull", "push"]
tags: [feature]
level: L1
confidentiality: internal
created: 2026-09-23
updated: 2026-09-27
---
# Memory Sync

## Card
Memory Sync moves notes between each machine and the shared repo: pull at session start, then stamp, check, commit and push at the end of a turn, with one hook command that works on Windows, macOS and Linux.

## Contract
Never force-pushes the default branch; a merge conflict stops the sync with exit 2 and names the files. `--agent` marks the actor as an agent for the guard. In pull-request mode (enforcement.mode pr, or a push refused by a protected branch) notes go to the person's own branch memory/<who> with one open pull request; that branch is rewritten only with a lease and never when the remote holds changes this machine lacks.

## Observations
- [fact] After a successful pull it compiles the local claim pack and closes expired trials, best-effort ^9414b0
- [fact] The Sync-Actor commit trailer uses the same agent-marker default as the guard ^975a71
- [fact] A push refused by a protected branch is exit 7 from the native scripts, and the dispatcher turns it into a pull request ^010496

## Relations
- depends_on [[Memory Guard]]
- depends_on [[Context Protocol]]
- part_of [[Core]]
