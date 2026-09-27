---
title: ADR-005 Playbooks
type: decision
status: proposed
tags: [adr, playbooks, trust]
level: L2
confidentiality: internal
created: 2026-09-28
updated: 2026-09-28
---
# ADR-005 Playbooks

**Decision:** a finished multi-step task someone did with an AI can be saved as a **playbook**
(`playbooks/PB-XXXX-<slug>.md`): its steps in order, each with a `Run:` and a `Check:` and a marker
(`[check]` reads only, `[local]` changes this machine, `[external]` changes anything shared), the
problems hit with their fixes, and how to verify the whole. Anyone saves one; a teammate's AI
replays it with them from a guided-run file, running `[check]` steps and asking before every
other step. `mem` never executes a playbook's commands. Each run is one line in an append-only
`<id>.runs` file beside it, merged with git's `union` driver.

Trust is **derived, never stored**: `approved` when a person whose level reaches the approval
level (L1 in a project tier, L2 in the company tier) approved the current steps (`approved_steps`
is a hash of the Steps section, so editing a step drops the approval by itself); `reproduced` when
someone other than the author logged a success against the current steps; otherwise
`unreviewed`, and `stale` beside it when the last success is over 90 days old. The guard enforces
the id format and uniqueness, step numbering and markers, append-only run logs whose new lines
name whoever committed them (locally and per commit in CI), and approvals given only by that
person with that level, never by an agent.

## Observations
- [decision] Trust is derived from a steps-bound approval and the run log, so it cannot go stale or be forged by editing a label
- [decision] mem writes a guided-run file and never runs a playbook's commands; the agent asks before every step that is not a check
- [decision] Run records live in an append-only .runs file per playbook with git's union merge
- [risk] A summary written from a session can miss a step or keep a machine-specific value; the author reviews the draft and the guard warns on home paths, account ids, private IPs and unknown emails

## Relations
- relates_to [[Core]]
- relates_to [[ADR-004 Context Protocol]]
- relates_to [[ADR-002 Memory Governance And Access Tiers]]
