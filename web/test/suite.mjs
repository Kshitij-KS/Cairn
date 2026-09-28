/* The GRID view (the plain alternative to the sky), driven the way a person uses it, against the
 * BUILT page at every corpus size. The sky has its own suite, sky.mjs.
 * What the page shows is compared with what the graph says, computed in harness.mjs from the raw
 * edges (never through the app's own code). Geometry, which jsdom cannot measure, is checked in
 * a real browser by browser.mjs. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  boot, settle, key, dblclick, typeInto, expectedLineage, shownLineage, sameSet, partitionProblems,
  withheldMarkers, privacyLeaks, omittedCount,
} from "./harness.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIX = (n) => path.join(HERE, "fixtures", n);
const CAP = 18;   // web/app/src/components/MapView.tsx
const COL_CAP = 10; // web/app/src/components/FocusView.tsx

let pass = 0, fail = 0;
const ok = (name, cond, detail = "") => {
  if (cond) { pass++; console.log("  PASS " + name + (detail ? "  " + detail : "")); }
  else { fail++; console.log("  FAIL " + name + "  " + detail); }
};
const $ = (doc, s) => doc.querySelector(s);
const $$ = (doc, s) => [...doc.querySelectorAll(s)];
const attr = (id) => '"' + id.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';

/** A note worth driving: one with dependencies both ways if there is one. */
function richNote(g) {
  const score = (id) => {
    const l = expectedLineage(g, id);
    return Math.min(l.reliesOn.size, l.reliedOnBy.size) * 10 + l.reliesOn.size + l.reliedOnBy.size + l.related.size;
  };
  return [...g.nodes].sort((a, b) => score(b.id) - score(a.id) || a.id.localeCompare(b.id))[0];
}

/** A column shows everything when it is short, and exactly the first COL_CAP of it when long. */
const columnOk = (shown, want) => (want.size <= COL_CAP ? sameSet(shown, want) : shown.size === COL_CAP && [...shown].every((x) => want.has(x)));

