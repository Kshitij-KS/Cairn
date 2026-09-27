/* Boot the real page in jsdom against a chosen graph.json, and hand back the window so a test
 * can poke it. jsdom has no layout engine and no SVG geometry, so the few APIs the app touches
 * are stubbed HERE and nowhere else, and each stub is a documented lie we then account for. */
import { JSDOM, VirtualConsole } from "jsdom";
import fs from "node:fs";
import path from "node:path";

import { fileURLToPath } from "node:url";
const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const W = 1120, H = 760;

export async function boot(graphPath, opts = {}) {
  const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
  const css = fs.readFileSync(path.join(WEB, "style.css"), "utf8");
  const app = fs.readFileSync(path.join(WEB, "app.js"), "utf8");
  const d3src = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "node_modules/d3/dist/d3.min.js"), "utf8");
  const graph = fs.readFileSync(graphPath, "utf8");

  const vc = new VirtualConsole();
  const errors = [];
  vc.on("jsdomError", (e) => errors.push(String(e.message || e)));
  vc.on("error", (...a) => errors.push(a.map(String).join(" ")));

  const dom = new JSDOM(html.replace(/<script src="https:[^"]*"><\/script>/, ""), {
    runScripts: "dangerously", pretendToBeVisual: true, url: "https://atlas.test/" + (opts.hash || ""),
    virtualConsole: vc,
  });
  const win = dom.window, doc = win.document;
  win.__errors = errors;

  // --- stubs, each one a lie we are choosing on purpose -------------------
  // 1. no layout engine: every box is the pane, which is what the app asks for
  win.Element.prototype.getBoundingClientRect = function () {
    const id = this.id || "";
    if (id === "atlas" || this.classList?.contains("atlas"))
      return { x: 0, y: 0, left: 0, top: 0, width: W, height: H, right: W, bottom: H };
    return { x: 0, y: 0, left: 0, top: 0, width: 300, height: 170, right: 300, bottom: 170 };
  };
  Object.defineProperty(win.HTMLElement.prototype, "offsetWidth", { get() { return 300; }, configurable: true });
  Object.defineProperty(win.HTMLElement.prototype, "offsetHeight", { get() { return 170; }, configurable: true });

  // 2. no SVG geometry: path length and point-at-length are straight-line approximations,
  //    enough for the draw-on animation and the pulse to run without throwing
  win.SVGElement.prototype.getTotalLength = function () {
    const d = this.getAttribute("d") || "";
    const nums = d.match(/-?\d+(\.\d+)?/g) || [];
    if (nums.length < 4) return 0;
    const [x1, y1] = [+nums[0], +nums[1]], [x2, y2] = [+nums[nums.length - 2], +nums[nums.length - 1]];
    return Math.hypot(x2 - x1, y2 - y1) || 1;
  };
  win.SVGElement.prototype.getPointAtLength = function (l) {
    const d = this.getAttribute("d") || "";
    const nums = (d.match(/-?\d+(\.\d+)?/g) || []).map(Number);
    if (nums.length < 4) return { x: 0, y: 0 };
    const total = this.getTotalLength() || 1, t = Math.max(0, Math.min(1, l / total));
    return { x: nums[0] + (nums[nums.length - 2] - nums[0]) * t,
             y: nums[1] + (nums[nums.length - 1] - nums[1]) * t };
  };
  // 2b. d3-zoom asks an <svg> for its width.baseVal.value to find its extent; jsdom has no
  //     SVG geometry properties at all, so without this every zoom call throws. Browser-only gap.
  for (const dim of ["width", "height"]) {
    Object.defineProperty(win.SVGSVGElement.prototype, dim, {
      configurable: true,
      get() { return { baseVal: { value: dim === "width" ? W : H } }; },
    });
  }

  win.SVGElement.prototype.getScreenCTM = function () {
    return { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0, inverse: () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }) };
  };
  if (!win.SVGElement.prototype.createSVGPoint) {
    win.SVGSVGElement.prototype.createSVGPoint = function () {
      return { x: 0, y: 0, matrixTransform() { return { x: this.x, y: this.y }; } };
    };
  }

  // 3. CSS custom properties: jsdom does not cascade, so serve the token block directly
  const tokens = {};
  const root = css.slice(css.indexOf(":root {"), css.indexOf("}", css.indexOf(":root {")));
  root.replace(/(--[\w-]+):\s*([^;]+);/g, (_, k, v) => { tokens[k] = v.trim(); return ""; });
  const realCS = win.getComputedStyle.bind(win);
  win.getComputedStyle = (el, pe) => {
    const s = realCS(el, pe);
    return new Proxy(s, {
      get(t, p) {
        if (p === "getPropertyValue") return (name) => tokens[name] || t.getPropertyValue(name) || "";
        const v = t[p];
        return typeof v === "function" ? v.bind(t) : v;
      },
    });
  };

  win.matchMedia = (q) => ({
    matches: q.includes("reduced-motion") ? !!opts.reducedMotion
      : q.includes("prefers-color-scheme: light") ? !!opts.light : false,
    media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
  });
  win.fetch = async () => ({ ok: true, status: 200, json: async () => JSON.parse(graph) });
  win.requestAnimationFrame = (cb) => win.setTimeout(() => cb(win.performance.now()), 16);
  win.cancelAnimationFrame = (id) => win.clearTimeout(id);
  if (!win.HTMLDialogElement.prototype.showModal)
    win.HTMLDialogElement.prototype.showModal = function () { this.open = true; };

  // d3 transitions throw asynchronously under jsdom when they touch geometry we only approximate;
  // swallow those so a real assertion failure is not masked by transition noise
  win.addEventListener("error", (e) => { e.preventDefault?.(); });
  process.removeAllListeners("uncaughtException");
  process.on("uncaughtException", (e) => { errors.push("uncaught: " + e.message + "\n" + String(e.stack||"").split("\n").slice(1,10).join("\n")); });

  const s1 = doc.createElement("script"); s1.textContent = d3src; doc.body.appendChild(s1);
  const s2 = doc.createElement("script"); s2.textContent = app; doc.body.appendChild(s2);

  await new Promise((r) => setTimeout(r, opts.settle || 900));
  return { win, doc, dom, errors };
}

