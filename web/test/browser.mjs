/* The checks jsdom cannot make, in a REAL browser: laid-out boxes (do the grid's chips and cards
 * ever overlap?), real text widths (do the sky's names collide?), and the deployed
 * Content-Security-Policy (does the page run under it, with no violation?).
 *
 * It needs a Chrome or Chromium. Set CHROME_PATH, or it looks in the usual places. With no browser
 * it prints SKIP and exits 0: an unrun check is reported as unrun, never as passed. */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import { labelProblems, crowding } from "./sky-checks.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(HERE, "..");
const candidates = [process.env.CHROME_PATH, "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].filter(Boolean);
const exe = candidates.find((p) => { try { return fs.statSync(p).isFile(); } catch { return false; } });
if (!exe) { console.log("SKIP browser checks: no Chrome found (set CHROME_PATH to run them)"); process.exit(0); }

// Serve web/ with the headers vercel.json deploys, so the CSP under test is the real one.
const vercel = JSON.parse(fs.readFileSync(path.join(WEB, "vercel.json"), "utf8"));
const headers = Object.fromEntries(vercel.headers.find((h) => h.source === "/(.*)").headers.map((h) => [h.key, h.value]));
const fixtures = path.join(HERE, "fixtures");
const server = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  let file = u.pathname === "/" ? path.join(WEB, "index.html") : path.join(WEB, u.pathname);
  const m = u.pathname.match(/^\/data\/([\w.-]+\.json)$/);
  if (m && m[1] !== "graph.json") file = path.join(fixtures, m[1]);
  if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { ...headers, "Content-Type": file.endsWith(".json") ? "application/json" : "text/html; charset=utf-8" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

let pass = 0, fail = 0;
const ok = (n, c, d = "") => { c ? pass++ : fail++; console.log((c ? "  PASS " : "  FAIL ") + n + (d ? "  " + d : "")); };
const browser = await chromium.launch({ executablePath: exe, headless: true, args: ["--no-sandbox", ...(process.env.CHROME_ARGS || "").split(" ").filter(Boolean)] });

async function open(url, vp) {
  const { width, height, isMobile } = vp;
  const ctx = await browser.newContext({ viewport: { width, height }, isMobile: !!isMobile, hasTouch: !!isMobile });
  const p = await ctx.newPage();
  const problems = [];
  p.on("console", (msg) => { if (msg.type() === "error") problems.push(msg.text()); });
  p.on("pageerror", (e) => problems.push("pageerror: " + e.message));
  await p.goto(base + url, { waitUntil: "networkidle" });
  await new Promise((r) => setTimeout(r, 600));
  // Fonts come from Google; a sandbox without the network cannot load them, and that is not a bug in the page.
  const real = () => problems.filter((t) => !/fonts\.(googleapis|gstatic)\.com|Failed to load resource/.test(t));
  return { p, real };
}

const overlaps = (boxes) => {
  const out = [];
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    if (a.x < b.x + b.w - 0.5 && a.x + a.w > b.x + 0.5 && a.y < b.y + b.h - 0.5 && a.y + a.h > b.y + 0.5) out.push(a.id + " / " + b.id);
  }
  return out;
};

for (const [fx, vp] of [["graph.json", { width: 1440, height: 900 }], ["n1020.json", { width: 1440, height: 900 }], ["n1020.json", { width: 390, height: 844, isMobile: true }]]) {
  console.log(`\n=== ${fx} at ${vp.width}px ===`);
  // --- the grid: open every group fully, then measure every chip and card -------------------
  const { p, real } = await open(`?data=data/${fx}#grid:area`, vp);
  ok("boots under the deployed CSP with no violation or error", real().length === 0, real().slice(0, 2).join(" | "));
  for (let i = 0; i < 400; i++) {
    const clicked = await p.evaluate(() => { const m = document.querySelector("[data-more]"); if (m) m.click(); return !!m; });
    if (!clicked) break;
  }
  await new Promise((r) => setTimeout(r, 500));
  const geo = await p.evaluate(() => {
    const box = (el, id) => { const r = el.getBoundingClientRect(); return { id, x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: r.height }; };
    const cards = [...document.querySelectorAll("[data-group]")].map((c) => box(c, c.getAttribute("data-group")));
    const chips = [...document.querySelectorAll('[data-view="map"] [data-note]')].map((c) => ({ ...box(c, c.getAttribute("data-note")), group: c.closest("[data-group]").getAttribute("data-group") }));
    return { cards, chips };
  });
  const byGroup = new Map();
  for (const c of geo.chips) { if (!byGroup.has(c.group)) byGroup.set(c.group, []); byGroup.get(c.group).push(c); }
  let chipHits = [];
  for (const list of byGroup.values()) chipHits = chipHits.concat(overlaps(list));
  ok("grid, every group opened: no two chips overlap", geo.chips.length > 0 && chipHits.length === 0, `${geo.chips.length} chips; ${chipHits.slice(0, 2).join(", ")}`);
  ok("grid, every group opened: no two cards overlap", overlaps(geo.cards).length === 0, `${geo.cards.length} cards`);
  const cardOf = new Map(geo.cards.map((c) => [c.id, c]));
  const outside = geo.chips.filter((c) => { const k = cardOf.get(c.group); return c.x < k.x - 0.5 || c.x + c.w > k.x + k.w + 0.5 || c.y < k.y - 0.5 || c.y + c.h > k.y + k.h + 0.5; });
  ok("grid: every chip sits inside its own card", outside.length === 0, outside.slice(0, 2).map((c) => c.id).join());
  if (fx === "graph.json" && vp.width > 1000) {
    // Prove both instruments can fail: squeeze the chips together, and try an injected script.
    await p.addStyleTag({ content: '[data-view="map"] [data-note]{margin-right:-40px}' });
    const squeezed = await p.evaluate(() => [...document.querySelectorAll('[data-view="map"] [data-note]')].map((c) => { const r = c.getBoundingClientRect(); return { id: c.getAttribute("data-note"), x: r.x, y: r.y, w: r.width, h: r.height }; }));
    ok("negative: chips forced together ARE reported as overlapping", overlaps(squeezed).length > 0, `${overlaps(squeezed).length} overlaps`);
    const ran = await p.evaluate(() => { const el = document.createElement("script"); el.textContent = "window.__injected = 1"; document.body.appendChild(el); return !!window.__injected; });
    ok("negative: the deployed CSP refuses an injected inline script", ran === false && real().some((t) => /Content Security Policy/i.test(t)), real().slice(-1).join());
  }
  await p.context().close();

  // --- the sky, with real text widths ---------------------------------------------------------
  const sky = await open(`?data=data/${fx}`, vp);
  const read = () => sky.p.evaluate(() => { window.__atlasSky.settle(); return window.__atlasSky.snapshot(); });
  let s = await read();
  let lp = labelProblems(s);
  ok("sky at a distance: no name collides (real text widths)", lp.length === 0 && s.labels.length > 0, `${s.labels.length} names; ${lp.slice(0, 2).join("; ")}`);
  ok("sky: no two stars crowd", crowding(s).length === 0);
  for (let i = 0; i < 10 && s.k < 1.1; i++) { await sky.p.evaluate(() => document.querySelector('[aria-label="Zoom in"]').click()); s = await read(); }
  lp = labelProblems(s);
  ok("sky closer in: no name collides", lp.length === 0, `${s.labels.length} names; ${lp.slice(0, 2).join("; ")}`);
  await sky.p.evaluate(() => window.__atlasSky.settle());
  const target = await sky.p.evaluate(() => {
    const s = window.__atlasSky.snapshot();
    return s.stars.find((x) => x.x > 40 && x.y > 40 && x.x < s.width - 40 && x.y < s.height - 40)?.id;
  });
  if (target) {
    const at = await sky.p.evaluate((id) => { const s = window.__atlasSky.snapshot().stars.find((x) => x.id === id); const r = document.querySelector("[data-view=sky] canvas").getBoundingClientRect(); return { x: r.x + s.x, y: r.y + s.y }; }, target);
    await sky.p.mouse.click(at.x, at.y);
    await new Promise((r) => setTimeout(r, 200));
    s = await read();
    lp = labelProblems(s);
    ok("sky in focus: a real click chooses the star under the pointer", s.selected === target, `${s.selected} vs ${target}`);
    ok("sky in focus: no name collides", lp.length === 0, lp.slice(0, 2).join("; "));
    const named = new Set(s.labels.map((l) => l.id));
    const all = [...s.lineage.on, ...s.lineage.by, ...s.lineage.see];
    ok("sky in focus: every neighbour on stage is named", all.every((id) => named.has(id)), `${all.filter((id) => !named.has(id)).length} of ${all.length} unnamed`);
  }
  ok("sky: no console error while driving it", sky.real().length === 0, sky.real().slice(0, 2).join(" | "));
  await sky.p.context().close();
}

await browser.close();
server.close();
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
