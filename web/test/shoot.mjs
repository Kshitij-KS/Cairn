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

const DARK = { "--ground":"#0b1120","--ground-2":"#0e1626","--surface":"#121a2b","--ink":"#e8edf7",
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
  P("rect", {});
  svg.querySelectorAll(".grain").forEach((e) => e.setAttribute("opacity", "0.055"));
  P(".lk", { stroke: "#8C8168", opacity: "1", "stroke-width": "1.2", fill: "none", "stroke-linecap": "round", "stroke-width": "1" });
  P(".lk.dep", { stroke: "#46402F", "stroke-width": "1.7", opacity: "1" });
  P(".proc", { fill: "none", stroke: "#46402F", "stroke-width": "1", opacity: "0.55",
               "stroke-linecap": "round" });
  svg.querySelectorAll(".cl-tissue circle").forEach((e)=>e.setAttribute("opacity","0.72"));
  P(".cl-disc", { fill: "#F3F0E7", stroke: "#8A7F63", "stroke-width": "1" });
  P(".cl-edge", { fill: "none", stroke: "#181611", "stroke-opacity": "0.20", "stroke-width": "1" });
  P(".cl-tick", { fill: "none", "stroke-width": "1", "stroke-dasharray": "1 11", opacity: "0.5" });
  P(".cl-name", { fill: "#181611", "font-family": "Georgia, serif", "font-weight": "500", stroke: "none" });
  P(".cl-count", { fill: "#6E6656", "font-family": "monospace", "letter-spacing": "0.04em",
                   stroke: "none" });
  P(".cl-mix path", { fill: "none", "stroke-width": "2.4", "stroke-linecap": "butt", opacity: "0.95" });
  P(".cl-flag", { fill: "none", stroke: "#9A6B1E", "stroke-width": "1.2", "stroke-dasharray": "3 5" });
  P(".nd-core", { stroke: "#F3F0E7", "stroke-width": "1" });
  P(".nd-rim", { fill: "none", stroke: "#181611", "stroke-opacity": "0.30", "stroke-width": "1" });
  P(".nd-bloom", { opacity: "0" });
  P(".nd-breath", { fill: "none", opacity: "0" });
  P(".nd-flag", { fill: "none", stroke: "#9A6B1E", "stroke-width": "1.3", opacity: "0" });
  P(".nd.flagged .nd-flag", { opacity: "1" });
  P(".nd-label", { fill: "#4A4438", "font-family": "sans-serif", "font-size": "11", stroke: "none" });
  P(".nd.minor .nd-label", { opacity: "0" });
  svg.querySelectorAll(".nd.faded").forEach((e) => e.setAttribute("style", "opacity:0.30"));
  P(".reticle", { stroke: "#C03A22", "stroke-width": "1.2", fill: "none", opacity: "0" });
  P(".nd.sel .reticle", { opacity: "0.95" });
  P(".nd.sel .nd-core", { stroke: "#C03A22", "stroke-width": "2.2" });
  P(".nd.sel .nd-label", { fill: "#181611", opacity: "1" });
  P(".nd.near .nd-core", { stroke: "#C03A22", "stroke-width": "1.8" });
  P(".guest-dot", { fill: "#F4F1E9", stroke: "#6E6656", "stroke-width": "1.2",
                    "stroke-dasharray": "2.5 2.5" });
  P(".guest.dep .guest-dot", { stroke: "#C03A22", "stroke-dasharray": "none" });
  P(".guest-line", { stroke: "#6E6656", "stroke-width": "1", opacity: "0.6" });
  P(".guest-label", { fill: "#6E6656", "font-family": "sans-serif", "font-size": "10.5", stroke: "none" });
  P(".cl.dim", { opacity: "0.28" });
  P(".cl.container .cl-disc", { fill: "none", stroke: "#C6BCA2", "stroke-dasharray": "2 6" });
  svg.querySelectorAll(".cl.dim .cl-name, .cl.dim .cl-count, .cl.dim .cl-mix")
     .forEach((el) => el.setAttribute("display", "none"));
  svg.querySelectorAll("filter").forEach((f) => f.remove());
  svg.querySelectorAll("[filter]").forEach((e) => e.removeAttribute("filter"));

  const bg = doc.createElementNS("http://www.w3.org/2000/svg", "rect");
  bg.setAttribute("width", "1120"); bg.setAttribute("height", "760"); bg.setAttribute("fill", "#E7E1D2");
  svg.insertBefore(bg, svg.firstChild);
  fs.writeFileSync(path.join(TMP, "shots") + "/" + name + ".svg", svg.outerHTML);
  console.log("wrote", name);
}

fs.mkdirSync(path.join(TMP, "shots"), { recursive: true });
const { win, doc } = await boot(FIX("n1020.json"));
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
