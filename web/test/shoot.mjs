/* Take the SVG the page actually built, resolve the tokens into plain attributes, and write it
 * out so it can be rasterised and looked at: jsdom cannot see type scaling. */
import { boot } from "./harness.mjs";
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

const OLD_DARK = { "--ground":"#0b1120","--ground-2":"#0e1626","--surface":"#121a2b","--ink":"#e8edf7",
  "--ink-2":"#93a2bc","--ink-3":"#7d8ba4","--rule":"#243044","--rule-soft":"#1a2436",
  "--accent":"#7fb2f0","--flag":"#e8b45e","--ok":"#7fc2a8","--l0":"#8fb8e8","--l1":"#7fc2a8",
  "--l2":"#e8b45e","--l3":"#e8836f","--link":"#2e3c55","--link-dep":"#566786" };

function svgOut(doc, name) {
  const svg = doc.querySelector("#graph").cloneNode(true);
  svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  svg.setAttribute("width", "1120"); svg.setAttribute("height", "760");
  svg.setAttribute("viewBox", "0 0 1120 760");

  // Paint by explicit attributes rather than by CSS: cairosvg's selector parser rejects the
  // pseudo-classes in the real stylesheet, and a rasteriser silently dropping rules would be
  // another way for the picture to differ from what the browser draws.
  const P = (sel, attrs) => svg.querySelectorAll(sel).forEach((el) => {
    for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  });
  // the dark (night) palette, from style.css
  P(".lk", { stroke: "#3A4460", opacity: "0.9", fill: "none", "stroke-linecap": "round", "stroke-width": "1.1" });
  P(".lk.dep", { stroke: "#7C86A6", "stroke-width": "1.5", opacity: "0.85" });
  P(".lk.hot", { stroke: "#DDA8FF", opacity: "1", "stroke-dasharray": "6 7" });
  P(".lk.cold", { opacity: "0.15" });
  P(".proc", { fill: "none", stroke: "#7C86A6", "stroke-width": "1", opacity: "0.45", "stroke-linecap": "round" });
  svg.querySelectorAll(".cl-tissue circle").forEach((e)=>e.setAttribute("opacity","0.85"));
  P(".df-a", { "stop-color": "#121A2A" });
  P(".df-b", { "stop-color": "#0C111D" });
  P(".cl-halo", { opacity: "0.10" });
  P(".cl-disc", { fill: "url(#disc-fill)", stroke: "#3E4866", "stroke-width": "1" });
  P(".cl-edge", { fill: "none", stroke: "#EEF1FA", "stroke-opacity": "0.10", "stroke-width": "1" });
  P(".cl-tick", { fill: "none", "stroke-width": "1", "stroke-dasharray": "1 9", opacity: "0.55" });
  P(".cl-name", { fill: "#EEF1FA", "font-family": "Georgia, serif", "font-weight": "400", stroke: "none" });
  P(".cl-count", { fill: "#B4BCD3", "font-family": "monospace", "letter-spacing": "0.04em", stroke: "none" });
  P(".cl-mix path", { fill: "none", "stroke-width": "3", "stroke-linecap": "round", opacity: "0.95" });
  P(".cl-flag", { fill: "none", stroke: "#F6C453", "stroke-width": "1.2", "stroke-dasharray": "3 5" });
  P(".nd-core", { stroke: "#070A12", "stroke-width": "1" });
  P(".nd-shine", { fill: "#ffffff", opacity: "0.16" });
  P(".cl.container .cl-tissue", { display: "none" });
  P(".nd-rim", { fill: "none", stroke: "#EEF1FA", "stroke-opacity": "0.18", "stroke-width": "1" });
  P(".nd-bloom", { opacity: "0.18" });
  P(".nd-breath", { fill: "none", opacity: "0" });
  P(".nd-flag", { fill: "none", stroke: "#F6C453", "stroke-width": "1.3", opacity: "0" });
  P(".nd.flagged .nd-flag", { opacity: "1" });
  P(".nd-label", { fill: "#B4BCD3", "font-family": "sans-serif", "font-size": "11", stroke: "none", "font-weight": "500" });
  P(".nd.minor .nd-label", { opacity: "0" });
  svg.querySelectorAll(".nd.faded").forEach((e) => e.setAttribute("style", "opacity:0.22"));
  P(".reticle", { stroke: "#D59CFF", "stroke-width": "1.3", fill: "none", opacity: "0" });
  P(".nd.sel .reticle", { opacity: "0.95" });
  P(".nd.sel .nd-core", { stroke: "#D59CFF", "stroke-width": "2.2" });
  P(".nd.sel .nd-label", { fill: "#EEF1FA", opacity: "1" });
  P(".nd.near .nd-core", { stroke: "#D59CFF", "stroke-width": "1.8" });
  P(".guest-dot", { fill: "#070A12", stroke: "#7C86A6", "stroke-width": "1.2", "stroke-dasharray": "2.5 2.5" });
  P(".guest.dep .guest-dot", { stroke: "#D59CFF", "stroke-dasharray": "none" });
  P(".guest-line", { stroke: "#7C86A6", "stroke-width": "1", opacity: "0.5", "stroke-dasharray": "3 4" });
  P(".guest-label", { fill: "#8891AE", "font-family": "sans-serif", "font-size": "10.5", stroke: "none" });
  P(".packet", { fill: "#E8C6FF", opacity: "0.9" });
  P(".cl.dim", { opacity: "0.28" });
  P(".cl.container .cl-disc", { fill: "none", stroke: "#3E4866", "stroke-dasharray": "2 7" });
  svg.querySelectorAll(".cl.dim .cl-name, .cl.dim .cl-count, .cl.dim .cl-mix")
     .forEach((el) => el.setAttribute("display", "none"));
  svg.querySelectorAll("filter").forEach((f) => f.remove());
  svg.querySelectorAll("[filter]").forEach((e) => e.removeAttribute("filter"));
  // a still picture: put each packet a third of the way along its path
  svg.querySelectorAll(".packet").forEach((c) => {
    const mp = c.querySelector("mpath"); const id = mp && (mp.getAttribute("href") || "").slice(1);
    const path = id && svg.querySelector("#" + id);
    const nums = path ? (path.getAttribute("d").match(/-?\d+(\.\d+)?/g) || []).map(Number) : [];
    if (nums.length >= 4) { c.setAttribute("cx", nums[nums.length - 2] + (nums[0] - nums[nums.length - 2]) * 0.33);
      c.setAttribute("cy", nums[nums.length - 1] + (nums[1] - nums[nums.length - 1]) * 0.33); }
    c.querySelectorAll("animateMotion").forEach((a) => a.remove());
  });

  const bg = doc.createElementNS("http://www.w3.org/2000/svg", "rect");
  bg.setAttribute("width", "1120"); bg.setAttribute("height", "760"); bg.setAttribute("fill", "#070A12");
  svg.insertBefore(bg, svg.firstChild);
  fs.writeFileSync(path.join(TMP, "shots") + "/" + name + ".svg", svg.outerHTML);
  console.log("wrote", name);
}

fs.mkdirSync(path.join(TMP, "shots"), { recursive: true });
setTimeout(() => { console.error("shoot: timed out"); process.exit(1); }, 90000).unref();
const { win, doc } = await boot(FIX(process.argv[2] || "n120.json"));
const live = (s) => [...doc.querySelectorAll(s)].filter((e) => !e.classList.contains("leaving"));
svgOut(doc, "1-top");

// into the biggest branch, all the way to notes
for (let i = 0; i < 4; i++) {
  const g = live("g.cl:not(.dim):not(.container)");
  if (!g.length) break;
  g.map((el) => ({ el, n: +el.querySelector(".cl-count").textContent }))
   .sort((a, b) => b.n - a.n)[0].el.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
  await sleep(1000);
  svgOut(doc, "2-depth" + (i + 1));
}
// select a note
const nd = live("g.nd");
if (nd.length) {
  nd[Math.floor(nd.length / 3)].dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
  await sleep(900);
  svgOut(doc, "3-selected");
}
process.exit(0);
