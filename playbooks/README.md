---
title: Playbooks Index
type: process
tags: [playbooks, process]
level: L0
confidentiality: internal
created: 2026-09-28
updated: 2026-09-28
---
# playbooks/ — tasks someone already finished, ready to replay

A **playbook** is a multi-step setup or task someone completed with an AI, written down so a
teammate's AI can walk them through it: the steps that worked, each with a check, and the problems
hit along the way with their fixes. Each `PB-XXXX-<slug>.md` has a run log `PB-XXXX-<slug>.runs`
beside it, one line per replay.

Save one with `/playbook-save` after finishing a task; find one with `/playbook-find <words>`;
replay one with `/playbook-run <ID>`. Without slash commands: `mem playbook save|find|run`.

## Observations
- [rule] Playbooks are L0: anyone saves one and logs their own runs; trust is earned, see ADR-005
- [rule] A run log is append-only and each line names the person who did the run
- [rule] Steps are marked [check], [local] or [external]; an unmarked step is treated as [external]

## Relations
- relates_to [[ADR-005 Playbooks]]
- relates_to [[Core]]