async function run(tag, file) {
  console.log("\n=== " + tag + " ===");
  const g = JSON.parse(fs.readFileSync(file, "utf8"));
  const { win, doc, errors } = await boot(file, { hash: "#grid:area" });

  // --- arrival ------------------------------------------------------------------------------
  ok("boots without an error", errors.length === 0, errors.slice(0, 2).join(" | "));
  ok("the skeleton gives way to the map", !$(doc, "[data-boot]") && !!$(doc, '[data-view="map"]'));
  ok("it read the data file it was asked for", win.__fetched[0] === "data/graph.json", win.__fetched.join());
  const stat = $(doc, "[data-stats] [data-value]");
  ok("headline numbers carry their final value from the first frame",
     !!stat && +stat.getAttribute("data-value") === g.stats.notes, (stat && stat.getAttribute("data-value")) + " vs " + g.stats.notes);

  // --- the partition: every note is shown once, or counted in a "+N more" ----------------------
  let probs = partitionProblems(doc, g);
  ok("every note is on the map exactly once, or counted in its group's +N more", probs.length === 0, probs.slice(0, 3).join("; "));
  const cards = $$(doc, "[data-group]");
  const over = cards.filter((c) => c.querySelectorAll("[data-note]").length > CAP);
  ok(`no group shows more than ${CAP} notes before it is asked to`, over.length === 0, over.map((c) => c.getAttribute("data-group")).join());
  ok("there is at least one group, and at least one chip", cards.length > 0 && $$(doc, "[data-note]").length > 0, `${cards.length} groups`);
  const folders = new Set(g.nodes.map((n) => (n.path.includes("/") ? n.path.slice(0, n.path.lastIndexOf("/")) : "")));
  ok("by area: one card per folder that holds a note", cards.length === folders.size, `${cards.length} cards, ${folders.size} folders`);

  // "+N more" opens in steps and the partition still holds after each step
  const more = $(doc, "[data-more]");
  if (more) {
    const gk = more.getAttribute("data-more");
    const count = () => $(doc, `[data-group=${attr(gk)}]`).querySelectorAll("[data-note]").length;
    const before = count();
    more.click(); await settle(win);
    const after = count();
    ok("+N more reveals more notes in that group, in place", after > before, `${before} -> ${after}`);
    probs = partitionProblems(doc, g);
    ok("the partition still holds after opening a group", probs.length === 0, probs.slice(0, 2).join("; "));
    const fewer = $(doc, `[data-fewer=${attr(gk)}]`);
    if (fewer) fewer.click();
    await settle(win);
    ok("Show fewer folds it back", count() === before);
  } else {
    ok("a corpus this small needs no +N more", cards.every((c) => c.querySelectorAll("[data-note]").length <= CAP));
  }

  // --- selecting: the rail explains it, and nothing floats over the map --------------------------
  const target = richNote(g);
  const want = expectedLineage(g, target.id);
  const chip = () => $(doc, `[data-view="map"] [data-note=${attr(target.id)}]`);
  for (let i = 0; i < 80 && !chip(); i++) {           // folded away: open groups until it is shown
    const m = $(doc, "[data-more]");
    if (!m) break;
    m.click(); await settle(win, 30);
  }
  ok("the note under test is reachable on the map", !!chip(), target.id);
  if (chip()) {
    chip().click(); await settle(win);
    ok("clicking a note selects it", chip().getAttribute("aria-pressed") === "true");
    const detail = $(doc, `[data-detail=${attr(target.id)}]`);
    ok("the rail switches to the note and names who wrote it",
       $(doc, '[data-tab="note"]').getAttribute("data-state") === "active" && !!detail && detail.textContent.includes("Who wrote it"));
    ok("no card or popover opens over the map on click",
       !$(doc, "[data-radix-popper-content-wrapper]") && !$(doc, '[role="dialog"]') && !$(doc, "[data-card]"));
    const lit = new Set([...want.reliesOn, ...want.reliedOnBy, ...want.related, target.id]);
    const wrong = $$(doc, '[data-view="map"] [data-note]').filter((el) => lit.has(el.getAttribute("data-note")) === /\bopacity-30\b/.test(el.className));
    ok("exactly the note's own relations stay lit; everything else fades", wrong.length === 0, wrong.slice(0, 3).map((e) => e.getAttribute("data-note")).join());
    ok("the address names the selection", win.location.hash === "#grid:area~" + encodeURIComponent(target.id), win.location.hash);
    const relIds = new Set($$(doc, "[data-detail] [data-rel-group] [data-id]").map((b) => b.getAttribute("data-id")));
    ok("the rail lists every relation, once", sameSet(relIds, new Set([...want.reliesOn, ...want.reliedOnBy, ...want.related])), `${relIds.size} listed`);

    // --- focus: the lineage is exactly the dependency sets ------------------------------------
    dblclick(win, chip()); await settle(win, 250);
    ok("double-click opens the focus view", !!$(doc, '[data-view="focus"]') && ($(doc, "[data-centre]") || { getAttribute: () => null }).getAttribute("data-centre") === target.id);
    const shown = shownLineage(doc);
    ok("left column is exactly what it relies on", columnOk(shown.reliesOn, want.reliesOn), `${shown.reliesOn.size} vs ${want.reliesOn.size}`);
    ok("right column is exactly what relies on it", columnOk(shown.reliedOnBy, want.reliedOnBy), `${shown.reliedOnBy.size} vs ${want.reliedOnBy.size}`);
    ok("see-also row is exactly what it merely relates to", sameSet(shown.related, want.related), `${shown.related.size} vs ${want.related.size}`);
    ok("the address records the focus", win.location.hash.endsWith("!focus"), win.location.hash);

    const nb = $(doc, '[data-lineage="right"]') || $(doc, '[data-lineage="left"]') || $(doc, '[data-lineage="below"]');
    if (nb) {
      const next = nb.getAttribute("data-note");
      nb.click(); await settle(win, 250);
      ok("choosing a neighbour re-centres on it", $(doc, "[data-centre]").getAttribute("data-centre") === next, next);
      const w2 = expectedLineage(g, next), s2 = shownLineage(doc);
      ok("...and its lineage is exact too", columnOk(s2.reliesOn, w2.reliesOn) && columnOk(s2.reliedOnBy, w2.reliedOnBy) && sameSet(s2.related, w2.related));
      ok("the trail shows where you came from", $$(doc, 'nav[aria-label="Where you have been"] button').some((b) => b.textContent === target.title));
      key(win, doc.body, "Escape"); await settle(win, 250);
      ok("Escape steps back to the previous note", $(doc, "[data-centre]").getAttribute("data-centre") === target.id);
    }
    key(win, doc.body, "Escape"); await settle(win, 250);
    ok("Escape again returns to the map, keeping the selection", !!$(doc, '[data-view="map"]') && !!chip() && chip().getAttribute("aria-pressed") === "true");
    key(win, doc.body, "Escape"); await settle(win);
    ok("Escape once more clears it", !$(doc, '[data-note][aria-pressed="true"]'));
  }

  // --- by time -------------------------------------------------------------------------------
  $(doc, '#group [data-value="time"]').click(); await settle(win, 250);
  const tcards = $$(doc, "[data-group]");
  const months = new Set(g.nodes.map((n) => { const s = (n.updated || n.created || "").slice(0, 7); return /^\d{4}-\d{2}$/.test(s) ? s : "undated"; }));
  ok("by time: one card per month (and one for undated)", tcards.length === months.size, `${tcards.length} vs ${months.size}`);
  ok("by time: every group is a month", tcards.every((c) => c.getAttribute("data-group").startsWith("time:")));
  probs = partitionProblems(doc, g);
  ok("by time: the partition holds", probs.length === 0, probs.slice(0, 2).join("; "));
  ok("by time: the address says so", win.location.hash === "#grid:time", win.location.hash);
  $(doc, '#group [data-value="area"]').click(); await settle(win, 200);

  // --- hiding a level -------------------------------------------------------------------------
  const lvl = [...new Set(g.nodes.map((n) => n.level))].sort()[0];
  const byId = new Map(g.nodes.map((n) => [n.id, n]));
  $(doc, `[data-legend] [data-level="${lvl}"]`).click(); await settle(win, 200);
  const leftover = $$(doc, "[data-note]").filter((el) => (byId.get(el.getAttribute("data-note")) || {}).level === lvl);
  ok(`hiding ${lvl} removes every ${lvl} note`, leftover.length === 0, `${leftover.length} left`);
  probs = partitionProblems(doc, g, new Set([lvl]));
  ok("the partition holds with a level hidden", probs.length === 0, probs.slice(0, 2).join("; "));
  $(doc, `[data-legend] [data-level="${lvl}"]`).click(); await settle(win, 200);

  // --- the command palette --------------------------------------------------------------------
  key(win, doc.body, "k", { ctrlKey: true }); await settle(win);
  const input = $(doc, "[data-palette] input");
  ok("Ctrl+K opens the palette", !!input);
  if (input) {
    const needle = (target.title.split(/\s+/).find((w) => w.length > 3) || target.title).toLowerCase();
    typeInto(win, input, needle); await settle(win);
    const hits = $$(doc, "[data-palette] [data-note]").map((e) => e.getAttribute("data-note"));
    const matches = (n) => [n.title, n.path, (n.tags || []).join(" "), n.brief || ""].join(" ").toLowerCase().includes(needle);
    const all = g.nodes.filter(matches).length;
    ok("the palette finds the note by a word of its title", hits.includes(target.id) || (all > 40 && hits.length === 40), `${hits.length} hits for "${needle}"`);
    ok("...and only notes that match", hits.length > 0 && hits.every((h) => matches(byId.get(h))));
    key(win, input, "Escape"); await settle(win);
    ok("Escape closes it", !$(doc, "[data-palette]"));
  }
  key(win, doc.body, "/"); await settle(win);
  ok("/ opens it too", !!$(doc, "[data-palette] input"));
  key(win, $(doc, "[data-palette] input") || doc.body, "Escape"); await settle(win);

  // --- rail counts match the queue ------------------------------------------------------------
  const open = g.queue.proposals.filter((p) => (p.status || "open") === "open").length + g.queue.review_needed.length;
  const nc = $(doc, '[data-tab="needs"] [data-count]');
  ok("the Needs-you count is open proposals plus flagged notes", !!nc && +nc.getAttribute("data-count") === open, `${nc && nc.getAttribute("data-count")} vs ${open}`);
  $(doc, '[data-tab="gaps"]').dispatchEvent(new win.MouseEvent("mousedown", { bubbles: true, button: 0 }));
  await settle(win);
  ok("the Gaps panel shows the health score", ($(doc, '[data-panel="gaps"]').textContent || "").includes("out of 100"));

  // --- privacy (oracle: the full build of the same corpus, where there is one) -----------------
  const fullPath = file.replace(/\.json$/, ".full.json");
  if (fs.existsSync(fullPath)) {
    const fullData = JSON.parse(fs.readFileSync(fullPath, "utf8"));
    const markers = withheldMarkers(g, fullData);
    ok("the privacy oracle has something to look for", markers.length > 0, `${markers.length} withheld markers`);
    if (tag === "redacted corpus") {
      ok("the redacted corpus leaves notes out, so the restricted-name check has something to test",
         omittedCount(g, fullData) >= 2, `${omittedCount(g, fullData)} omitted`);
    }
    // Open everything a person could open: every group, every tab, the help, a note.
    for (let i = 0; i < 200; i++) { const m = $(doc, "[data-more]"); if (!m) break; m.click(); await settle(win, 10); }
    $(doc, "[data-note]").click(); await settle(win);
    const text = [];
    for (const t of ["note", "changes", "needs", "gaps"]) {
      $(doc, `[data-tab="${t}"]`).dispatchEvent(new win.MouseEvent("mousedown", { bubbles: true, button: 0 }));
      await settle(win, 60);
      text.push(doc.documentElement.outerHTML);
    }
    $(doc, "[data-open-help]").click(); await settle(win);
    const leaks = privacyLeaks(doc, markers);
    const leaksEachTab = text.flatMap((h) => markers.filter((m) => h.includes(m)));
    ok("no withheld string reaches the rendered page (text or markup, every tab)", leaks.length === 0 && leaksEachTab.length === 0,
       [...leaks, ...leaksEachTab].slice(0, 3).join(" | "));
  } else if (tag === "template corpus" || tag === "redacted corpus") {
    ok("this corpus has a full-build oracle beside it", false, fullPath);
  }

  ok("no error surfaced while driving it", errors.length === 0, errors.slice(0, 2).join(" | "));
  win.close();
}

