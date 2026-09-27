---
title: ADR-001 Shared Memory System
type: decision
status: accepted
tags: [adr, memory]
level: L2
confidentiality: internal
created: 2026-09-27
updated: 2026-09-27
---
# ADR-001 Shared Memory System

**Decision:** the team's AI agents share one memory made of Markdown notes in a private git
repository, served locally by the Basic Memory MCP server and read through `scripts/mem.py`.
Each code repository can add its own `memory/` tier with the same rules.

**Why:** notes in git are reviewable, diffable, free, and readable by every AI client; Basic
Memory adds search and a knowledge graph without a hosted service.

**Alternatives rejected:** hosted vector stores and paid team tiers (cost and lock-in); a wiki
(not reviewable per change, not readable by agents without a connector).

## Observations
- [decision] Shared memory is Markdown in git, indexed locally by Basic Memory, zero paid services ^9c0578
- [decision] Basic Memory is used unmodified as a separate process, so its AGPL licence does not reach product code ^72dbbf
- [risk] Basic Memory breaking changes; mitigated by keeping notes to its documented core format ^78f4f6

## Relations
- relates_to [[Core]]
- relates_to [[Tooling Stack]]
