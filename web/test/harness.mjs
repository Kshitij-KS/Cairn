/* Boot the BUILT page (web/index.html, exactly what ships) in jsdom against a chosen graph.json,
 * and hand back the window so a test can drive it. jsdom has no layout engine and does not run
 * module scripts, so the few gaps are filled HERE and nowhere else, each one a documented lie:
 *
 *  1. The app script is a <script type="module">, which jsdom skips. It is lifted out of the page
 *     and run as a classic script at the end of <body>, inside a function so its top-level names
 *     stay private, in strict mode as a module would be. A module runs after parsing, and so
 *     does this.
 *  2. ResizeObserver, matchMedia, scrollIntoView and the clipboard do not exist in jsdom.
 *  3. fetch serves the chosen graph file (or fails, when a test asks it to).
 *  4. Every box measures 0x0, so page geometry (card overlap) is NOT checked here: that is what
 *     test/browser.mjs does, in a real browser.
 *  5. There is no canvas. getContext("2d") returns a recorder that draws nothing and measures
 *     text at 6.5px a character. The sky's own geometry (where each star and each name goes) is
 *     plain arithmetic, so it IS checked here, through window.__atlasSky.snapshot().
 */
import { JSDOM, VirtualConsole } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export function builtPage() {
  const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
  const m = html.match(/<script type="module">([\s\S]*?)<\/script>/);
  if (!m) throw new Error("web/index.html has no inline module script: is it a fresh build?");
  return { html: html.replace(m[0], ""), app: m[1] };
}

export async function boot(graphPath, opts = {}) {
  const { html, app } = builtPage();
  const graph = graphPath ? fs.readFileSync(graphPath, "utf8") : null;
  const vc = new VirtualConsole();
  const errors = [];
  vc.on("jsdomError", (e) => { const t = String(e.message || e); if (!/Could not parse CSS stylesheet/.test(t)) errors.push(t); });
  vc.on("error", (...a) => errors.push(a.map(String).join(" ")));

  const dom = new JSDOM(html, {
    runScripts: "dangerously", pretendToBeVisual: true,
    url: "https://atlas.test/" + (opts.search || "") + (opts.hash || ""), virtualConsole: vc,
  });
  const win = dom.window, doc = win.document;
  win.__errors = errors;
  if (opts.lastVisit) win.localStorage.setItem("atlas-last-visit", opts.lastVisit);

  win.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  win.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} takeRecords() { return []; } };
  win.matchMedia = (q) => ({
    matches: q.includes("reduced-motion") ? !!opts.reducedMotion : q.includes("prefers-color-scheme: dark") ? !!opts.dark : false,
    media: q, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent() { return false; },
  });
  win.Element.prototype.scrollIntoView = function () {};
  const calls = { fillText: 0 };
  win.__canvasCalls = calls;
  win.HTMLCanvasElement.prototype.getContext = function () {
    const store = { canvas: this };
    return new Proxy(store, {
      get(t, p) {
        if (p in t) return t[p];
        if (p === "measureText") return (txt) => ({ width: String(txt).length * 6.5 });
        if (p === "createRadialGradient" || p === "createLinearGradient") return () => ({ addColorStop() {} });
        if (p === "fillText") return () => { calls.fillText++; };
        return () => {};
      },
      set(t, p, v) { t[p] = v; return true; },
    });
  };
  win.HTMLElement.prototype.hasPointerCapture = () => false;
  win.HTMLElement.prototype.releasePointerCapture = () => {};
  const copied = [];
  Object.defineProperty(win.navigator, "clipboard", { value: { writeText: async (t) => { copied.push(t); } }, configurable: true });
  win.__copied = copied;
  const fetched = [];
  win.fetch = async (url) => {
    fetched.push(String(url));
    if (opts.fetchFails) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => JSON.parse(opts.graphText ?? graph) };
  };
  win.__fetched = fetched;

  win.addEventListener("error", (e) => { errors.push("window error: " + (e.message || e.error)); });
  const s = doc.createElement("script");
  s.textContent = '(function(){"use strict";\n' + app + "\n})();";
  doc.body.appendChild(s);
  await settle(win, opts.settle || 400);
  return { win, doc, dom, errors };
}

// jsdom tears a window down while a queued task of its own still reads window.location; that
// throws from jsdom's internals after the test is over. Only that exact teardown error is
// swallowed; any other uncaught error still fails the run.
process.on("uncaughtException", (e) => {
  if (/reading '_location'/.test(String(e && e.message)) && /jsdom[\\/]lib[\\/]jsdom[\\/]browser[\\/]Window\.js/.test(String(e.stack))) return;
  console.error(e); process.exit(2);
});

export const settle = (win, ms = 120) => new Promise((r) => win.setTimeout(r, ms));

/** React listens at the root for real event types; a bare .click() is fine, but keys and
 *  double-clicks need the full event. */
export function key(win, target, k, mods = {}) {
  target.dispatchEvent(new win.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...mods }));
}
export function dblclick(win, el) {
  el.dispatchEvent(new win.MouseEvent("dblclick", { bubbles: true, cancelable: true, detail: 2 }));
}
/** Type into a React-controlled input: set the value through the native setter, then fire input. */
export function typeInto(win, input, text) {
  const set = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, "value").set;
  set.call(input, text);
  input.dispatchEvent(new win.Event("input", { bubbles: true }));
}

