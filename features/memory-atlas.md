---
title: Memory Atlas
type: feature
status: live
owner: __OWNER__
covers: ["scripts/build_atlas.py", "web/**", ".github/workflows/atlas.yml"]
aliases: ["atlas", "visualization", "graph", "dashboard"]
tags: [feature]
level: L1
confidentiality: internal
created: 2026-09-23
updated: 2026-09-27
---
# Memory Atlas

## Card
Memory Atlas is the visual map of the memory: a build step turns the notes into graph.json (public builds withhold note bodies, and summaries above the publication threshold) and a static web page renders it as an explorable graph.

## Contract
A public build never contains a restricted note, a trial or eval body, or any note below the publication significance. The page reads only graph.json.

## Observations
- [status] Publishing is manual while automatic publication is paused ^cb4138
- [fact] graph.json schema 4 carries features, gaps, trials, playbooks (derived trust and counts only) and, in full builds only, local session ledgers; build_atlas.py --verify is the redaction gate CI runs ^308f40

## Relations
- depends_on [[Memory Guard]]
- part_of [[Core]]
