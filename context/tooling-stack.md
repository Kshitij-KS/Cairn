---
title: Tooling Stack
type: context
tags: [tooling, context, canonical]
level: L2
confidentiality: internal
created: 2026-09-27
updated: 2026-09-27
---
# Tooling Stack

The tools the team relies on, and the decisions about them.

## Observations
- [tool] AI clients with first-class support: Claude Code, Kiro, Cursor and Claude Desktop ^85e8af
- [tool] Basic Memory (local MCP server, AGPL, used unmodified as a separate process) indexes these notes ^4b86eb
- [tool] uv runs every script here (PEP 723, standard-library Python), so there is no install step beyond uv ^7041de
- [tool] GitHub hosts the repository; branch protection and the memory-gate workflow are the enforcement that holds ^3dc60e
- [tool] <!-- TODO: fill in --> languages, frameworks, cloud, observability ^a5043e

## Relations
- relates_to [[Architecture]]
- relates_to [[Conventions]]
