// The sky's geometry: where every note sits, as a pure function of the notes (no randomness, no
// clock), so the same memory always draws the same sky and a link always lands on the same spot.
//
// Each group is a sunflower (Vogel's phyllotaxis): note i sits at radius C*sqrt(i+0.5) and angle
// i*golden-angle, most important first, at the centre. That spiral packs points evenly with a
// nearest-neighbour distance close to C, so with C well above two dot radii no two dots can
// touch, at any size of group. Nothing ever expands, so nothing can ever overlap.
import { packSiblings } from "d3-hierarchy";
import { groups, type Arrangement, type Group, type Model, type Note } from "./data";

export const SPIRAL = 12.5;       // Vogel scale: the nearest two notes in a group sit ~19 world units apart (measured min 19.3 over 3,100)
export const DOT_MAX = 6.5;       // the largest dot radius, in world units at zoom 1
export const GROUP_PAD = 58;      // clear space around a group: room for its name
const GOLDEN = Math.PI * (3 - Math.sqrt(5));

export interface SkyGroup { key: string; label: string; sub: string | null; x: number; y: number; R: number; notes: Note[] }
export interface SkyLayout {
  pos: Map<string, { x: number; y: number }>;
  groups: SkyGroup[];
  bounds: { x0: number; y0: number; x1: number; y1: number };
}

export const dotRadius = (observations: number) => 2.6 + Math.min(3.9, Math.sqrt(Math.max(0, observations)) * 0.9);
const groupRadius = (n: number) => SPIRAL * Math.sqrt(Math.max(1, n) - 0.5) + DOT_MAX + 6;

export function sunflower(i: number) {
  const r = SPIRAL * Math.sqrt(i + 0.5), a = i * GOLDEN;
  return { x: r * Math.cos(a), y: r * Math.sin(a) };
}

export function skyLayout(m: Model, arrangement: Arrangement, visible: (n: Note) => boolean): SkyLayout {
  const gs: Group[] = groups(m, arrangement, visible);
  const circles = gs.map((g) => ({ g, r: groupRadius(g.notes.length) + GROUP_PAD, x: 0, y: 0 }));
  if (arrangement === "area") {
    // Biggest first, so the largest areas sit near the middle of the pack.
    const order = [...circles].sort((a, b) => b.r - a.r || a.g.key.localeCompare(b.g.key));
    packSiblings(order);
  } else {
    // Months read left to right, oldest first, on shelves about as wide as the sky is tall.
    const chron = [...circles].reverse();
    const area = chron.reduce((s, c) => s + (2 * c.r) ** 2, 0);
    const width = Math.max(900, Math.sqrt(area) * 1.5);
    let x = 0, y = 0, row = 0;
    for (const c of chron) {
      if (x > 0 && x + 2 * c.r > width) { x = 0; y += 2 * row; row = 0; }
      c.x = x + c.r; c.y = y + c.r; x += 2 * c.r; row = Math.max(row, c.r);
    }
  }
  const pos = new Map<string, { x: number; y: number }>();
  const out: SkyGroup[] = [];
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const c of circles) {
    const R = c.r - GROUP_PAD;
    c.g.notes.forEach((n, i) => {
      const p = sunflower(i);
      pos.set(n.id, { x: c.x + p.x, y: c.y + p.y });
    });
    out.push({ key: c.g.key, label: c.g.label, sub: c.g.sub, x: c.x, y: c.y, R, notes: c.g.notes });
    x0 = Math.min(x0, c.x - c.r); y0 = Math.min(y0, c.y - c.r); x1 = Math.max(x1, c.x + c.r); y1 = Math.max(y1, c.y + c.r);
  }
  if (!out.length) { x0 = y0 = -100; x1 = y1 = 100; }
  // Centre the sky on the origin.
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  for (const p of pos.values()) { p.x -= cx; p.y -= cy; }
  for (const g of out) { g.x -= cx; g.y -= cy; }
  return { pos, groups: out, bounds: { x0: x0 - cx, y0: y0 - cy, x1: x1 - cx, y1: y1 - cy } };
}

/** Where a selected note's relations stand while it is in focus, as offsets in SCREEN pixels from
 *  the note (the camera centres it): what it relies on in a bowed column to the left, what relies
 *  on it to the right, see-also stacked below. Offsets in screen space mean the spacing, and so
 *  the room for each name, is the same at every zoom. */
export interface LineageSlot { id: string; side: "on" | "by" | "see"; dx: number; dy: number }
export const LINEAGE_CAP = 14;
export const NARROW = 640;
export function lineageSlots(on: string[], by: string[], see: string[], vw: number, vh: number) {
  if (vw < NARROW) return narrowSlots(on, by, see, vw, vh);
  const side = Math.min(320, Math.max(150, vw * 0.27));
  const rows = Math.max(Math.min(on.length, LINEAGE_CAP), Math.min(by.length, LINEAGE_CAP), 1);
  const seeN = Math.min(see.length, 8);
  // Rows shrink from 34px towards 24px before anything is left out.
  const avail = vh - 150 - seeN * 26;
  const gap = Math.max(24, Math.min(34, avail / rows));
  const slots: LineageSlot[] = [];
  // Each column stands on an arc around the note, like a bracket: "( note )". Rows keep an even
  // vertical pitch; the arc's radius is wide enough that the ends never swing past 60 degrees.
  const column = (ids: string[], sgn: -1 | 1, s: "on" | "by") => {
    const list = ids.slice(0, LINEAGE_CAP);
    const half = ((list.length - 1) / 2) * gap;
    const rho = Math.max(side, half / Math.sin(Math.PI / 3));
    list.forEach((id, i) => {
      const dy = (i - (list.length - 1) / 2) * gap;
      const dx = Math.sqrt(Math.max(0, rho * rho - dy * dy)) - (rho - side);
      slots.push({ id, side: s, dx: sgn * dx, dy });
    });
  };
  column(on, -1, "on");
  column(by, 1, "by");
  const top = (rows * gap) / 2 + 46;
  see.slice(0, 8).forEach((id, i) => slots.push({ id, side: "see", dx: 18, dy: top + i * 26 }));
  return { slots, gap, hidden: { on: Math.max(0, on.length - LINEAGE_CAP), by: Math.max(0, by.length - LINEAGE_CAP), see: Math.max(0, see.length - 8) }, narrow: false };
}

/** On a phone there is no room for three columns: the note sits at the top and its relations
 *  hang below it in one list, section by section, each name running to the right of its dot. */
function narrowSlots(on: string[], by: string[], see: string[], vw: number, vh: number) {
  const cap = Math.max(3, Math.floor((vh - 170) / 28 / 3));
  const slots: LineageSlot[] = [];
  const x = -vw / 2 + 34;
  let y = 64;
  const section = (ids: string[], side: "on" | "by" | "see") => {
    if (!ids.length) return;
    y += 26;                                      // room for the section's heading
    ids.slice(0, cap).forEach((id) => { slots.push({ id, side, dx: x, dy: y }); y += 28; });
    y += 8;
  };
  section(on, "on"); section(by, "by"); section(see, "see");
  return { slots, gap: 28, hidden: { on: Math.max(0, on.length - cap), by: Math.max(0, by.length - cap), see: Math.max(0, see.length - cap) }, narrow: true };
}
