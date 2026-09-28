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
updated: 2026-09-28
---
# Memory Atlas

## Card
Memory Atlas is the visual map of the memory: a build step turns the notes into graph.json (public builds withhold note bodies, and summaries above the publication threshold) and a static web page renders it as an explorable graph.

## Contract
A public build never contains a restricted note, a trial or eval body, any note below the publication significance, a withheld title, or a code path. The page reads only graph.json.

## Observations
- [status] Publishing is manual while automatic publication is paused ^cb4138
- [fact] graph.json schema 4 carries features, gaps, trials, playbooks (derived trust and counts only) and, in full builds only, local session ledgers; build_atlas.py --verify is the redaction gate CI runs ^308f40
- [fact] A note with public_title or publish_title false is published under an opaque id and path; relations to it resolve by its real title ^c142ec
- [fact] Activity publishes only the public paths of published notes, never code paths or a note's earlier path ^539fa4
- [fact] --verify compares with a fresh build by default and never trusts the file's own publication block ^735f09
- [decision] Since 2026-09-28 the main view is a sky drawn on a canvas: each area a sunflower cluster with fixed homes, so nothing ever expands or overlaps; choosing a note flies the camera to it and brings its relations out to stand left (relied on) and right (relying); a grid of cards is the plain alternative ^f22fa6
- [fact] web/index.html is a single file built by Vite from web/app and committed; npm run check-build fails if it drifts, and the build pins its two inline scripts by sha256 in the vercel.json CSP ^b72daf
- [fact] The sky caches name widths and clears the cache when web fonts finish loading, so names measured in the fallback font are never drawn in the wider real one on top of each other ^76194f

## Relations
- depends_on [[Memory Guard]]
- part_of [[Core]]
