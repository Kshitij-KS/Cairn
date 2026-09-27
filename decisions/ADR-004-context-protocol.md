---
title: ADR-004 Context Protocol
type: decision
status: proposed
tags: [adr, memory, protocol]
level: L2
confidentiality: internal
created: 2026-09-27
updated: 2026-09-27
---
# ADR-004 Context Protocol

**Decision:** every agent enters the memory the same way: the big picture (`CORE.md`) first, then
the feature the task is about, found from the files it will touch and the words used, then that
feature's neighbours in the direction the task needs (what it relies on when building, what relies
on it when changing). `mem load "<the task>"` does this, caches what it read for the session, and
writes one bundle file. When it cannot tell which feature is meant, it asks one question.

Features are notes in `features/` with a short card, a contract (what the part promises) and the
code paths it `covers:`. Changing covered code without updating its feature note is flagged.

## Observations
- [decision] Agents read what the task needs; the protocol governs order and scope, not a token cap ^38a84d
- [decision] Scope follows dependency direction; relates_to links are never followed ^b3a68b
- [decision] A session never loads the same note twice unless it changed or the context was compacted ^2d67ce
- [decision] Only the latest context is read unless a past version is named explicitly ^665b7e
- [risk] Resolution from words is heuristic; files touched are the most reliable signal ^02bdda

## Relations
- relates_to [[Core]]
- relates_to [[ADR-003 Claims Recall And Trials]]
