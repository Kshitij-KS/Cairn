---
title: Agent Integration
type: feature
status: live
owner: __OWNER__
covers: ["CLAUDE.md", ".claude/**", ".agents/**", ".kiro/**", ".cursor/**"]
aliases: ["hooks", "skill", "slash commands", "CLAUDE.md"]
tags: [feature]
level: L1
confidentiality: internal
created: 2026-09-23
updated: 2026-09-27
---
# Agent Integration

## Card
Agent Integration is the instructions and hooks that make each agent follow the protocol: CLAUDE.md and its mirrors, the team-memory skill, the /cairn /cairn-context /cairn-recall /cairn-remember /cairn-gaps /cairn-try /cairn-feature commands, and session hooks that open, evict and watch the session ledger.

## Contract
The skill copies under .claude/ and .kiro/ are byte-identical to .agents/skills/; the guard allows them only while they are.

## Observations
- [risk] Kiro and Cursor hook and command behaviour is not verified against their current docs ^6dd17c

## Relations
- depends_on [[Context Protocol]]
- depends_on [[Memory Sync]]
- part_of [[Core]]
