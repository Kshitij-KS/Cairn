/* The invariant this whole design exists to keep, asserted at every corpus size:
 * never more than `cap` labelled things on screen, at any depth, in either arrangement. */
import { boot, withheldMarkers, privacyLeaks, omittedCount } from "./harness.mjs";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const TMP = path.join(HERE, ".work");
fs.mkdirSync(TMP, { recursive: true }); // a fresh checkout has no .work/: the first run died on ENOENT
// Fixtures live beside the tests. Generate the synthetic ones with
// tools/gen_fixture.py, then build each with scripts/build_atlas.py.
const FIX = (n) => path.join(HERE, "fixtures", n);

let pass = 0, fail = 0;
const ok = (name, cond, detail = "") => {
  if (cond) { pass++; console.log("  PASS " + name + (detail ? "  " + detail : "")); }
  else { fail++; console.log("  FAIL " + name + "  " + detail); }
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Label boxes from the rendered DOM, IN SCREEN SPACE. The first version of this measured world
// coordinates and reported 86% collisions on a view that is actually clean, because the camera
// zooms in when you open a constellation. A checker that ignores the camera is measuring a
// picture nobody is looking at.
function camOf(win) {
  const g = win.document.querySelector("g.world");
  const t = (g && g.getAttribute("transform")) || "";
  const tr = t.match(/translate\(([-\d.e]+)[, ]([-\d.e]+)\)/);
  const sc = t.match(/scale\(([-\d.e]+)\)/);
  return { x: tr ? +tr[1] : 0, y: tr ? +tr[2] : 0, k: sc ? +sc[1] : 1 };
}

function labelBoxes(doc, sel, cam = { x: 0, y: 0, k: 1 }) {
  const out = [];
  for (const g of doc.querySelectorAll(sel)) {
    if (g.classList.contains("leaving")) continue;
    // .minor labels are hidden by CSS opacity, which jsdom does not cascade; counting them as
    // drawn is measuring a label nobody can see.
    if (g.classList.contains("minor") && !doc.querySelector("g.world.close")) continue;
    const t = g.getAttribute("transform") || "";
    const m = t.match(/translate\(([-\d.]+),([-\d.]+)\)/);
    if (!m) continue;
    const label = g.querySelector("text");
    if (!label || !label.textContent.trim()) continue;
    if (label.style.display === "none") continue;
    const text = label.textContent.trim();
    // The declared size is in USER units. SVG scales text along with everything else, so the
    // size on screen is declared x (camera scale) x (any counter-scale the element carries).
    // Believing text was camera-independent is exactly how the labels got three times too big.
    const decl = g.classList.contains("cl") ? 14 : 11;
    const own = ((label.parentElement.getAttribute("transform") || "")
      .match(/scale\(([-\d.e]+)\)/) || [, 1])[1];
    const fs_ = decl * cam.k * Number(own);
    const w = text.length * fs_ * 0.51, h = fs_ * 1.2;
    const sx = cam.x + (+m[1]) * cam.k;
    const sy = cam.y + (+m[2]) * cam.k + (+(label.getAttribute("y") || 0)) * cam.k * Number(own);
    out.push({ x: sx - w / 2, y: sy - h, w, h, text, screenFont: fs_ });
  }
  return out;
}
const collisions = (boxes) => {
  let n = 0;
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) { n++; break; }
  }
  return n;
};

