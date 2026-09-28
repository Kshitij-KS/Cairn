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
updated: 2026-09-28
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
- [fact] Before pre and post the dispatcher moves past local commits whose content upstream already has, so a squash-merged pull request does not conflict with its own source commits ^e93c79
- [fact] A left-behind memory/<who> branch whose content is merged into the base is reused; the person's branch is their roles.json handle ^ae2389
- [fact] The dispatcher saves and restores the index around a pull, so autostash no longer unstages the person's files ^996bf9
- [fact] The lock is judged by its owner process on this machine, not by age alone, and is stolen by rename ^b537b6
- [fact] sync-memory resolves its own location and the repository root with realpath; a relpath between a short or symlinked path and git's long one made every tier commit look like it changed files outside the tier, and CI now runs every suite with TMPDIR behind a symlink ^f72a20

## Relations
- depends_on [[Memory Guard]]
- depends_on [[Context Protocol]]
- part_of [[Core]]