/* ----------------------------- page readers -----------------------------
 * The assertions compare what the PAGE shows with what the GRAPH says, computed here from the
 * raw edges, never through the app's own model: a checker that reuses the code under test
 * agrees with it by construction. */

export function expectedLineage(graph, id) {
  const ids = new Set(graph.nodes.map((n) => n.id));
  const on = new Set(), by = new Set(), rel = new Set();
  for (const e of graph.edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    if (e.dependency) {
      if (e.source === id && e.target !== id) on.add(e.target);
      if (e.target === id && e.source !== id) by.add(e.source);
    }
  }
  for (const e of graph.edges) {
    if (!ids.has(e.source) || !ids.has(e.target) || e.dependency) continue;
    const other = e.source === id ? e.target : e.target === id ? e.source : null;
    if (other && other !== id && !on.has(other) && !by.has(other)) rel.add(other);
  }
  return { reliesOn: on, reliedOnBy: by, related: rel };
}

export function shownLineage(doc) {
  const col = (side) => new Set([...doc.querySelectorAll(`[data-lineage="${side}"][data-present]`)].map((b) => b.getAttribute("data-note")));
  return { reliesOn: col("left"), reliedOnBy: col("right"), related: col("below") };
}

export const sameSet = (a, b) => a.size === b.size && [...a].every((x) => b.has(x));

/** Every note is on the map exactly once, or counted in its group's "+N more": the partition
 *  the whole design rests on. Returns the problems found; an empty list is a pass. */
export function partitionProblems(doc, graph, hidden = new Set()) {
  const problems = [];
  const visible = graph.nodes.filter((n) => !hidden.has(n.level));
  const chips = [...doc.querySelectorAll('[data-view="map"] [data-note]')].map((c) => c.getAttribute("data-note"));
  const seen = new Set();
  for (const c of chips) { if (seen.has(c)) problems.push("drawn twice: " + c); seen.add(c); }
  let folded = 0;
  for (const b of doc.querySelectorAll("[data-more]")) {
    const n = +((b.textContent || "").match(/\+(\d+) more/) || [])[1];
    if (!Number.isFinite(n)) problems.push("unreadable more pill: " + b.textContent);
    else folded += n;
  }
  if (seen.size + folded !== visible.length) problems.push(`shown ${seen.size} + folded ${folded} != ${visible.length} visible notes`);
  const ids = new Set(visible.map((n) => n.id));
  for (const c of seen) if (!ids.has(c)) problems.push("not a visible note: " + c);
  return problems;
}

/* Privacy oracle (audit 07-F5). The old checks skipped every node whose body was withheld - the
 * exact case they were meant to cover - and two of them inspected the input JSON, not the page.
 * Here the FULL build is the oracle: every string it has that the public file withholds becomes a
 * marker, and the rendered page (text AND markup, so attributes and URLs count) must contain none
 * of them. Callers must also assert markers.length > 0, so the scan has something to find. */
export function withheldMarkers(publicGraph, fullGraph) {
  const pubText = JSON.stringify(publicGraph);
  const pubById = new Map(publicGraph.nodes.map((n) => [n.id, n]));
  const out = new Set();
  const clean = (s) => String(s || "").replace(/[`*_#>\[\]]/g, "").replace(/\s+/g, " ").trim();
  // Long strings (body lines, briefs) are matched as substrings. A NAME is matched as a whole
  // word whatever its length: the old 24-character floor meant "Acme Deal" was never a marker,
  // so a leaked restricted title could not be caught (recheck 07-F5).
  const add = (s) => {
    const t = clean(s);
    if (t.length >= 24 && !pubText.includes(t.slice(0, 40))) out.add(t.slice(0, 40));
  };
  const addName = (s) => {
    const t = clean(s);
    if (t.length >= 3 && !wordIn(pubText, t)) out.add(t);
  };
  for (const n of fullGraph.nodes) {
    const p = pubById.get(n.id);
    if (!p) { addName(n.title); addName(n.id); continue; }   // omitted note, or a withheld title: its name is secret
    if (p.body == null && n.body) for (const line of n.body.split("\n").slice(0, 60)) add(line);
    if (p.brief == null && n.brief) add(n.brief);
  }
  for (const a of fullGraph.activity || []) if (a.message) add(a.message);
  return [...out];
}

/** How many notes of the full build the public file leaves out (or renames): the denominator the
 * restricted-name check must not run with at zero. */
export function omittedCount(publicGraph, fullGraph) {
  const ids = new Set(publicGraph.nodes.map((n) => n.id));
  return fullGraph.nodes.filter((n) => !ids.has(n.id)).length;
}

function wordIn(text, t) {
  const esc = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp("(^|[^\\p{L}\\p{N}_])" + esc + "($|[^\\p{L}\\p{N}_])", "iu").test(text);
}

export function privacyLeaks(doc, markers) {
  const text = doc.body.textContent || "";
  const html = doc.documentElement.outerHTML || "";
  return markers.filter((m) => (m.length >= 24 ? (text.includes(m) || html.includes(m)) : (wordIn(text, m) || wordIn(html, m))));
}