export const W_ = W, H_ = H;

/* Privacy oracle (audit 07-F5). The old checks skipped every node whose body was withheld - the
 * exact case they were meant to cover - and two of them inspected the input JSON, not the page.
 * Here the FULL build is the oracle: every string it has that the public file withholds becomes a
 * marker, and the rendered page (text AND markup, so attributes and URLs count) must contain none
 * of them. Callers must also assert markers.length > 0, so the scan has something to find. */
export function withheldMarkers(publicGraph, fullGraph) {
  const pubText = JSON.stringify(publicGraph);
  const pubById = new Map(publicGraph.nodes.map((n) => [n.id, n]));
  const out = new Set();
  const add = (s) => {
    const t = String(s || "").replace(/[`*_#>\[\]]/g, "").replace(/\s+/g, " ").trim();
    if (t.length >= 24 && !pubText.includes(t.slice(0, 40))) out.add(t.slice(0, 40));
  };
  for (const n of fullGraph.nodes) {
    const p = pubById.get(n.id);
    if (!p) { add(n.title + " "); add(n.id + " ".repeat(24)); continue; }   // omitted note: its name is secret
    if (p.body == null && n.body) for (const line of n.body.split("\n").slice(0, 60)) add(line);
    if (p.brief == null && n.brief) add(n.brief);
  }
  for (const a of fullGraph.activity || []) if (a.message) add(a.message);
  return [...out];
}

export function privacyLeaks(doc, markers) {
  const text = doc.body.textContent || "";
  const html = doc.documentElement.outerHTML || "";
  return markers.filter((m) => text.includes(m) || html.includes(m));
}
