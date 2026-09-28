/* The sky's geometry checks, shared by sky.mjs and negative.mjs. */
const DOT_MAX = 6.5;                   // web/app/src/lib/sky.ts

export const snap = (win) => { win.__atlasSky.settle(); return win.__atlasSky.snapshot(); };

/** Names that touch another name, or cover a star that is not their own. Empty is a pass. */
export function labelProblems(s) {
  const out = [];
  const L = s.labels;
  for (let i = 0; i < L.length; i++) for (let j = i + 1; j < L.length; j++) {
    const a = L[i], b = L[j];
    if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) out.push(`"${a.id}" overlaps "${b.id}"`);
  }
  const shown = new Map(s.stars.map((x) => [x.id, x]));
  const obstacles = s.focus > 0.5 ? s.stars.filter((x) => x.side || x.id === s.selected) : s.stars.filter((x) => x.a >= 0.3);
  for (const l of L) {
    if (l.kind === "centre" || l.kind === "hover" || l.kind === "group") continue;
    for (const d of obstacles) {
      if (d.id === l.id) continue;
      const nx = Math.max(l.x, Math.min(d.x, l.x + l.w)), ny = Math.max(l.y, Math.min(d.y, l.y + l.h));
      if ((nx - d.x) ** 2 + (ny - d.y) ** 2 < d.r ** 2) { out.push(`"${l.id}" covers the star of "${d.id}"`); break; }
    }
    if (l.kind !== "group" && !l.id.startsWith("head:") && !shown.has(l.id)) out.push(`"${l.id}" is named but not drawn`);
  }
  return out;
}

/** Stars closer (in world units) than two of the biggest dots: the sunflower promise. */
export function crowding(s) {
  const pts = s.stars.map((x) => ({ id: x.id, x: x.x / s.k, y: x.y / s.k }));
  const cell = 2 * DOT_MAX, grid = new Map(), bad = [];
  for (const p of pts) {
    const gx = Math.floor(p.x / cell), gy = Math.floor(p.y / cell);
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      for (const q of grid.get(`${gx + dx},${gy + dy}`) || []) {
        if (Math.hypot(p.x - q.x, p.y - q.y) < 2 * DOT_MAX) bad.push(`${p.id} ~ ${q.id}`);
      }
    }
    const k = `${gx},${gy}`;
    if (!grid.has(k)) grid.set(k, []);
    grid.get(k).push(p);
  }
  return bad;
}

