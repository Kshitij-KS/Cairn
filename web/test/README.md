# Front-end checks

```bash
cd web && npm ci
npm test                # sky.mjs + suite.mjs + negative.mjs, in jsdom, against the BUILT page
npm run test:browser    # browser.mjs, in a real Chrome (CHROME_PATH, or the usual install paths)
npm run check-build     # web/index.html and vercel.json are exactly what web/app builds to today
```

Everything runs against `web/index.html`, the file that ships, not the sources. The fixtures are
the template's own notes (`graph.json`, with `graph.full.json` as its unredacted build for the
privacy oracle), a redacted corpus (`redacted.json` / `redacted.full.json`), and synthetic corpora
of about 120, 1,020 and 3,020 notes.

## What these protect

1. **Nothing overlaps.** In the sky: no two stars closer than two of the largest dots, and no name
   touching another name or covering another star, at a distance, zoomed in, in focus and by time
   (jsdom, from the engine's own geometry; `browser.mjs` repeats it with real text widths). In the
   grid: every chip and card measured in a real browser, with every group opened, at 1440px and 390px.
2. **The lineage is exact.** What stands left of a chosen note is exactly what it relies on, right
   is exactly what relies on it, below is exactly what it relates to, computed from the raw edges
   by the test, never through the app's own model.
3. **The partition.** In the grid, every note is shown once or counted in its group's "+N more".
4. **Redaction.** No withheld body, no summary line above `publication.brief_levels`, no withheld
   title and no commit message reaches the page, text or markup, in any tab.
5. **The deployed CSP.** The page runs under the exact header `vercel.json` sends, with no violation.
6. **The gates can fail.** `negative.mjs` breaks each invariant on purpose and asserts the check
   goes red.

## Standing rules

**Every check asserts that it reached something** (a label check on a view with no labels asserts
nothing), and **an unrun check says so**: `browser.mjs` prints SKIP when there is no Chrome, and
`tools/run_tests.sh` counts a missing `npm ci` as a failure.

**Look at it.** jsdom cannot see a picture. After a visual change, open the page in a browser.

## Fixtures

```bash
python3 tools/gen_fixture.py 100  /tmp/n120    # ~120 notes
python3 tools/gen_fixture.py 1000 /tmp/n1020
python3 tools/gen_fixture.py 3000 /tmp/n3020
# then in each: git add -A && git commit -qm fixture && python3 scripts/build_atlas.py
```

They are committed so the suite runs anywhere without a generation step. Regenerate them whenever
`build_atlas.py` changes its schema.
