---
title: Project Scaffolding
type: feature
status: live
owner: __OWNER__
covers: ["scripts/new_project_memory.py", "scripts/new-project-memory.sh", "scripts/new-project-memory.ps1", "templates/**"]
aliases: ["new project", "template", "project tier"]
tags: [feature]
level: L1
confidentiality: internal
created: 2026-09-23
updated: 2026-09-28
---
# Project Scaffolding

## Card
Project Scaffolding creates a project tier inside a code repo: memory/ with its own notes, policy, guard, protocol and sync scripts, plus the agent configs for Claude Code, Kiro and Cursor.

## Contract
Never overwrites an existing file; files that already exist get a .team-memory.suggested file to merge by hand, and a second run changes nothing. Installs a memory-gate workflow scoped to memory/ and the memory block of the repository's CODEOWNERS, which also owns the gate workflow and CODEOWNERS itself. The new tier passes its own guard before its first commit, and gets the same agent hooks and commands as the company tier.

## Observations
- [gotcha] Before 2026-09-23 the scaffold did not copy memory_guard.py, so project tiers ran with policy unenforced ^205493
- [decision] Since 2026-09-28 one Python implementation (new_project_memory.py) does the scaffolding; the .sh and .ps1 files only find Python and run it, because the two shell copies had drifted and the PowerShell one could not be tested on Linux ^3deb4e
- [fact] A project tier's context/, decisions/ and CORE.md are L1 through paths.project_rules; in the company tier they are L2 ^070500
- [fact] A tier scaffolded under a path with a symlink or 8.3 short name classifies and writes CODEOWNERS exactly as under its real path; test_scaffold catches it when TMPDIR sits behind a symlink ^eb6b32

## Relations
- depends_on [[Memory Sync]]
- depends_on [[Memory Guard]]
- depends_on [[Context Protocol]]
- part_of [[Core]]
