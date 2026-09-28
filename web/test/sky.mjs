/* The SKY, the main view, against the built page at every corpus size. The canvas draws nothing
 * under jsdom, but the geometry is arithmetic, and the engine reports it through
 * window.__atlasSky.snapshot(): where each star is on screen, each name's box, and the focus.
 * Everything here is compared with what the graph says, computed from the raw edges. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { boot, settle, key, expectedLineage, sameSet, withheldMarkers, privacyLeaks } from "./harness.mjs";
import { snap, labelProblems, crowding } from "./sky-checks.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIX = (n) => path.join(HERE, "fixtures", n);
const LINEAGE_CAP = 14, SEE_CAP = 8;   // web/app/src/lib/sky.ts

let pass = 0, fail = 0;
const ok = (name, cond, detail = "") => {
  if (cond) { pass++; console.log("  PASS " + name + (detail ? "  " + detail : "")); }
  else { fail++; console.log("  FAIL " + name + "  " + detail); }
};

function clickStar(win, id) {
  const s = win.__atlasSky.snapshot().stars.find((x) => x.id === id);
  if (!s) return false;
  const c = win.document.querySelector("[data-view=sky] canvas");
  c.dispatchEvent(new win.MouseEvent("click", { bubbles: true, clientX: s.x, clientY: s.y }));
  return true;
}
const richNote = (g) => {
  const score = (id) => { const l = expectedLineage(g, id); return Math.min(l.reliesOn.size, l.reliedOnBy.size) * 10 + l.reliesOn.size + l.reliedOnBy.size + l.related.size; };
  return [...g.nodes].sort((a, b) => score(b.id) - score(a.id) || a.id.localeCompare(b.id))[0];
};
const capped = (shown, want, cap) => (want.size <= cap ? sameSet(new Set(shown), want) : shown.length === cap && shown.every((x) => want.has(x)));

async function run(tag, file) {
  console.log("\n=== " + tag + " ===");
  const g = JSON.parse(fs.readFileSync(file, "utf8"));
  const { win, doc, errors } = await boot(file);
  ok("boots into the sky without an error", !!doc.querySelector("[data-view=sky] canvas") && !!win.__atlasSky && errors.length === 0, errors.slice(0, 2).join(" | "));

  let s = snap(win);
  ok("every note is a star", s.stars.length === g.nodes.length, `${s.stars.length} of ${g.nodes.length}`);
  const folders = new Set(g.nodes.map((n) => (n.path.includes("/") ? n.path.slice(0, n.path.lastIndexOf("/")) : "")));
  ok("one cluster per area", s.groups === folders.size, `${s.groups} vs ${folders.size}`);
  const crowd = crowding(s);
  ok("no two stars are closer than two of the largest dots", crowd.length === 0, crowd.slice(0, 3).join("; "));
  ok("the whole sky is in frame after the opening move",
     s.stars.every((x) => x.x >= 0 && x.x <= s.width && x.y >= 0 && x.y <= s.height), `k=${s.k.toFixed(3)}`);
  let lp = labelProblems(s);
  ok("at a distance: no name touches another or covers a star", lp.length === 0, lp.slice(0, 3).join("; "));
  // Every area is named unless its name has no free place at this distance; those are the small
  // ones, and a closer zoom names them. The large areas (a twentieth of the notes or more) must be.
  const gNamed = new Set(s.labels.filter((l) => l.kind === "group").map((l) => l.id.slice(6)));
  const areaOf = (n) => "area:" + (n.path.includes("/") ? n.path.slice(0, n.path.lastIndexOf("/")) : "");
  const sizes = new Map(); for (const n of g.nodes) sizes.set(areaOf(n), (sizes.get(areaOf(n)) || 0) + 1);
  const bigUnnamed = [...sizes].filter(([k, v]) => v >= g.nodes.length / 20 && !gNamed.has(k)).map(([k]) => k);
  ok("at a distance: every large area is named", bigUnnamed.length === 0, `${gNamed.size} of ${s.groups} named; missing ${bigUnnamed.join()}`);
  ok("at a distance: most areas are named", gNamed.size >= Math.ceil(s.groups * 0.6), `${gNamed.size} of ${s.groups}`);
  ok("something was actually drawn", win.__canvasCalls.fillText > 0, `${win.__canvasCalls.fillText} text draws`);

  // zoom in on the middle: more names appear, still none collide
  for (let i = 0; i < 12 && win.__atlasSky.snapshot().k < 0.9; i++) { doc.querySelector('[aria-label="Zoom in"]').click(); win.__atlasSky.settle(); }
  s = snap(win);
  lp = labelProblems(s);
  ok("closer in: note names appear", s.labels.some((l) => l.kind === "note"), `${s.labels.filter((l) => l.kind === "note").length} names at k=${s.k.toFixed(2)}`);
  ok("closer in: still no name touches another or covers a star", lp.length === 0, lp.slice(0, 3).join("; "));

  // --- choosing a note: the lineage forms around it ---------------------------------------------
  const t = richNote(g);
  doc.querySelector('[aria-label="Show the whole sky"]').click(); snap(win);
  ok("a star can be clicked", clickStar(win, t.id), t.id);
  await settle(win, 60);
  s = snap(win);
  const want = expectedLineage(g, t.id);
  ok("clicking a star chooses it", s.selected === t.id && doc.querySelector("[data-view=sky]").getAttribute("data-selected") === t.id);
  ok("the rail shows it, and no box opens over the sky",
     !!doc.querySelector(`[data-detail]`) && !doc.querySelector("[data-sky-tip]") && !doc.querySelector('[role="dialog"]'));
  ok("left: exactly what it relies on", capped(s.lineage.on, want.reliesOn, LINEAGE_CAP), `${s.lineage.on.length} vs ${want.reliesOn.size}`);
  ok("right: exactly what relies on it", capped(s.lineage.by, want.reliedOnBy, LINEAGE_CAP), `${s.lineage.by.length} vs ${want.reliedOnBy.size}`);
  ok("below: exactly what it relates to", capped(s.lineage.see, want.related, SEE_CAP), `${s.lineage.see.length} vs ${want.related.size}`);
  ok("anything left out is counted, for the panel", s.hidden.on === Math.max(0, want.reliesOn.size - LINEAGE_CAP) && s.hidden.by === Math.max(0, want.reliedOnBy.size - LINEAGE_CAP));
  const centre = s.stars.find((x) => x.id === t.id);
  ok("the chosen star is brought to the middle", Math.abs(centre.x - s.width / 2) < 2, `x=${centre.x.toFixed(1)} of ${s.width}`);
  const sideOk = s.stars.filter((x) => x.side).every((x) => (x.side === "on" ? x.x < centre.x : x.side === "by" ? x.x > centre.x : x.y > centre.y));
  ok("relied-on stand to its left, dependents to its right, see-also below", sideOk);
  const named = new Set(s.labels.map((l) => l.id));
  const unnamed = [...s.lineage.on, ...s.lineage.by, ...s.lineage.see].filter((id) => !named.has(id));
  ok("every note in the focus is named", unnamed.length === 0, unnamed.slice(0, 3).join());
  lp = labelProblems(s);
  ok("in focus: no name touches another or covers a star", lp.length === 0, lp.slice(0, 3).join("; "));
  ok("the rest of the sky steps back", s.stars.filter((x) => !x.side && x.id !== t.id).every((x) => x.a <= 0.21));
  ok("the address names it", win.location.hash === "#area~" + encodeURIComponent(t.id), win.location.hash);

  const next = s.lineage.by[0] || s.lineage.on[0] || s.lineage.see[0];
  if (next) {
    clickStar(win, next); await settle(win, 60); s = snap(win);
    const w2 = expectedLineage(g, next);
    ok("clicking a neighbour moves the focus there", s.selected === next, next);
    ok("...with its own exact lineage", capped(s.lineage.on, w2.reliesOn, LINEAGE_CAP) && capped(s.lineage.by, w2.reliedOnBy, LINEAGE_CAP) && capped(s.lineage.see, w2.related, SEE_CAP));
    key(win, doc.body, "Escape"); await settle(win, 60); s = snap(win);
    ok("Escape steps back to the note before", s.selected === t.id, String(s.selected));
  }
  key(win, doc.body, "Escape"); await settle(win, 60); s = snap(win);
  ok("Escape again returns every star home", s.selected === null && s.stars.every((x) => !x.side && x.a > 0.99));

  // --- rearranging -----------------------------------------------------------------------------
  doc.querySelector('#group [data-value="time"]').click(); await settle(win, 60); s = snap(win);
  const months = new Set(g.nodes.map((n) => { const v = (n.updated || n.created || "").slice(0, 7); return /^\d{4}-\d{2}$/.test(v) ? v : "undated"; }));
  ok("by time: one cluster per month", s.groups === months.size, `${s.groups} vs ${months.size}`);
  ok("by time: every note is still a star", s.stars.length === g.nodes.length);
  ok("by time: still no crowding", crowding(s).length === 0);
  lp = labelProblems(s);
  ok("by time: no name collisions", lp.length === 0, lp.slice(0, 2).join("; "));
  doc.querySelector('#group [data-value="area"]').click(); await settle(win, 60);

  // --- hiding a level ----------------------------------------------------------------------------
  const lvl = [...new Set(g.nodes.map((n) => n.level))].sort()[0];
  const byId = new Map(g.nodes.map((n) => [n.id, n]));
  doc.querySelector(`[data-legend] [data-level="${lvl}"]`).click(); await settle(win, 60); s = snap(win);
  ok(`hiding ${lvl} takes its stars out of the sky`, s.stars.every((x) => byId.get(x.id).level !== lvl) && s.stars.length === g.nodes.filter((n) => n.level !== lvl).length);
  doc.querySelector(`[data-legend] [data-level="${lvl}"]`).click(); await settle(win, 60);

  // --- privacy: the sky's names come from the same public fields ---------------------------------
  const fullPath = file.replace(/\.json$/, ".full.json");
  if (fs.existsSync(fullPath)) {
    const markers = withheldMarkers(g, JSON.parse(fs.readFileSync(fullPath, "utf8")));
    clickStar(win, t.id); await settle(win, 60); snap(win);
    const leaks = privacyLeaks(doc, markers);
    ok("no withheld string reaches the page in the sky", markers.length > 0 && leaks.length === 0, `${markers.length} markers, ${leaks.length} leaks`);
  }
  ok("no error while driving it", errors.length === 0, errors.slice(0, 2).join(" | "));
  win.close();
}

for (const [tag, f] of [["template corpus", FIX("graph.json")], ["redacted corpus", FIX("redacted.json")], ["120 notes", FIX("n120.json")],
  ["1020 notes", FIX("n1020.json")], ["3020 notes", FIX("n3020.json")]]) await run(tag, f);

console.log("\n=== motion ===");
{
  const g = JSON.parse(fs.readFileSync(FIX("graph.json"), "utf8"));
  const t = richNote(g);
  const a = await boot(FIX("graph.json"));
  a.win.__atlasSky.settle();
  clickStar(a.win, t.id);
  await settle(a.win, 30);
  ok("choosing a star is a journey, not a cut", a.win.__atlasSky.snapshot().animating === true);
  a.win.close();
  const r = await boot(FIX("graph.json"), { reducedMotion: true });
  await settle(r.win, 50);
  clickStar(r.win, t.id);
  await settle(r.win, 40);
  const s = r.win.__atlasSky.snapshot();
  ok("with reduced motion it arrives at once", s.selected === t.id && s.animating === false && Math.abs(s.stars.find((x) => x.id === t.id).x - s.width / 2) < 2);
  r.win.close();
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
