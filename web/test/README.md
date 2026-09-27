# Front-end checks

```bash
cd web/test && npm install
npm test          # 110 assertions across four corpus sizes, plus 9 negative tests
npm run shots     # render each depth to SVG, then rasterise and LOOK at them
```

`suite.mjs` runs against four fixtures — the template's own notes plus synthetic corpora at 120, 1,020 and
3,020 notes. Generate the synthetic ones with `tools/gen_fixture.py` (see below); the paths are at
the bottom of `suite.mjs`.

## What these protect

1. **The caps.** At every depth, in both arrangements, at all four sizes: at most 9 groups and 32
   notes, zero collisions among the labels actually drawn.
2. **Type is camera-independent.** Every label measures exactly 11px or 14px *on screen* whatever
   the camera scale. This is the most valuable check here: SVG scales text with its ancestors, and
   before this assertion existed the whole suite was green while every label rendered at three
   times its intended size.
3. **Redaction.** No withheld body, no summary line above `publication.brief_levels`, and no commit
   message reaches the DOM. It scans `document.body.textContent`, not the data.
4. **Reduced motion** renders and navigates.
5. **The gates can fail.** `negative.mjs` feeds a cluster claiming 200 members and asserts the
   client still draws at most 32; it also asserts the label-thinning pass parks *some* labels at
   density, because a legibility check that runs on a view with no labels passes while asserting
   nothing.

## Two standing rules

**Every check asserts that it reached something.** A label check on a view with no labels asserts nothing, so each one also checks it saw at least one.

**Look at the screenshots.** `npm run shots` exists because
this suite has been green while the screen was a mess. jsdom cannot see text metrics, blend modes
or frame rate; it can only see what you told it to measure.

## Fixtures

`fixtures/graph.json` is the template's own notes (`fixtures/graph.full.json` is their unredacted build, the privacy oracle's source). The three synthetic ones were produced by

```bash
python3 tools/gen_fixture.py 100  /tmp/n120    # ~120 notes
python3 tools/gen_fixture.py 1000 /tmp/n1020
python3 tools/gen_fixture.py 3000 /tmp/n3020
# then in each: git add -A && git commit -qm fixture && python3 scripts/build_atlas.py
```

They are committed so the suite runs anywhere without a generation step. Regenerate them whenever
`build_atlas.py` changes its schema.
