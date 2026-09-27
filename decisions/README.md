---
title: ADR Process
type: process
permalink: decisions/adr-process
tags: [adr, decisions, process, canonical]
level: L2
confidentiality: internal
created: 2026-09-25
updated: 2026-09-27
---
# decisions/ — Architecture Decision Records

One file per decision that is expensive to reverse: technology choices, system boundaries,
vendor commitments, data-handling rules, process rules the whole team must follow.
**Humans write and edit ADRs. Agents propose them** via a note in `log/proposals/` titled `PROPOSAL - ADR-<title>`.

## How to write one

1. Copy `ADR-000-template.md` to `ADR-NNN-<kebab-slug>.md` (next free number, zero-padded to 3).
2. Fill every section. Keep it under a page; link to longer material rather than pasting it.
3. Set frontmatter `status: proposed`, `title: ADR-NNN <Title>`, `date: YYYY-MM-DD`, `deciders: [names]`.
4. Open a PR. At least one other teammate reviews. Merge = `status: accepted` (edit the
   frontmatter in the same PR once agreed).
5. Add the ADR to the relevant `context/` note as a relation (`- implements [[ADR-NNN Title]]`)
   so the graph connects.

## Status lifecycle

```
proposed ──► accepted ──► deprecated        (no longer applies, nothing replaces it)
    │            └───────► superseded by ADR-MMM   (a newer ADR replaces it)
    └──► rejected                                  (kept for the record; never delete)
```

- Only `status: accepted` ADRs are authoritative in the trust order.
- Never edit the body of an accepted ADR to change its meaning — write a new ADR that supersedes
  it and set `superseded_by: ADR-MMM` on the old one. Typos and links may be fixed in place.
- Never delete an ADR.

## Frontmatter (Basic Memory format)

```yaml
---
title: ADR-002 Example Decision
type: decision
permalink: decisions/adr-002-example-decision
status: proposed            # proposed | accepted | rejected | deprecated | superseded
date: 2026-09-22
deciders: [Alex Tester]
supersedes:                 # ADR-NNN, optional
superseded_by:              # ADR-MMM, optional
tags: [adr, <topic>]
---
```

Body sections: Context → Decision → Consequences → Alternatives considered → Observations →
Relations. The `## Observations` and `## Relations` sections are what Basic Memory indexes —
put the one-line facts and the links there, even if they repeat the prose.

## Observations
- [rule] Only `status: accepted` ADRs are authoritative ^b0e289
- [rule] Agents never edit `decisions/`; they write `PROPOSAL - ADR-…` notes to `log/proposals/` ^cf00f1
- [rule] Supersede, never rewrite; never delete ^e3c531
- [rule] Numbering is sequential, zero-padded to three digits ^e7e8fe

## Relations
- relates_to [[Conventions]]
- relates_to [[ADR-001 Shared Memory System]]
