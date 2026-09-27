---
title: Memory Atlas Spec
type: spec
permalink: web/spec
level: L3
confidentiality: internal
tags: [dashboard, visualization, spec]
---

# Memory Atlas - spec

The Memory Atlas is a static web page that shows a Cairn memory as a map: what the memory knows,
what changed, and what is waiting on a person, in one screen and without a terminal.

## Why it exists

The memory's governance rituals (triaging proposals, working down a cascade list, noticing an
unfilled placeholder) are otherwise CLI commands. Rituals that live only in a terminal stop
happening for the people who are not at one, and then the memory rots: proposals pile up,
`review_needed` stamps go stale, placeholders stay unfilled. The page is the surface that keeps the
governance loop visible.

**Success metric:** the open-proposal queue's median age stays under 7 days. It measures whether the
loop is alive, which page views would not.

## What it shows

- **The map.** Every public note, grouped by area or by time (two arrangements; the page morphs
  between them). Colour is the level, size is the number of facts, fading is age. Selecting a note
  shows its detail and highlights what depends on it: exactly what `memory_guard.py cascade` would
  stamp if it changed.
- **Briefing line.** The conclusion in words: "Three proposals are waiting, the oldest for six days.
  Two notes need re-reading."
- **Since you last looked.** The last visit time is kept in this browser (localStorage) and used to
  mark what is new. It is per browser, and the first visit says so.
- **Queue.** Open proposals and notes carrying `review_needed`, each with its age.
- **Health.** Orphan notes, unfilled `TODO` placeholders, stale notes, unresolved relations. Each
  item links to the file.
- **Pulse.** Recent activity: level, whether a person or an agent wrote it, files touched. Commit
  messages are withheld by default.
- Notes are addressable: the selected note is in the URL.

Out of scope: editing anything from the page (the write path is the guard; routing writes around
it would defeat the governance layer), authentication, natural-language query.

## Data pipeline

`scripts/build_atlas.py` (standard library only) parses the notes with the guard's own parsers, so
the page can never disagree with the enforcement engine; walks `git log` for activity (capped at
200 entries); computes the layout; and writes one `web/data/graph.json` (schema 4). The page is
`index.html` + `app.js` + `style.css`, with d3 v7 from a CDN. No build step; host it anywhere
(`vercel.json` is included).

Publication is manual (Actions -> atlas), and the workflow runs the redaction tests first.

## Redaction: the load-bearing feature

The page is meant to be shareable while the repository is private, so what it may show is decided
by each note's `confidentiality:` field and `governance/roles.json` `publication`:

| `confidentiality` | On the public build |
|---|---|
| `open` | everything: title, observations, relations, body |
| `internal` (default) | title, level, dates, tags, relations, observation counts by category, and a brief (the first sentence of the summary, capped at 160 characters) **only for levels in `publication.brief_levels`** (default `["L0"]`) |
| `restricted` | nothing: the note, its edges and every trace of its path are absent |

The brief is limited by level because a note's first sentence is often its substance: for a
strategy note, publishing it undoes the redaction beside it. Commit messages are withheld because a
message like `promote: switch payments to the new provider at 1.9% per charge` is a leak wearing a
changelog's clothing. Authors are withheld when `publish_authors` is false. A sensitive title can
be replaced with `public_title:` or hidden with `publish_title: false`.

The generator refuses to write a public build if any note has no `confidentiality` field. The
public file has a closed schema, and `build_atlas.py --verify graph.json --against-source` rebuilds
it from the notes and fails on any difference, any unknown key, any duplicate key, and any trace of
a restricted note. `--full` produces the unredacted build for local use; it is never deployed.

## Level of detail

About 60 freely placed 11px labels fit a typical pane, and a note's label anchored under its own
mark fits far fewer. That is a fact about type, not about rendering technology, so canvas or WebGL
would not move it. The map therefore shows **one depth at a time**, capped at every level:

- at most **9 groups** and at most **32 notes** per view (`GROUP_CAP`, `CAP` in `build_atlas.py`);
- growth adds depth, not density: oversized groups split by real keys (folder, month, week, day),
  and a level holding exactly one thing is spliced out;
- the time stream rolls months up into years once there are more than ten.

Consequences, taken deliberately:

