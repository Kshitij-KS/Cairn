---
title: Conventions
type: context
tags: [conventions, process, context, canonical]
level: L2
confidentiality: internal
created: 2026-09-27
updated: 2026-09-27
---
# Conventions

Process and coding conventions that apply across every project. Project-specific conventions
belong in that project's memory.

## Observations
- [rule] Load context before any task (`mem load "<the task>"`); save durable learnings after, only if they survive the week ^3da3f8
- [rule] Trust order: accepted decisions > Core, features, context > projects > log; contradictions are flagged, never silently resolved ^303c75
- [rule] Agents write observations only; everything else goes through a proposal a person approves ^45bbde
- [rule] Every note has frontmatter (title, type, tags), Observations and at least one Relations entry ^94d773
- [rule] Relation types are single tokens: relates_to, part_of, depends_on, supersedes, implements, owned_by, blocked_by ^885b7a
- [rule] Docs are updated in the same change as the code they describe ^1d6d0a
- [rule] Secrets live in git-ignored files and a secret manager, never in repositories, docs or memory ^afe0d0
- [rule] <!-- TODO: fill in --> branching, review, commit message style, definition of done ^8f71dc

## Relations
- relates_to [[Company]]
- relates_to [[Glossary]]
- depends_on [[Tooling Stack]]
- relates_to [[ADR Process]]
