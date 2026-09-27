---
title: Project Scaffolding
type: feature
status: live
owner: __OWNER__
covers: ["scripts/new-project-memory.sh", "scripts/new-project-memory.ps1", "templates/**"]
aliases: ["new project", "template", "project tier"]
tags: [feature]
level: L1
confidentiality: internal
created: 2026-09-23
updated: 2026-09-27
---
# Project Scaffolding

## Card
Project Scaffolding creates a project tier inside a code repo: memory/ with its own notes, policy, guard, protocol and sync scripts, plus the agent configs for Claude Code, Kiro and Cursor.

## Contract
Never overwrites an existing file; configs that already exist get a .team-memory.suggested file to merge by hand.

## Observations
- [gotcha] Before 2026-09-23 the scaffold did not copy memory_guard.py, so project tiers ran with policy unenforced ^205493

## Relations
- depends_on [[Memory Sync]]
- depends_on [[Memory Guard]]
- depends_on [[Context Protocol]]
- part_of [[Core]]
