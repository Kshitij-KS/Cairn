/* Break each invariant on purpose and confirm the check goes red, then confirm the reduced-motion path still renders a usable page. */
import { boot, withheldMarkers, privacyLeaks } from "./harness.mjs";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const TMP = path.join(HERE, ".work");
fs.mkdirSync(TMP, { recursive: true }); // a fresh checkout has no .work/: the first run died on ENOENT
// Fixtures live beside the tests. Generate the synthetic ones with
// tools/gen_fixture.py, then build each with scripts/build_atlas.py.
const FIX = (n) => path.join(HERE, "fixtures", n);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let pass = 0, fail = 0;
const ok = (n, c, d = "") => { c ? pass++ : fail++; console.log((c ? "  PASS " : "  FAIL ") + n + (d ? "  " + d : "")); };

const src = JSON.parse(fs.readFileSync(FIX("n1020.json"), "utf8"));

// 1. overfill a leaf cluster and confirm the cap check would catch it
{
  const d = JSON.parse(JSON.stringify(src));
  const leaf = (function find(cs) {
    for (const c of cs) { if (c.members?.length) return c; const r = find(c.children || []); if (r) return r; }
    return null;
  })(d.arrangements.area.clusters);
  const extra = d.nodes.slice(0, 200).map((n) => n.id);
  leaf.members = [...new Set([...leaf.members, ...extra])];
  leaf.count = leaf.members.length;
  for (const id of extra) if (!leaf.pos[id]) leaf.pos[id] = [Math.random() * 2 - 1, Math.random() * 2 - 1];
  fs.writeFileSync(path.join(TMP, "bad-cap.json"), JSON.stringify(d));
  const { win, doc } = await boot(path.join(TMP, "bad-cap.json"));
  const live = (s) => [...doc.querySelectorAll(s)].filter((e) => !e.classList.contains("leaving"));
  // drill to that leaf
  for (let i = 0; i < 6; i++) {
    const g = live("g.cl:not(.dim):not(.container)");
    if (!g.length) break;
    g.map((el) => ({ el, n: +el.querySelector(".cl-count").textContent }))
      .sort((a, b) => b.n - a.n)[0].el.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    await sleep(900);
  }
  const n = live("g.nd").length;
  // and at least one note must be reached, or this passes by never reaching any notes at all
  ok("the cap is enforced in the CLIENT too, not only the builder",
     n > 0 && n <= d.arrangements.area.cap,
     `a cluster claiming ${leaf.count} members drew ${n}`);
  win.close();
}

// 2. confirm the label check can go red: force every label on at a dense level
{
  const { win, doc } = await boot(FIX("n1020.json"));
  const live = (s) => [...doc.querySelectorAll(s)].filter((e) => !e.classList.contains("leaving"));
  for (let i = 0; i < 6; i++) {
    const g = live("g.cl:not(.dim):not(.container)");
    if (!g.length) break;
    g.map((el) => ({ el, n: +el.querySelector(".cl-count").textContent }))
      .sort((a, b) => b.n - a.n)[0].el.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    await sleep(900);
  }
  const minor = live("g.nd.minor").length, total = live("g.nd").length;
  ok("the thinning pass actually parks labels at density", minor > 0 && minor < total,
     `${minor} of ${total} parked — if this were 0 the legibility check would be vacuous`);
  win.close();
}

// 3. reduced motion: the page must be fully usable with nothing moving
{
  const { win, doc, errors } = await boot(FIX("n1020.json"), { reducedMotion: true });
  const live = (s) => [...doc.querySelectorAll(s)].filter((e) => !e.classList.contains("leaving"));
  ok("reduced motion boots clean", errors.length === 0, errors.slice(0, 1).join(""));
  ok("reduced motion still draws the map", live("g.cl").length >= 2, `${live("g.cl").length} groups`);
  ok("the motion switch hides itself when the OS already said no",
     doc.querySelector("#motion-row").hidden === true);
  ok("with reduced motion no light runs along the edges", doc.querySelectorAll(".packet").length === 0);
  const g = live("g.cl:not(.dim):not(.container)")[0];
  g.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
  await sleep(120);                                  // no transition to wait for
  ok("navigation is instant with motion off",
     live("g.nd").length + live("g.cl:not(.dim):not(.container)").length > 0,
     `${live("g.nd").length} notes, ${live("g.cl:not(.dim):not(.container)").length} groups after 120ms`);
  win.close();
}

// 4. a corpus with no arrangements at all must say so rather than render nothing
{
  const d = JSON.parse(JSON.stringify(src));
  delete d.arrangements;
  fs.writeFileSync(path.join(TMP, "bad-old.json"), JSON.stringify(d));
  const { doc, win } = await boot(path.join(TMP, "bad-old.json"));
  ok("an out-of-date data file explains itself",
     doc.body.textContent.includes("too old"), doc.querySelector("#boot h2")?.textContent || "");
  win.close();
}

// privacy oracle can fail (audit 07-F5): render a withheld body line through a title
{
  const pub = JSON.parse(fs.readFileSync(FIX("graph.json"), "utf8"));
  const full = JSON.parse(fs.readFileSync(FIX("graph.full.json"), "utf8"));
  const markers = withheldMarkers(pub, full);
  ok("oracle: the template corpus yields withheld markers", markers.length > 0, `${markers.length}`);
  const leaky = JSON.parse(JSON.stringify(pub));
  leaky.arrangements.area.clusters[0].label = markers[0];  // top-level cluster labels are always drawn
  fs.writeFileSync(path.join(TMP, "leaky.json"), JSON.stringify(leaky));
  const { win, doc } = await boot(path.join(TMP, "leaky.json"));
  await sleep(600);
  doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "/", bubbles: true }));
  const leaks = privacyLeaks(doc, markers);
  ok("negative: a withheld string rendered into the page is caught", leaks.length > 0, `${leaks.length} leak(s)`);
  win.close();
}

// ...and a SHORT secret name, the class the old 24-character floor could never catch (07-F5)
{
  const pub = JSON.parse(fs.readFileSync(FIX("redacted.json"), "utf8"));
  const full = JSON.parse(fs.readFileSync(FIX("redacted.full.json"), "utf8"));
  const markers = withheldMarkers(pub, full);
  const short = markers.filter((m) => m.length < 24);
  const leaky = JSON.parse(JSON.stringify(pub));
  leaky.arrangements.area.clusters[0].label = short[0] || "";
  fs.writeFileSync(path.join(TMP, "leaky-short.json"), JSON.stringify(leaky));
  const { win, doc } = await boot(path.join(TMP, "leaky-short.json"));
  await sleep(600);
  const leaks = privacyLeaks(doc, markers);
  ok("negative: a short restricted title rendered into the page is caught", short.length > 0 && leaks.length > 0,
     `${short.length} short markers, ${leaks.length} leak(s)`);
  win.close();
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
