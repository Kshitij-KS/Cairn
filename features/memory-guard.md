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
updated: 2026-09-28
---
# Memory Guard

## Card
Memory Guard is the enforcement engine every write passes through at commit: it derives each note's level from its path, caps agents at L0, stamps attribution from the git identity and claim ids, rejects secrets and imperatives, validates format, features and trials, and flags notes a planning change has made stale.

## Contract
Exit codes are a public interface: 0 ok, 3 secret, 4 access denied, 5 invalid. A note's level is a pure function of its path and governance/roles.json. A claim id, once assigned, is never reassigned to different text in another note; in a collision the claim committed first keeps it. What is judged is what is committed (the index, or the head of the range).

## Observations
- [constraint] The guard ignores MEMORY_ACTOR_KIND=human or bot inside an agent runtime with no terminal; a process can still drop the markers, so the real boundary is review plus branch protection on the remote ^996ee7
- [fact] codeowners writes a level-aware file once enforcement.auto_merge_levels is set, and only a marked memory block in a project tier ^4adfa1
- [fact] With no MEMORY_ACTOR_KIND set, an agent runtime marker in the environment (CLAUDE_CODE_SESSION_ID and others) makes the actor an agent ^7451c1
- [fact] Run from a code repo's root, the notes root is ./memory when it holds .basic-memory/project.json ^85a13c
- [gotcha] git quotes non-ASCII file names by default; the guard reads every listing NUL-separated with core.quotePath=false, because a quoted scripts/évil.py matched no rule and passed as L0 ^3e4346
- [fact] A structural floor makes dot-files, instruction files (AGENTS.md, nested CLAUDE.md), scripts and aliasable names L3 at any depth, and a symbolic link L3 anywhere ^985352
- [fact] check --staged reads the index and --range the head of the range, never the working tree ^96d2ba
- [fact] An existing note's author never changes; stamp restores it and a change to it fails ^2d12eb
- [fact] A lost claim id is reported as gone; ambiguous carry-forward gives a new id rather than moving one to another fact ^be7c9f
- [fact] The secret scan matches key prefixes (sk-, sk-ant-) only at the start of a token, so a CSS name such as mask-image-linear-to-color in the built Atlas page is not read as a key ^70f36d
- [fact] The guard resolves the notes root and git's repository root with realpath, so a tier reached through a symlink or a Windows 8.3 short name (C:\Users\RUNNER~1) keeps its prefix; tested through an alias in test_security ^8aaed9

## Relations
- part_of [[Core]]
- implements [[ADR-002 Memory Governance And Access Tiers]]
