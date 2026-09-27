---
title: Company
type: context
tags: [company, context, canonical]
level: L2
confidentiality: internal
created: 2026-09-27
updated: 2026-09-27
---
# Company

Who we are and what we are working towards. Project-specific facts live in each project's own
`memory/` folder, not here.

<!-- TODO: 3-5 sentences: name, what the team exists to do, who it serves, current stage, size, timezones. -->

## Observations
- [fact] Owner of this memory: __OWNER_NAME__ ^2a3070
- [status] <!-- TODO: fill in --> current stage and the one thing the team is trying to prove this quarter ^a5cb7b
- [constraint] This memory must cost nothing to run: no hosted or paid tiers (see [[ADR-001 Shared Memory System]]) ^6a19e7
- [rule] Never store credentials, customer data, salaries or private-message content (see [[Conventions]]) ^14dd97

## Relations
- relates_to [[Product]]
- relates_to [[Roles]]
- relates_to [[Conventions]]