- **Layout is computed in the builder and frozen into the data.** No simulation in the browser, no
  load freeze, and the map is identical for everyone, so "that cluster on the left" means the same
  thing to every teammate.
- **Every group disc contains its members,** so going deeper is a camera move into a real place.
- **The camera moves; the layout never does.**
- **SVG stays,** because the view never draws more than a few hundred elements.
- **Text never scales with the camera.** Everything meant to be read lives in a counter-scaled
  group; every label measures 11px or 14px on screen at any zoom.

## Look

An engraved plate: ink on paper, drawn with real linework. The page follows the system theme
(light "bone paper" or a dark plate) and remembers a manual choice. `web/style.css` holds the
tokens and is the source of truth; this table mirrors it.

- Connections are the substance: they carry weight and taper; dependencies are heavier ink.
- Depth comes from four discrete paper steps and a hard hairline edge, never from a gradient or a
  glow.
- One signal colour. Vermilion means "this is the thing you are looking at" and nothing else.
- Level colour is a legend: four inks that stay subordinate to the signal.
- No motion that is not answering something the person just did; `prefers-reduced-motion` removes it.

| Level | Meaning | Light | Dark |
|---|---|---|---|
| L0 | observation | `#3A5A86` | `#7FA3D6` |
| L1 | project planning | `#3F7247` | `#7FB185` |
| L2 | strategy | `#8A621A` | `#D9A441` |
| L3 | governance | `#8C3A2C` | `#DC7A63` |

| Role | Light | Dark |
|---|---|---|
| ground (`--paper-0`) | `#E7E1D2` | `#14130F` |
| primary ink | `#181611` | `#F2EEE2` |
| signal | `#C03A22` | `#E85C3C` |
| needs re-reading | `#91651C` | `#D9A441` |

Spectral for the wordmark and headings; the system sans for interface text; monospace only for
commit hashes and file paths.

## States and accessibility

Written before layout: first-time empty (onboarding, not an error); empty after filtering (says why,
offers to clear); loading (a skeleton of the real layout); refreshing (never blanks what is on
screen); data older than 48 hours (the build stamp turns amber); fetch failure (names the command
that fixes it); an out-of-date data schema (explains itself instead of drawing nothing); arriving by
deep link; nothing waiting (says so plainly).

Every note is reachable by keyboard and activates on Enter or Space; tabs move with arrow keys;
dialogs trap and return focus; live regions announce the briefing; focus shows on the mark, not on
a group's bounding box.

## Tests (`web/test`)

`npm test` runs the page in jsdom against the template's own notes and three synthetic corpora
(about 120, 1,020 and 3,020 notes, from `tools/gen_fixture.py`):

- the caps hold **at every level**, in both arrangements, at every size, with no collisions among
  the labels actually drawn;
- every label measures 11px or 14px on screen whatever the camera scale;
- a privacy oracle scans the rendered page (`document.body.textContent` and markup) for every
  string the public build withheld;
- reduced motion renders and navigates;
- `negative.mjs` proves the checks can fail: an overfilled cluster is still capped, the label
  thinning pass really parks labels, and a deliberately leaked string is caught.

What the suite also guards against, from defects found while building it:

- every check asserts that it reached at least one note or marker, so an empty view cannot pass;
- the caps are asserted at every level of the tree, not only the top;
- elements caught mid-exit are revived when a new view reuses them;
- a note's visibility never depends on a transition finishing;
- label collisions are measured in screen coordinates, not world coordinates;
- `npm run shots` renders each depth to SVG, because jsdom cannot see what a person sees.

## Not verified

jsdom has no layout engine and no SVG geometry, so `getBoundingClientRect`, path lengths and CTMs
are stubbed, and label widths come from a per-character estimate rather than real text metrics.
Frame rate, the feel of the camera, font loading, blend modes, touch targets and pinch-zoom have
not been measured by the suite. Look at the page in a real browser after any visual change.

## Open questions

| Question | Owner |
|---|---|
| Are any note titles themselves sensitive? The public build shows them unless `public_title` or `publish_title: false` is set | owner |
| Where to host the page, and whether it needs its own domain | owner |
| Should `open` be promoted deliberately (a publication decision) or stay rare? | stewards |

## Relations
- depends_on [[Access Model]]
- relates_to [[ADR-002 Memory Governance And Access Tiers]]
- relates_to [[Cairn]]
