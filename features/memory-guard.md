---
title: Memory Guard
type: feature
status: live
owner: __OWNER__
covers: ["scripts/memory_guard.py"]
aliases: ["guard", "policy check", "pre-commit"]
tags: [feature]
level: L1
confidentiality: internal
created: 2026-09-23
updated: 2026-09-27
---
# Memory Guard

## Card
Memory Guard is the enforcement engine every write passes through at commit: it derives each note's level from its path, caps agents at L0, stamps attribution from the git identity and claim ids, rejects secrets and imperatives, validates format, features and trials, and flags notes a planning change has made stale.

## Contract
Exit codes are a public interface: 0 ok, 3 secret, 4 access denied, 5 invalid. A note's level is a pure function of its path and governance/roles.json. A claim id, once assigned, is never reassigned to different text in another note.

## Observations
- [constraint] The guard ignores MEMORY_ACTOR_KIND=human or bot inside an agent runtime with no terminal; a process can still drop the markers, so the real boundary is review plus branch protection on the remote ^996ee7
- [fact] codeowners writes a level-aware file once enforcement.auto_merge_levels is set, and only a marked memory block in a project tier ^4adfa1
- [fact] With no MEMORY_ACTOR_KIND set, an agent runtime marker in the environment (CLAUDE_CODE_SESSION_ID and others) makes the actor an agent ^7451c1
- [fact] Run from a code repo's root, the notes root is ./memory when it holds .basic-memory/project.json ^85a13c

## Relations
- part_of [[Core]]
- implements [[ADR-002 Memory Governance And Access Tiers]]
