---
title: 2026-09-22 Basic Memory keeps stale relations when a project path changes
type: gotcha
tags:
- basic-memory
- indexing
- gotcha
level: L0
confidentiality: internal
created: 2026-09-22
updated: 2026-09-27
permalink: log/journal/2026-09-22-basic-memory-stale-index-after-path-change
---
# Basic Memory keeps stale relations when a project path changes

`basic-memory project remove <name>` followed by `project add <name> <new-path>` does **not**
purge the old rows. `reindex --full` afterwards reports every file as indexed and still serves
the previous relation types, so the graph silently disagrees with the files on disk.

Found while verifying the cascade: the notes contained six `depends_on` edges and the index
reported one, having kept the `relates_to` rows the same notes carried before they were edited.
Registering the identical content under a fresh project name returned the correct six, which is
what proves the parser is fine and the index was stale.

## Observations
- [gotcha] `project remove` + `project add` under the same name keeps stale relation rows; `reindex --full` does not clear them and still reports "N observed, N indexed" ^b43aed
- [symptom] The graph serves an old relation type after a note's `## Relations` section is edited ^c390aa
- [fix] Register the path under a new project name, or clear the index and rebuild, before trusting relation counts ^e7b4a0
- [fact] Verified 2026-09-22 on basic-memory 0.23.2: the same content gave depends_on=1 on the reused project and depends_on=6 on a fresh one ^ef3047
- [rule] A reindex that reports success is not evidence the graph is correct — check a known edge ^3a8973

## Relations
- relates_to [[Tooling Stack]]
- relates_to [[Access Model]]