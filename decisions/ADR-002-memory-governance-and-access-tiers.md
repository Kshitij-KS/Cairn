---
title: ADR-002 Memory Governance And Access Tiers
type: decision
permalink: decisions/adr-002-memory-governance-and-access-tiers
status: accepted
date: 2026-09-22
deciders: [Cairn maintainers]
supersedes:
superseded_by:
level: L2
confidentiality: internal
created: 2026-09-22
updated: 2026-09-27
tags: [adr, governance, access, roles, significance, security]
---
# ADR-002 Memory Governance And Access Tiers

> Extends ADR-001, which stays `accepted` and authoritative for the store, the MCP layer and the
> sync. This ADR replaces only how writes are governed.

## Context

A shared memory governed by a sentence in a Markdown file, such as "agents may propose changes to
`context/` and `decisions/` but must not edit them directly", is governed by convention only.

That is a convention, not a control. An agent that ignores it simply writes. A teammate in a
hurry simply writes. Nothing measures whether a stored note was worth storing, nothing records
who actually wrote it beyond the git author of a batch commit, and nothing notices when a
strategy change makes a dozen downstream notes wrong. For a small team sharing one memory across
several AI clients, three failure modes follow: the memory fills with transcript until nobody reads
it; company strategy drifts because an agent "helpfully" edited it mid-task; and a plan changes
while every note that depended on it silently keeps asserting the old one.

Two requirements pull in opposite directions and must both be met. Recording how the code
actually behaves has to be **frictionless** — that knowledge is cheap to write and expensive to
lose, and any ceremony means it never gets written. Changing what we believe has to be
**deliberate** — that is cheap to write and expensive to get wrong.

## Decision

Govern memory on **two independent axes**, and enforce them in code.

**Level** — what kind of knowledge, deciding who may change it and whether the change cascades.
L0 observation (code-level facts, gotchas, corrected assumptions) writable by any agent or
contributor without review. L1 project planning, restricted to that project's maintainer. L2
ideation and strategy, restricted to stewards. L3 governance — the rules, hooks, CI and scripts
— restricted to owners. **An agent is capped at L0 regardless of who is driving it:** the
human's authority applies when the human commits.

**Significance** — whether a change is worth storing at all. Tier A decisions are written by a
human from an agent's proposal. Tier B signals are written by agents automatically. Tier C is
one generated changelog line per commit, which every change gets, so nothing is lost even when
nothing is elaborated. Tier D is discarded.

Enforcement is one engine, `scripts/memory_guard.py`, invoked identically by the local sync
hook and by CI, so a check cannot pass on a laptop and fail in the pipeline. It enforces the
level and role, stamps attribution **from the git identity rather than from what the note
claims**, validates frontmatter and the ADR lifecycle, blocks credential shapes, rejects notes
containing instructions aimed at future agents, rejects journal entries ≥85% similar to a recent
one, and requires every note to carry at least one relation.

Because the notes form a graph, a change at L1/L2/L3 **cascades**: the guard walks dependency
edges (`implements`, `depends_on`, `part_of`, `supersedes` — not `relates_to`) and stamps each
dependent note with `review_needed`, agents reading a stamped note must say so and prefer the
note that changed, and CI opens one issue listing the affected set. This is what "a planning
change updates the entire context" means mechanically. Following `relates_to` is rejected: every
note has several, so it would flag every note, which is the same as flagging none.

The real boundary is the remote: branch protection plus `.github/CODEOWNERS` plus a required
`memory-gate` check. L0 pull requests that pass every check merge automatically; everything
above waits for the review GitHub enforces. (As built, auto-merge is off until the gate has been
exercised on GitHub; every pull request waits for review. See ARCHITECTURE.md section 13.) Local guards catch mistakes; only the remote stops
determined misuse, and `governance/ACCESS.md` says so in those words.

## Consequences

- Recording a code-level fact costs nothing: write, and it merges without a human. That is the
  behaviour we most want, so it is the behaviour with the least friction.
- Strategy and plans cannot be changed by an agent at all, including one launched by the owner.
  Occasionally this will be annoying — the escape hatch is a proposal, which takes one extra
  note and produces a better record than the direct edit would have.
- Attribution becomes trustworthy rather than decorative: `author` is the creator, `updated_by`
  the last editor, both written from git and re-verified in CI against the commit author.
- Every change is traceable three ways: the changelog line, the commit with its `Sync-Actor` and
  `Sync-Agent` trailers, and `memory_guard.py audit`.
- Cost stays $0. The significance detector is deterministic — keyword and file-pattern based, no
  model call. A model-judged variant is possible but not shipped, because it would bill
  tokens on every turn end.
- New costs: a JSON policy file to keep current, one more script in the hook path, and a
  five-minute setup (teams, branch protection) that must actually be done or CODEOWNERS is
  decoration.
- The guard is itself L3 and runs on every teammate's machine, which makes `scripts/` and the hook paths
  the highest-value target in the repo. They are owner-only and review-gated for that reason.
- **Revisit when:** the team passes ~15 people and per-project maintainers outgrow one JSON
  file; or the deterministic detector proves too noisy or too quiet in practice, measured
  against what actually got stored over a month.

## Alternatives considered

| Option | Why not |
|---|---|
| Keep convention-only rules | an instruction in Markdown is not a control, and the cost of a silent strategy edit is paid long after it happens |
| Separate repos per access level | access control by repo permission is genuinely enforced, but it fragments the graph — relations cannot cross repos, and the graph is the reason we chose this store. Used only for `restricted`, where the tradeoff is worth it |
| Branch protection alone, no local guard | the author discovers the violation minutes later in CI, after the agent has moved on. The local guard fails at the moment of the mistake, with the fix in the message |
| A model call to classify every write | better judgement, non-zero cost on every turn, and non-deterministic — the same turn could store or not store. Kept as an opt-in |
| Store everything, filter at read time | shifts the cost to every future read and to every agent's context window, forever, to save one decision now |

## Observations
- [decision] Memory is governed on two independent axes: level (who may change it, does it cascade) and significance (is it worth storing) ^0954a2
- [decision] L0 observation is writable by agents and contributors with no review; L1 needs a maintainer, L2 a steward, L3 an owner ^14bf57
- [decision] An agent is capped at L0 regardless of the role of the human driving it ^9d76bd
- [decision] Enforcement is one engine, scripts/memory_guard.py, run identically by the local hook and by CI ^97853f
- [decision] Attribution is stamped from the git identity and re-verified in CI against the commit author ^b762f7
- [decision] A change at L1/L2/L3 stamps review_needed on notes that depend on it (dependency edges only, depth 1, capped at 8) ^0225c3
- [decision] The significance detector is deterministic and free; the model-judged variant is opt-in ^796388
- [constraint] Local guards are advisory; branch protection plus CODEOWNERS is the only real enforcement ^5fe814
- [risk] scripts/ and the hook paths execute code on every teammate's machine, so they are owner-only and review-gated ^46879d
- [risk] A memory note is a prompt-injection surface, so notes are data and the guard rejects imperatives aimed at agents ^170468
- [revisit] Team beyond ~15 people, or measured evidence that the detector is too noisy or too quiet ^a1826c

## Relations
- relates_to [[ADR-001 Shared Memory System]]
- implements [[Access Model]]
- implements [[Significance Rubric]]
- relates_to [[Conventions]]
- relates_to [[Roles]]
