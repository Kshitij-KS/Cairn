---
title: Significance Rubric
type: governance
permalink: governance/significance-rubric
level: L3
confidentiality: internal
tags: [governance, significance, storage, canonical]
created: 2026-09-25
updated: 2026-09-27
---
# Significance rubric — what gets stored, and in how much detail

The failure mode this exists to prevent is a memory that fills with transcript. A store that
records everything is a store nobody reads, and an agent that reads it wastes its context on
yesterday's chatter instead of today's constraints. So the default is **do not store**, and the
burden is on the writing agent to justify an exception.

This is the **significance** axis. It answers *whether* something is stored. It does not answer
*who may store it* — that is the **level** axis in `ACCESS.md`, and the two are independent.

## The one test

> **Would a teammate, or an agent, make a worse decision in a month without this?**

If no: do not write it. Silence is the correct output of most turns.

## The four tiers

| Tier | Name | Stored as | Who writes it | Where |
|---|---|---|---|---|
| **A** | decision | full note: context, decision, consequences, alternatives, author, date | a human with the level's role, after a proposal | `decisions/**`, `context/**` |
| **B** | signal | short attributed note, ≤ 80 lines | agent or contributor, automatically | `log/journal/**`, `projects/**` |
| **C** | summary | one line: date, author, level, files, message | the CI bot, from the commit | `log/CHANGELOG.md` |
| **D** | discard | nothing | — | — |

Every change produces **at least** a Tier C line, because the changelog is generated from commits
and therefore cannot be forgotten. Tier C is the floor, not a decision anyone makes.

## Tier A — a decision or an ideological change

Write a proposal when the answer to any of these is yes:

- Would reversing this cost more than a day?
- Does it change what we believe, not just what we know? (a plan, a direction, a principle)
- Does it commit money, a vendor, or a public interface?
- Does it change who owns something?
- Does it contradict a note that already exists?

An agent **never writes Tier A directly.** It writes `log/proposals/PROPOSAL - <what>.md` containing
the exact text it believes belongs in canon plus the reason, and a human with the role promotes it.
That promotion is the moment the change becomes real, and it is a reviewed commit with a name on it.

**Worked examples.** "Card payments move to the new provider after the trial" — Tier A,
L2, steward. "We keep the paid search vendor and sign the annual contract" — Tier A, L2, because it
commits money and reverses a standing decision. "Single sign-on is P0 and passing the security
review is its exit gate" — Tier A, L1, that project's maintainer.

## Tier B — a signal worth keeping

This is where **code-level truth** lives, and it is deliberately generous: these notes cost one
short file and save hours. Write one when you learned something durable and non-obvious:

- a corrected assumption — documented behaviour that turned out to be false, and what is actually true
- a gotcha that cost real time, with the symptom someone would search for
- a dead end: what was tried, why it failed, so nobody retries it
- a real constraint discovered in the code or the environment
- a workstream status change worth a teammate's attention

**Worked examples.** "The nightly export runs in UTC, so dates near midnight shift a day" —
Tier B, and worth more than most Tier A notes because it silently misleads. "`uv tool install
basic-memory` fails on Python < 3.12; pass `--python 3.12`" — Tier B. "Kiro ignores symlinked
skills, so the copies must be regenerated" — Tier B. "The staging database lags production by an
hour" — Tier B, and a good candidate for later promotion to L2 context.

Keep it short. Title, one-paragraph summary, the observations, at least one relation. Eighty lines
is the ceiling and most notes should be fifteen.

## Tier D — do not store

Never write, even when the turn felt productive:

- progress narration: "I read the file, then edited it, then ran the tests"
- anything re-derivable from the code, the diff or `git log` — link to the commit instead
- restating a doc that already exists in the repo — link it
- task chatter, apologies, plans for the next turn
- a second note saying what an existing note already says (the guard rejects a journal entry that
  is ≥ 85% similar to one from the last 30 days — fix the original instead)
- anything on the never-store list: credentials, keys, tokens, PII, compensation, private DMs

## How the automatic capture works

Storage is triggered by the agent's `Stop` hook, not by remembering to ask.

The **default detector is deterministic and free** — no model call, no token cost. It reads the
hook's input and the working tree, and raises a flag when the turn shows a significance marker:
a dependency, config, workflow or schema file changed; a design or decision document was
touched; more than a threshold number of files moved; or the assistant's own closing message
contains decision language ("we decided", "switched to", "root cause", "turns out", "instead of",
"deprecated", "now owns"). If a marker fires and no memory note was written this session, the hook
blocks the stop **once** and tells the agent exactly what to write and where. Once per session, so
it is a nudge rather than a nag.

A **model-judged detector** is possible for teams that want better judgement than keywords: a
`type: "prompt"` Stop hook that sends the rubric plus the turn's data to a small model, which
returns `{"ok": false, "reason": "..."}` to make the agent write, or `{"ok": true}` to let it stop.
It is **not shipped**, because it costs tokens on every turn end and Cairn is meant to run at $0.

Both detectors are advisory. Neither can force a good note; they can only make the absence of one
visible at the moment it matters.

## Observations
- [rule] Default is do not store; the test is whether a teammate would decide worse in a month without it ^dc3c28
- [rule] Tier A (decisions, ideological change) is written by a human with the role, from an agent's proposal ^3724d6
- [rule] Tier B (code-level signal) is written automatically by agents and merges without review ^7df37d
- [rule] Tier C is one changelog line per commit, generated by CI — the floor nothing can fall below ^29d042
- [rule] Tier D is discarded: progress narration, anything re-derivable from code or git, duplicates ^ee107c
- [rule] A journal note ≥85% similar to one from the last 30 days is rejected; update the original ^c2cf02
- [rule] The default significance detector is deterministic and costs nothing; the model-judged one is opt-in ^c0f599
- [constraint] Journal notes are capped at 80 lines ^e0f9ba

## Relations
- part_of [[Cairn]]
- relates_to [[Access Model]]
- relates_to [[Log Folder Rules]]
- implements [[ADR-002 Memory Governance And Access Tiers]]
