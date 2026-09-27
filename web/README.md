---
title: Memory Atlas Readme
type: guide
permalink: web/readme
level: L3
confidentiality: internal
tags: [dashboard, vercel, deploy]
---

# Memory Atlas

A map of the team's memory for people who are not going to open a terminal. It shows what the
memory holds, what changed, and what is waiting on someone. Design notes and the reasoning behind
it are in `SPEC.md`.

## Run it locally

```bash
uv run -q --script scripts/build_atlas.py        # writes web/data/graph.json, redacted
python -m http.server -d web 8080                # then open http://localhost:8080
```

Opening `index.html` straight from disk will not work, because browsers block `fetch` on
`file://`. The page says so if you try.

To read the note contents as well, generate the unredacted build:

```bash
uv run -q --script scripts/build_atlas.py --full  # writes web/data/graph.full.json
cp web/data/graph.full.json web/data/graph.json    # local only, never commit this
```

`web/data/graph.full.json` is listed in `.gitignore`. Keep it that way.

## What is published and what is not

The public build is driven by each note's `confidentiality` field, so redaction follows the same
marking the access rules use.

| Marking | On the published site |
|---|---|
| `open` | everything, including the note text |
| `internal`, the default | title, level, author, dates, tags, links, a count of facts by category, and a one line summary for observation-level (L0) notes only |
| `restricted` | nothing. The note and its links are absent |

Commit messages are withheld too, because a message like `promote: switch payments to the new
provider at 1.9% per charge` carries exactly what the note bodies are holding back.

The generator refuses to write a public build if any note has no `confidentiality` field, since
the safe reading of an unmarked note is "do not publish". CI repeats the check after the build
and fails the run if a body or a commit message got through.

## Deploy to Vercel

1. Push the repository to GitHub.
2. In Vercel, import the repository and set **Root Directory** to `web`. Leave the framework as
   Other and the build command empty. The site is static.
3. Deploy. Vercel serves `index.html` and rebuilds on every push.

`web/vercel.json` sets a content security policy limiting scripts to this origin and cdnjs,
sends `X-Robots-Tag: noindex` so the page stays out of search results, and marks
`data/graph.json` as always revalidate so a deploy is never served from a stale cache.

`.github/workflows/atlas.yml` regenerates `web/data/graph.json`. It is run by hand (Actions -> atlas)
while automatic publication is paused; restoring its push trigger makes the map never staler than
the last merge. The header shows the commit it was built from and
turns amber past two days, which is how you notice the rebuild stopped running.

## Public or private hosting

Decide this for your team. A public URL with `noindex` stays out of search results but anyone with
the link can read it; the redaction above is what makes that defensible: structure and attribution
are visible, the text is not. If you want the full text on a shared URL, put an access proxy (for
example Cloudflare Access) in front of the domain and publish the unredacted build there instead.

## Observations
- [rule] The published build is redacted by each note's `confidentiality` field; unmarked notes block the build
- [rule] `web/data/graph.full.json` is unredacted and must never be committed or deployed
- [fact] Vercel serves the `web` directory as a static site with no build step
- [fact] The atlas workflow (run by hand while automatic publication is paused) rebuilds the map and fails if a note body or commit message reaches the public file
- [decision] The published build is redacted; an access proxy is the route to a private full-text version

## Relations
- part_of [[Cairn]]
- depends_on [[Access Model]]
- relates_to [[Memory Atlas Spec]]
