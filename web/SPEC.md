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

- **The sky** (the main view). Every public note is a star, grouped into a cluster per area or per
  month (two arrangements; the stars fly between them). Colour is the level (or, on request, how
  recently it changed), size is the number of facts. Selecting a star is a focus: the camera flies
  to it and its relations step out of their clusters to stand around it, what it relies on to the
  left, what relies on it to the right, see-also below. That left/right split is exactly what
  `memory_guard.py cascade` would stamp if it changed.
- **The grid** (the plain alternative). The same notes as cards of labelled chips, one card per
  area or month, and a column lineage view for one note.
- **Briefing line.** The conclusion in words: "Three proposals are waiting, the oldest for six days.
  Two notes need re-reading."
- **Since you last looked.** The last visit time is kept in this browser (localStorage) and used to
  mark what is new. It is per browser, and the first visit says so.
- **Queue.** Open proposals and notes carrying `review_needed`, each with its age.
- **Health.** Orphan notes, unfilled `TODO` placeholders, stale notes, unresolved relations. Each
  item links to the file.
- **Pulse.** Recent activity: level, whether a person or an agent wrote it, how many files, and
  which published notes it touched. Code paths and commit messages are never published.
- Views are addressable: the mode, the arrangement and the selected note are in the URL
  (`#area~<id>` in the sky, `#grid:area~<id>!focus` in the grid).

Out of scope: editing anything from the page (the write path is the guard; routing writes around
it would defeat the governance layer), authentication, natural-language query.

## Data pipeline

`scripts/build_atlas.py` (standard library only) parses the notes with the guard's own parsers, so
the page can never disagree with the enforcement engine; walks `git log` for activity (capped at
200 entries); and writes one `web/data/graph.json` (schema 4). The page reads only that file.

The page itself is a small React app in `web/app/` (Radix primitives in the shadcn style, Motion,
cmdk, d3 modules for the camera and packing), built by Vite into **one self-contained file**,
`web/index.html`, with every script and style inlined. That file is committed, so the site still
hosts anywhere with no build step and no server; `npm run check-build` fails if it is not exactly
what the source builds to today. The build also writes the sha256 of each inline script into the
Content-Security-Policy in `vercel.json`, so the deployed page runs those two scripts and nothing else.

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

## Nothing overlaps, by construction

The old map nested groups inside discs and opened them in place, and notes collided whenever a
group grew. The sky removes the cause instead of tuning around it:

- **Nothing expands.** Every note has one fixed home. A cluster is a sunflower (Vogel's
  phyllotaxis): note *i* sits at radius `12.5 * sqrt(i + 0.5)` on the golden angle, most connected
  first, so it is at the heart. That spiral packs points evenly; the nearest two notes are about 19
  world units apart at any size (measured: 19.3 over 3,100 points), against a largest dot of 6.5,
  so no two dots can touch. Clusters are circle-packed with room for their names.
- **Names are placed, never piled.** Every frame, names go down greedily, most important first,
  and a name goes only where it touches no other name and covers no other star. At a distance you
  read the areas; zoom in and note names appear where there is room.
- **A focus has its own geometry.** Around a chosen note, its relations stand in two bracket-shaped
  arcs and a list, spaced in screen pixels (so the room for each name is the same at every zoom),
  capped at 14 a side (8 see-also) with the rest counted and listed in the side panel. On a narrow
  screen the three become one list under the note.
- **Deterministic.** The layout is a pure function of the notes, so "that cluster on the left" means
  the same thing to every teammate, and a link lands on the same spot.

## Look and motion

Linear/Vercel-quiet chrome (neutral zinc, Geist and Geist Mono, hairline shadows instead of
borders) around a sky that is the brightest thing on the page. Dark by default when the system is,
with a light theme. Level colours are the one strong colour.

Motion follows Emil Kowalski's rules for interface animation, and cinema for the sky:

- Interface motion is fast and eased out (`cubic-bezier(0.23, 1, 0.32, 1)`), under 300ms, exits
  faster than entrances; pressing anything scales it to 0.97; popovers grow from their trigger; the
  command palette opens with no animation at all, because it is used from the keyboard.
- The camera moves with a smooth zoom (van Wijk and Nuij), so long journeys pull out a little and
  come back in, and any flight can be interrupted by grabbing the sky.
- A focus is choreographed: the camera flies in while the neighbours fly out of their clusters to
  their places, the rest of the sky steps back behind a veil, the relation curves draw on, and names
  fade in only once the notes have nearly arrived, so text never rides on a moving dot. Light runs
  along each dependency the way a change travels. Escape plays it backwards.
- The first load pulls back from close in to take in the whole sky; switching arrangement flies
  every star to its new home, left to right, and the new cluster names wait until the stars arrive.
- Ambient life (a slow twinkle, a breathing ring on notes changed this week) runs only while the
  page is visible. `prefers-reduced-motion` turns every move into a cut and stops the ambient
  motion; the page is complete at rest.

## States and accessibility

Written before layout: first-time empty (onboarding, not an error); empty after filtering (says why,
offers to clear); loading (a skeleton of the real layout); refreshing (never blanks what is on
screen); data older than 48 hours (the build stamp turns amber); fetch failure (names the command
that fixes it); an out-of-date data schema (explains itself instead of drawing nothing); arriving by
deep link; nothing waiting (says so plainly).

Every note is reachable by keyboard: `/` or Ctrl/Cmd+K opens the palette, which finds any note and
runs any action; the grid is a page of real buttons (Enter or Space), and `G` switches to it. The
sky's canvas carries a label saying so. Tabs move with arrow keys, dialogs trap and return focus,
and the briefing is a live region.

## Tests (`web/test`)

`npm test` runs the BUILT page (`web/index.html`, exactly what ships) in jsdom against the
template's own notes, a redacted corpus, a full local build, and synthetic corpora of about 120,
1,020 and 3,020 notes (`tools/gen_fixture.py`). Expected values come from the graph's raw edges,
never from the app's own code.

- `sky.mjs`: every note is a star; no two stars closer than two of the largest dots; no name
  touches another or covers a star, at a distance, zoomed in, in focus and by time; every large area
  is named; clicking a star gives exactly its lineage (left, right, below), brings it to the centre
  and names every neighbour; neighbours re-centre, Escape walks back; hiding a level removes its
  stars; with reduced motion a focus arrives at once.
- `suite.mjs` (the grid): every note is shown once or counted in its group's "+N more", before and
  after opening a group; selecting fades exactly the unrelated notes and opens no box over the map;
  the column lineage is exact; the palette, arrangement, level filter, rail counts, deep links, the
  `?data=` whitelist, and the failure states.
- Both: a privacy oracle scans the rendered page (text and markup, every tab) for every string the
  public build withheld.
- `negative.mjs` proves the checks fail when they should: a chip drawn twice or missing, a
  dependent in the wrong column, two names on top of each other, a name over a star, two stars
  crowding, and leaked strings (long and short).
- `browser.mjs` (`npm run test:browser`, needs Chrome; CI runs it) makes the checks jsdom cannot:
  real layout (with every group opened, no two chips or cards overlap and every chip is inside its
  card, at 1440px and 390px), real text widths for the sky's names, a real click choosing the star
  under the pointer, and the deployed Content-Security-Policy (the page runs under it with no
  violation).

## Not verified

The feel of the motion (timing, easing, frame rate on a slow machine) was checked by eye from
frame sequences in a headless browser, not measured. Touch gestures (pinch, pan) were not tested on
a real device. Web fonts were not loadable where the screenshots were taken, so the checks ran with
the fallback font; the name-placement check runs on real widths either way.

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