async function run(tag, file) {
  console.log("\n=== " + tag + " ===");
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  const { win, doc, errors } = await boot(file);
  const cap = data.arrangements.area.cap;

  ok("boots without a thrown error", errors.length === 0, errors.slice(0, 2).join(" | "));
  ok("skeleton is dismissed", doc.querySelector("#boot").classList.contains("gone"));

  // --- depth 0 -----------------------------------------------------------
  const clusters = [...doc.querySelectorAll("g.cl:not(.leaving)")];
  ok("top level draws constellations", clusters.length >= 2, `${clusters.length} drawn`);
  ok("top level stays small however big the corpus", clusters.length <= 14, `${clusters.length}`);
  const cb = labelBoxes(doc, "g.cl", camOf(win));
  {
    const sizes = cb.map((b) => b.screenFont);
    const off = sizes.filter((v) => Math.abs(v - 14) > 0.8);
    ok("constellation names are a constant size on screen", off.length === 0,
       sizes.length ? `sizes seen: ${[...new Set(sizes.map((v) => v.toFixed(1)))].join(", ")}px` : "none");
  }
  ok("no constellation labels collide", collisions(cb) === 0,
     `${collisions(cb)} of ${cb.length} collide`);
  ok("every constellation is labelled", cb.length === clusters.length, `${cb.length}/${clusters.length}`);
  ok("no notes are drawn at the far view", doc.querySelectorAll("g.nd:not(.leaving)").length === 0);

  let notes = [];

  // --- every level, not just the top: the cap the first version forgot -----
  {
    // walk back to the top, then drill the biggest branch to the bottom, checking each level
    for (let i = 0; i < 6 && doc.querySelectorAll("#crumbs .crumb").length > 1; i++) {
      doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await sleep(260);
    }
    let worstGroups = 0, worstColl = 0, depth = 0, path = [];
    for (let d = 0; d < 5; d++) {
      const groups = [...doc.querySelectorAll("g.cl:not(.dim):not(.container):not(.leaving)")];
      if (!groups.length) break;
      const gb = labelBoxes(doc, "g.cl:not(.dim):not(.container)", camOf(win));
      worstGroups = Math.max(worstGroups, groups.length);
      worstColl = Math.max(worstColl, collisions(gb));
      depth = d + 1;
      const next = groups.map((el) => ({ el, n: +el.querySelector(".cl-count").textContent }))
        .sort((a, b) => b.n - a.n)[0];
      path.push(next.n);
      next.el.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
      await sleep(1000);
    }
    ok("no level ever shows too many groups", worstGroups <= 12,
       `widest level had ${worstGroups} groups, ${depth} levels deep (${path.join(" > ")})`);
    ok("group labels never collide at any depth", worstColl === 0, `${worstColl} collided`);

    notes = [...doc.querySelectorAll("g.nd:not(.leaving)")];
    // Every corpus must reach real notes, or the checks below inspect nothing.
    ok("drilling down reaches actual notes", notes.length > 0, `${notes.length} at the bottom`);
    ok("never more notes than the cap", notes.length <= cap, `${notes.length} <= ${cap}`);
    const nb = labelBoxes(doc, "g.nd", camOf(win));
    const coll = collisions(nb);
    {
      const sizes = nb.map((b) => b.screenFont);
      const off = sizes.filter((v) => Math.abs(v - 11) > 0.8);
      ok("note names are a constant size on screen", off.length === 0,
         sizes.length ? `sizes seen: ${[...new Set(sizes.map((v) => v.toFixed(1)))].join(", ")}px` : "none");
    }
    ok("note labels stay legible", coll === 0,
       `${coll} of ${nb.length} labels drawn collide, out of ${notes.length} notes`);
    ok("most notes are named at a glance",
       notes.length > 0 && nb.length >= Math.ceil(notes.length * 0.55),
       `${nb.length} of ${notes.length} named`);
    ok("breadcrumb shows where you are", doc.querySelectorAll("#crumbs .crumb").length >= 2,
       doc.querySelector("#crumbs").textContent.replace(/\s+/g, " ").trim());
  }

  // --- select a note: the close-up ---------------------------------------
  if (notes.length) {
    notes[0].dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    await sleep(600);
    ok("selecting marks the note", !!doc.querySelector("g.nd.sel"));
    ok("the anchored card opens", !doc.querySelector("#card").hidden);
    ok("the card names the note", (doc.querySelector("#card h3")?.textContent || "").length > 0,
       doc.querySelector("#card h3")?.textContent?.slice(0, 40));
    ok("the rest of the constellation recedes", doc.querySelectorAll("g.nd.faded").length > 0
       || notes.length < 3, `${doc.querySelectorAll("g.nd.faded").length} faded`);
    ok("the full entry fills the rail", (doc.querySelector("#detail").textContent || "").includes("Who wrote it"));

    // back out
    doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await sleep(300);
    ok("escape closes the close-up", doc.querySelector("#card").hidden);
  }

  // --- back to the top ---------------------------------------------------
  let guard = 0;
  while (doc.querySelectorAll("#crumbs .crumb").length > 1 && guard++ < 6) {
    doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await sleep(220);
  }
  ok("escape walks all the way back out", doc.querySelectorAll("#crumbs .crumb").length === 1);

  // --- the other arrangement --------------------------------------------
  doc.querySelector('#seg-arrange button[data-arrange="time"]')
    .dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
  await sleep(1000);
  const tcl = [...doc.querySelectorAll("g.cl:not(.leaving)")];
  ok("the time arrangement draws", tcl.length >= 1, `${tcl.length} months`);
  ok("time labels do not collide either", collisions(labelBoxes(doc, "g.cl", camOf(win))) === 0);
  ok("the arrangement toggle reflects the change",
     doc.querySelector('#seg-arrange button[data-arrange="time"]').getAttribute("aria-pressed") === "true");

  // --- privacy (oracle: the full build of the same corpus, if there is one) ------------
  const fullPath = file.replace(/\.json$/, ".full.json");
  if (fs.existsSync(fullPath)) {
    const fullData = JSON.parse(fs.readFileSync(fullPath, "utf8"));
    const markers = withheldMarkers(data, fullData);
    ok("the privacy oracle has something to look for", markers.length > 0, `${markers.length} withheld markers`);
    if (tag === "redacted corpus") {
      // a check whose denominator is zero checked nothing (recheck 07-F5)
      ok("the redacted corpus leaves notes out, so the restricted-name check has something to test",
         omittedCount(data, fullData) >= 2, `${omittedCount(data, fullData)} omitted`);
      ok("short secret names are markers too", markers.some((m) => m.length < 24), markers.filter((m) => m.length < 24).join(", "));
    }
    const leaks = privacyLeaks(doc, markers);
    ok("no withheld string reaches the rendered page (text or markup)", leaks.length === 0, leaks.slice(0, 3).join(" | "));
  } else if (tag === "template corpus") {
    ok("the template corpus has a full-build oracle beside it (graph.full.json)", false, fullPath);
  }
  ok("the public file carries no commit messages",
     data.mode !== "public" || data.activity.every((a) => a.message === null));

  win.close();
  return { pass, fail };
}

const fixtures = [
  ["template corpus", FIX("graph.json")],
  ["redacted corpus", FIX("redacted.json")],
  ["120 notes", FIX("n120.json")],
  ["1020 notes", FIX("n1020.json")],
  ["3020 notes", FIX("n3020.json")],
];
for (const [tag, f] of fixtures) {
  if (!fs.existsSync(f)) { console.log("\n=== " + tag + " === (missing)"); fail++; continue; }  // a missing fixture is red
  await run(tag, f);
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
