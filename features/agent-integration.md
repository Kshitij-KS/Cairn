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
updated: 2026-09-28
---
# Agent Integration

## Card
Agent Integration is the instructions and hooks that make each agent follow the protocol: CLAUDE.md and its mirrors, the team-memory skill, the /cairn /cairn-context /cairn-recall /cairn-remember /cairn-gaps /cairn-try /cairn-feature commands, and session hooks that open, evict and watch the session ledger.

## Contract
The skill copies under .claude/ and .kiro/ are byte-identical to .agents/skills/; the guard allows them only while they are.

## Observations
- [risk] Kiro and Cursor hook and command behaviour is not verified against their current docs ^6dd17c
- [fact] Each Kiro event is one hook (sync-memory.py pre --then-session, post --significance) so its steps run in a fixed order ^fa4562
- [fact] Claude Code's allow-list names mem verbs; mem role, playbook approve, core init and codeowners --write are denied ^9e8ff4
- [fact] A project tier's hooks and commands are derived from the company tier's own files, so the two cannot drift ^234c12

## Relations
- depends_on [[Context Protocol]]
- depends_on [[Memory Sync]]
- part_of [[Core]]
