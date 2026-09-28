/* Break each invariant on purpose and confirm its check goes red. A check that has never been
 * seen to fail has not been shown to check anything. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { boot, settle, dblclick, partitionProblems, expectedLineage, shownLineage, sameSet, withheldMarkers, privacyLeaks } from "./harness.mjs";
import { labelProblems, crowding, snap } from "./sky-checks.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const TMP = path.join(HERE, ".work");
fs.mkdirSync(TMP, { recursive: true });
const FIX = (n) => path.join(HERE, "fixtures", n);
let pass = 0, fail = 0;
const ok = (n, c, d = "") => { c ? pass++ : fail++; console.log((c ? "  PASS " : "  FAIL ") + n + (d ? "  " + d : "")); };

// 1. the partition check sees a note that vanished from the grid, and one drawn twice
{
  const g = JSON.parse(fs.readFileSync(FIX("n120.json"), "utf8"));
  const { win, doc } = await boot(FIX("n120.json"), { hash: "#grid:area" });
  ok("partition: clean before sabotage", partitionProblems(doc, g).length === 0);
  const chip = doc.querySelector('[data-view="map"] [data-note]');
  const clone = chip.cloneNode(true);
  chip.parentElement.appendChild(clone);
  ok("negative: a note drawn twice is caught", partitionProblems(doc, g).some((p) => p.startsWith("drawn twice")));
  clone.remove(); chip.remove();
  ok("negative: a note missing from the grid is caught", partitionProblems(doc, g).some((p) => p.includes("visible notes")));
  win.close();
}

// 2. the lineage check sees a neighbour in the wrong column
{
  const g = JSON.parse(fs.readFileSync(FIX("graph.json"), "utf8"));
  const id = "features/context-protocol";
  const { win, doc } = await boot(FIX("graph.json"), { hash: "#grid:area~" + encodeURIComponent(id) + "!focus" });
  await settle(win, 200);
  const want = expectedLineage(g, id);
  ok("lineage: the real page matches before sabotage", sameSet(shownLineage(doc).reliedOnBy, want.reliedOnBy) && want.reliedOnBy.size > 0);
  const el = doc.querySelector('[data-lineage="right"][data-present]');
  el.setAttribute("data-lineage", "left");
  const shown = shownLineage(doc);
  ok("negative: a dependent shown on the relied-on side is caught", !sameSet(shown.reliedOnBy, want.reliedOnBy) && !sameSet(shown.reliesOn, want.reliesOn));
  el.removeAttribute("data-present"); el.setAttribute("data-lineage", "right");
  ok("negative: a neighbour still leaving (not present) is not counted", !sameSet(shownLineage(doc).reliedOnBy, want.reliedOnBy));
  win.close();
}

// 3. the sky's geometry checks see a collision and a crowd
{
  const { win } = await boot(FIX("n120.json"));
  for (let i = 0; i < 8 && win.__atlasSky.snapshot().k < 1; i++) { win.document.querySelector('[aria-label="Zoom in"]').click(); win.__atlasSky.settle(); }
  const s = snap(win);
  ok("sky: clean before sabotage", labelProblems(s).length === 0 && crowding(s).length === 0 && s.labels.length > 1);
  const a = JSON.parse(JSON.stringify(s));
  const l0 = a.labels.find((l) => l.kind === "note") || a.labels[0];
  a.labels.push({ ...l0, id: "intruder", x: l0.x + 4 });
  ok("negative: two names on top of each other are caught", labelProblems(a).some((p) => p.includes("intruder")));
  const b = JSON.parse(JSON.stringify(s));
  const star = b.stars.find((x) => !b.labels.some((l) => l.id === x.id)) || b.stars[1];
  const lab = b.labels.find((l) => l.kind === "note" && l.id !== star.id);
  lab.x = star.x - 2; lab.y = star.y - 2;
  ok("negative: a name laid over another star is caught", labelProblems(b).some((p) => p.includes("covers the star")));
  const c = JSON.parse(JSON.stringify(s));
  c.stars[1].x = c.stars[0].x + 1; c.stars[1].y = c.stars[0].y;
  ok("negative: two stars nearly on top of each other are caught", crowding(c).length > 0);
  win.close();
}

// 4. the privacy oracle sees a withheld string rendered into the page, in both views
{
  const pub = JSON.parse(fs.readFileSync(FIX("graph.json"), "utf8"));
  const full = JSON.parse(fs.readFileSync(FIX("graph.full.json"), "utf8"));
  const markers = withheldMarkers(pub, full);
  ok("oracle: the template corpus yields withheld markers", markers.length > 0, `${markers.length}`);
  const leaky = JSON.parse(JSON.stringify(pub));
  leaky.nodes[0].tags = [...(leaky.nodes[0].tags || []), markers[0]];
  const f = path.join(TMP, "leaky.json");
  fs.writeFileSync(f, JSON.stringify(leaky));
  const { win, doc } = await boot(f, { hash: "#grid:area~" + encodeURIComponent(leaky.nodes[0].id) });
  await settle(win, 150);
  ok("negative: a withheld string rendered into the page is caught", privacyLeaks(doc, markers).length > 0);
  win.close();
}
{
  const pub = JSON.parse(fs.readFileSync(FIX("redacted.json"), "utf8"));
  const full = JSON.parse(fs.readFileSync(FIX("redacted.full.json"), "utf8"));
  const markers = withheldMarkers(pub, full);
  const short = markers.filter((m) => m.length < 24);
  const leaky = JSON.parse(JSON.stringify(pub));
  leaky.nodes[0].title = short[0] || "";
  const f = path.join(TMP, "leaky-short.json");
  fs.writeFileSync(f, JSON.stringify(leaky));
  const { win, doc } = await boot(f, { hash: "#area~" + encodeURIComponent(leaky.nodes[0].id) });
  await settle(win, 150);
  ok("negative: a short restricted title rendered into the page is caught", short.length > 0 && privacyLeaks(doc, markers).length > 0,
     `${short.length} short markers`);
  win.close();
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
