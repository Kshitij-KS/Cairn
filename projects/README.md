---
title: Projects Index
type: process
permalink: projects/projects-index
tags: [projects, workstreams, process]
level: L0
confidentiality: internal
created: 2026-09-25
updated: 2026-09-27
---
# projects/ — one file per active workstream

A **workstream** is something with a goal, an owner and an end: a project, an epic, a migration,
a procurement, a research spike. This folder holds the company-level status card for each one.
Agents **may write here freely** (create and update), because status is not a company fact —
it is a snapshot with a date on it.

Deep, project-internal knowledge (architecture, gotchas, vocabulary) does **not** go here — it
goes into that project's own `memory/` folder (created with `scripts/new-project-memory.*`).
The card here links to it.

## File format

File: `projects/<workstream-slug>.md` — one file, updated in place; never create a second card
for the same workstream. Archive by setting `status: done` or `status: dropped`; do not delete.

```markdown
---
title: <Workstream Name>          # Title Case, unique — other notes link to it with [[Workstream Name]]
type: workstream
permalink: projects/<workstream-slug>
status: active                    # active | paused | done | dropped
owner: <person>
started: YYYY-MM-DD
updated: YYYY-MM-DD               # bump on every edit
repo: <org/repo or path>          # if it has one
memory: <repo>/memory             # its project-memory folder, if any
tags: [workstream, <topic>]
---

# <Workstream Name>

<Two sentences: goal and what "done" means.>

## Observations
- [status] <one line, dated: what is true now>
- [milestone] <date> — <what shipped>
- [blocker] <what is blocking, who can unblock>
- [decision] <decisions taken inside this workstream that others must know> (or link an ADR)
- [risk] <known risks>
- [next] <the next concrete step>

## Relations
- owned_by [[<Person>]]           # only if a person note exists; otherwise name in frontmatter
- relates_to [[Product]]          # at least one relation to a context/ note
- depends_on [[<Other Workstream>]]
- implements [[ADR-NNN Title]]
```

## Rules
- Keep the `[status]` line current; agents update it after finishing work that changes it.
- Observations are facts with dates, not narrative. No task lists, no progress diaries.
- When a workstream produces a durable company fact (a new vendor, a changed owner, an
  architecture change), that fact is proposed into `context/` via `log/` — the card only links.

## Observations
- [rule] One file per workstream; update in place; archive via `status`, never delete ^340bf4
- [rule] Cards hold dated status, not project internals; internals live in `<repo>/memory/` ^ac3682

## Relations
- relates_to [[Conventions]]
- relates_to [[Core]]