const RUNS = [
  ["template corpus", FIX("graph.json")],
  ["redacted corpus", FIX("redacted.json")],
  ["120 notes", FIX("n120.json")],
  ["1020 notes", FIX("n1020.json")],
  ["3020 notes", FIX("n3020.json")],
  ["full local build", FIX("graph.full.json")],
];
for (const [tag, f] of RUNS) await run(tag, f);

// --- arrival states -----------------------------------------------------------------------------
console.log("\n=== arriving ===");
{
  const g = JSON.parse(fs.readFileSync(FIX("graph.json"), "utf8"));
  const t = richNote(g);
  const a = await boot(FIX("graph.json"), { hash: "#grid:area~" + encodeURIComponent(t.id) + "!focus" });
  const centre = a.doc.querySelector("[data-centre]");
  ok("a pasted grid focus link opens that note in focus", !!centre && centre.getAttribute("data-centre") === t.id, a.errors.join());
  a.win.close();

  const b = await boot(FIX("graph.json"), { hash: "#area/features~" + encodeURIComponent(t.id) });
  ok("an old-format link (#area/<group>~<id>) opens the sky on its note",
     b.doc.querySelector("[data-view=sky]")?.getAttribute("data-selected") === t.id);
  b.win.close();

  const c = await boot(FIX("graph.json"), { hash: "#area~no/such-note" });
  ok("a link to a note that is not here opens the sky, not an error", !!c.doc.querySelector("[data-view=sky]") && !c.doc.querySelector("[data-view=sky]").hasAttribute("data-selected") && c.errors.length === 0);
  c.win.close();

  const d = await boot(FIX("graph.json"), { search: "?data=../../etc/passwd" });
  ok("?data= only reads files under data/", d.win.__fetched[0] === "data/graph.json", d.win.__fetched.join());
  d.win.close();

  const e = await boot(FIX("graph.json"), { search: "?data=data/n120.json" });
  ok("?data=data/<name>.json is honoured", e.win.__fetched[0] === "data/n120.json");
  e.win.close();

  const f = await boot(null, { fetchFails: true });
  ok("a missing data file explains how to build it", (f.doc.querySelector("[data-problem]") || { textContent: "" }).textContent.includes("build_atlas.py"));
  f.win.close();

  const old = JSON.parse(fs.readFileSync(FIX("graph.json"), "utf8"));
  old.schema = 3;
  const h = await boot(null, { graphText: JSON.stringify(old) });
  ok("an old data file says it is too old", (h.doc.querySelector("[data-problem]") || { textContent: "" }).textContent.includes("too old"));
  h.win.close();

  const r = await boot(FIX("graph.json"), { reducedMotion: true, hash: "#grid:area" });
  ok("with reduced motion it still boots, with no error", !!r.doc.querySelector('[data-view="map"]') && r.errors.length === 0, r.errors.join());
  const first = r.doc.querySelector("[data-stats] [data-value]");
  ok("with reduced motion the numbers do not count up", !!first && first.textContent === String(g.stats.notes), first && first.textContent);
  r.doc.querySelector("[data-theme-toggle]").click(); await settle(r.win);
  const th = r.doc.documentElement.getAttribute("data-theme");
  ok("the theme toggle sets and remembers a theme", (th === "dark" || th === "light") && r.win.localStorage.getItem("atlas-theme") === th, th);
  r.win.close();

  const lv = await boot(FIX("graph.json"), { lastVisit: "2000-01-01T00:00:00Z" });
  ok("a returning visitor is told what changed since", (lv.doc.querySelector("[data-briefing]") || { textContent: "" }).textContent.includes("since you last looked"));
  lv.win.close();
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
