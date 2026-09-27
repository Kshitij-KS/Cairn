---
title: ADR-003 Claims Recall And Trials
type: decision
status: proposed
tags: [adr, memory]
level: L2
confidentiality: internal
created: 2026-09-27
updated: 2026-09-27
---
# ADR-003 Claims Recall And Trials

**Decision:** each observation line (`- [category] text ^id`) is an addressable fact with a stable
six-character id that survives rewording. Facts can be recalled with ranked reasons
(`mem recall`), retired with history kept, pinned or muted per person, and tested with retrieval
evals. Changes to the memory can be tried as **trials**: an overlay visible only to named people,
with an expiry, that is kept through the normal permission rules or dropped with a recorded
result. Retrieval order is superseded by [[ADR-004 Context Protocol]].

## Observations
- [decision] Every observation line carries a stable id assigned by the guard's stamp ^101c9e
- [decision] Trials are overlays applied at read time; no file changes until a trial is kept ^aa1d18
- [decision] Retrieval evals are deterministic and run before and after a trial ^beb493
- [risk] Id carry-forward on edits is heuristic; a full rewrite gets a new id ^9d3154

## Relations
- relates_to [[Core]]
- relates_to [[ADR-004 Context Protocol]]
