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
- **Pulse.** Recent activity: level, whether a person or an agent wrote it, how many files, and
  which published notes it touched. Code paths and commit messages are never published.
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
be replaced with `public_title:` or hidden with `publish_title: false`; such a note is published
under an opaque id and path, and relations to it still resolve.

The generator refuses to write a public build if any note has no `confidentiality` field. The
public file has a closed schema, and `build_atlas.py --verify graph.json` rebuilds it from the
notes (by default) and fails on any difference, any unknown key or wrongly typed value, any
duplicate key, publication settings the policy does not grant, and any trace of a restricted note or
a withheld title. `--full` produces the unredacted build for local use; it is never deployed.

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

An observatory instrument: the memory is a sky you fly into, and the chrome around it is glass and
hairline, so the map is always the brightest thing on the page. Dark (night) by default when the
system is dark, with a light (day) theme; the toggle wipes between them in a circle from the button.

- **Light is information.** A note is a lit mark in its level's colour with a soft bloom and a small
  highlight; a region is a disc lit from its centre, its contents drawn inside it as tissue, its level
  mix as a gauge on the rim. The ground is a quiet gradient over a faint dot grid (an instrument's
  graticule, not a starfield).
- **One signal colour** (orchid) means "this is what you are looking at": the selection, its
  reticle, the edges it touches (drawn marching), the ripple a click leaves.
- **Glass** for everything that floats over the map (controls, key, card, hover card, search), with
  a hairline edge that catches light.
- **Type.** Instrument Serif for names and headings, Instrument Sans for the interface, IBM Plex
  Mono for ids, counts and paths. Every label measures 11px (notes) or 14px (regions) on screen.

Motion is physical and always optional. Springs for what you touch (a mark swells under the
pointer, segmented controls move a thumb, the card and dialogs spring in); a long ease for the
camera; each level arrives in a staggered wave; the briefing arrives a word at a time; numbers count
up. One continuous motion is an argument rather than decoration: light runs along every dependency
from the note relied on to the notes that rely on it, the direction a planning change cascades.
`prefers-reduced-motion` stops all of it, and the Motion switch does the same on request; the page
is complete at rest.

| Level | Meaning | Night | Day |
|---|---|---|---|
| L0 | observation | `#6EA8FF` | `#2F6FEB` |
| L1 | project planning | `#3DDC97` | `#0E9F6E` |
| L2 | strategy | `#FFB547` | `#C27400` |
| L3 | governance | `#FF7A6E` | `#D9463B` |

| Role | Night | Day |
|---|---|---|
| ground | `#070A12` | `#F4F3EF` |
| raised surface | `#121A2A` | `#FFFFFF` |
| primary text | `#EEF1FA` | `#11131F` |
| secondary text | `#B4BCD3` | `#3D4257` |
| rule | `#232B40` | `#DCDCE4` |
| signal | `#D59CFF` | `#8E3BD6` |
| needs attention | `#F6C453` | `#B7791F` |

Search is also a command bar: `/` or Ctrl/Cmd+K focuses it, arrow keys move through the results,
Enter opens one, and the matched text is marked.

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
