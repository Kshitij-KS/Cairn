// The sky's renderer: one <canvas>, a camera, and tweens. Everything drawn is a function of the
// memory, the camera and the clock; nothing random (the starfield comes from a fixed seed).
//
// Motion follows three rules. Every move is spatially honest: a note that leaves its group to
// stand beside the one you chose flies there from where it was, and flies back. The camera moves
// with a smooth zoom (van Wijk and Nuij), pulling out a little on long journeys the way a
// cinematographer would. And motion can always be interrupted: grab the sky mid-flight and the
// flight stops where it is.
import { select, type Selection } from "d3-selection";
import { zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from "d3-zoom";
import { interpolateZoom } from "d3-interpolate";
import { easeCubicInOut } from "d3-ease";
import { freshnessLevelColour, lineage, type Arrangement, type Level, type Model, type Note } from "@/lib/data";
import { dotRadius, lineageSlots, skyLayout, type SkyGroup, type SkyLayout } from "@/lib/sky";

type Side = "on" | "by" | "see";
interface Star { n: Note; hx: number; hy: number; x: number; y: number; sx: number; sy: number; tx: number; ty: number;
  a: number; sa: number; ta: number; r: number; colour: string; delay: number; side: Side | null; gone: boolean }
export interface LabelBox { id: string; kind: "group" | "centre" | Side | "hover" | "note"; x: number; y: number; w: number; h: number }
export interface SkySnapshot {
  width: number; height: number; k: number; selected: string | null; focus: number;
  stars: { id: string; x: number; y: number; r: number; a: number; side: Side | null }[];
  labels: LabelBox[];
  lineage: { on: string[]; by: string[]; see: string[] }; hidden: { on: number; by: number; see: number };
  groups: number; animating: boolean;
}
export interface SkyCallbacks {
  hover: (id: string | null, x: number, y: number) => void;
  select: (id: string | null) => void;
}

const TOKENS = ["--bg", "--bg-subtle", "--fg", "--fg-2", "--muted", "--faint", "--l0", "--l1", "--l2", "--l3", "--flag", "--edge", "--edge-dep"];
const FALLBACK: Record<string, string> = { "--bg": "#09090b", "--bg-subtle": "#0f0f12", "--fg": "#fafafa", "--fg-2": "#d4d4d8", "--muted": "#a1a1aa",
  "--faint": "#71717a", "--l0": "#60a5fa", "--l1": "#34d399", "--l2": "#fbbf24", "--l3": "#fb7185", "--flag": "#fbbf24",
  "--edge": "rgba(255,255,255,.22)", "--edge-dep": "rgba(255,255,255,.5)" };

interface Cubic { ax: number; ay: number; c1x: number; c1y: number; c2x: number; c2y: number; bx: number; by: number }
function cpoint(c: Cubic, t: number) {
  const u = 1 - t, a = u * u * u, b = 3 * u * u * t, d = 3 * u * t * t, e = t * t * t;
  return { x: a * c.ax + b * c.c1x + d * c.c2x + e * c.bx, y: a * c.ay + b * c.c1y + d * c.c2y + e * c.by };
}
const easeQuintOut = (t: number) => 1 - Math.pow(1 - t, 5);
function lcg(seed: number) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

export class SkyEngine {
  private ctx: CanvasRenderingContext2D | null;
  private sel: Selection<HTMLCanvasElement, unknown, null, undefined>;
  private zb: ZoomBehavior<HTMLCanvasElement, unknown>;
  private t: ZoomTransform = zoomIdentity;
  private W = 800; private H = 600; private dpr = 1;
  private m: Model | null = null;
  private layout: SkyLayout | null = null;
  private stars = new Map<string, Star>();
  private list: Star[] = [];
  private tokens: Record<string, string> = { ...FALLBACK };
  private dark = true;
  private colourMode: "level" | "freshness" = "level";
  private selected: string | null = null;
  private hovered: string | null = null;
  private slots: { on: string[]; by: string[]; see: string[] } = { on: [], by: [], see: [] };
  private hiddenCounts = { on: 0, by: 0, see: 0 };
  private focus = 0; private focusFrom = 0; private focusTo = 0;
  private tween: { t0: number; dur: number } | null = null;
  private flight: { t0: number; dur: number; i: ReturnType<typeof interpolateZoom> } | null = null;
  private drawOn = { t0: 0 };
  private preFocus: ZoomTransform | null = null;
  private raf = 0; private dirty = true; private running = false;
  private labels: LabelBox[] = [];
  private widths = new Map<string, number>();
  private starfield: { x: number; y: number; r: number; tw: number }[] = [];
  private reduced: boolean;
  private destroyed = false;
  private first = true;
  /** 0..1: how far the names of a focus have faded in. They wait until the notes have nearly
   *  arrived, so text never rides along with a moving dot. */
  private namesIn = 1;
  /** The same for group names and glows after a rearrangement: the old ones cannot fade out
   *  (they are gone), so the new ones wait until the stars have reached them. */
  private groupsIn = 1; private arranging = false;
  private narrow = false;

  constructor(private canvas: HTMLCanvasElement, private cb: SkyCallbacks, reduced: boolean) {
    this.reduced = reduced;
    let ctx: CanvasRenderingContext2D | null = null;
    try { ctx = canvas.getContext("2d"); } catch { ctx = null; }
    this.ctx = ctx;
    const rnd = lcg(20260928);
    for (let i = 0; i < 240; i++) this.starfield.push({ x: rnd(), y: rnd(), r: 0.3 + rnd() * 0.9, tw: rnd() * Math.PI * 2 });
    this.sel = select(canvas);
    this.zb = zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([0.06, 6])
      .on("start", (e) => { if (e.sourceEvent) this.flight = null; })
      .on("zoom", (e) => { this.t = e.transform; this.kick(); });
    this.sel.call(this.zb).on("dblclick.zoom", null);
    canvas.addEventListener("pointermove", this.onMove);
    canvas.addEventListener("pointerleave", this.onLeave);
    canvas.addEventListener("click", this.onClick);
    this.readTokens();
    this.resize();
  }

  destroy() {
    this.destroyed = true;
    cancelAnimationFrame(this.raf);
    this.sel.on(".zoom", null);
    this.canvas.removeEventListener("pointermove", this.onMove);
    this.canvas.removeEventListener("pointerleave", this.onLeave);
    this.canvas.removeEventListener("click", this.onClick);
  }

  // ------------------------------------------------------------------ inputs from the app

  readTokens() {
    let cs: CSSStyleDeclaration | null = null;
    try { cs = getComputedStyle(document.documentElement); } catch { cs = null; }
    for (const k of TOKENS) {
      const v = cs?.getPropertyValue(k).trim();
      this.tokens[k] = v || FALLBACK[k];
    }
    const bg = this.tokens["--bg"];
    this.dark = !/^#f|^#e|^rgb\(2[0-9]{2}/i.test(bg);
    this.recolour();
  }

  setReduced(r: boolean) { this.reduced = r; this.kick(); }

  resize() {
    const r = this.canvas.parentElement?.getBoundingClientRect();
    const w = Math.max(320, Math.round(r?.width || this.canvas.clientWidth || 960));
    const h = Math.max(360, Math.round(r?.height || this.canvas.clientHeight || 620));
    this.dpr = Math.min(2, (typeof window !== "undefined" && window.devicePixelRatio) || 1);
    if (w !== this.W || h !== this.H) {
      this.W = w; this.H = h;
      this.canvas.width = Math.round(w * this.dpr); this.canvas.height = Math.round(h * this.dpr);
      this.canvas.style.width = w + "px"; this.canvas.style.height = h + "px";
      this.zb.extent([[0, 0], [w, h]]);
      if (this.selected) this.placeFocus(false);
    }
    this.kick();
  }

  setData(m: Model, arrangement: Arrangement, hidden: Set<Level>, colour: "level" | "freshness") {
    const fresh = this.m !== m;
    this.m = m;
    this.colourMode = colour;
    this.layout = skyLayout(m, arrangement, (n) => !hidden.has(n.level));
    const now = performance.now();
    const cx = 0, cy = 0;
    const maxD = Math.max(1, ...[...this.layout.pos.values()].map((p) => Math.hypot(p.x - cx, p.y - cy)));
    for (const s of this.stars.values()) s.gone = true;
    for (const n of m.g.nodes) {
      const p = this.layout.pos.get(n.id);
      if (!p) continue;
      let s = this.stars.get(n.id);
      if (!s) {
        s = { n, hx: p.x, hy: p.y, x: p.x, y: p.y, sx: p.x, sy: p.y, tx: p.x, ty: p.y, a: 0, sa: 0, ta: 1,
              r: dotRadius(n.observations), colour: "#fff", delay: 0, side: null, gone: false };
        this.stars.set(n.id, s);
      }
      s.n = n; s.hx = p.x; s.hy = p.y; s.gone = false; s.ta = 1;
      // The reveal travels outward from the middle of the sky; a rearrangement sweeps left to right.
      s.delay = this.first ? (Math.hypot(p.x, p.y) / maxD) * 520 : ((p.x - this.layout.bounds.x0) / Math.max(1, this.layout.bounds.x1 - this.layout.bounds.x0)) * 180;
    }
    for (const s of this.stars.values()) if (s.gone) { s.ta = 0; s.delay = 0; }
    this.list = [...this.stars.values()];
    this.recolour();
    if (this.selected && !this.layout.pos.has(this.selected)) this.selected = null;
    if (this.selected) this.placeFocus(!this.first);
    else { for (const s of this.list) { s.tx = s.hx; s.ty = s.hy; s.side = null; } }
    this.arranging = !this.first;
    this.startTween(now, this.first ? 1100 : 820);
    if (this.first) {
      const fit = this.fitTransform();
      if (this.reduced || this.selected) {
        if (!this.selected) this.apply(fit);
      } else {
        // Open slightly close in, then pull back to take in the whole sky.
        const k0 = fit.k * 1.9;
        this.apply(zoomIdentity.translate(this.W / 2, this.H / 2).scale(k0));
        this.flyTo(fit, 1500);
      }
      this.first = false;
    } else if (!this.selected && fresh === false) {
      this.flyTo(this.fitTransform(), 900);
    }
    this.kick();
  }

  setColour(c: "level" | "freshness") { this.colourMode = c; this.recolour(); this.kick(); }

  setSelected(id: string | null) {
    if (id === this.selected) return;
    const was = this.selected;
    if (id && (!this.stars.has(id) || this.stars.get(id)!.gone)) id = null;
    if (id && !was) this.preFocus = this.t;
    this.selected = id;
    this.hovered = null;
    if (id) this.placeFocus(true);
    else {
      for (const s of this.list) { s.tx = s.hx; s.ty = s.hy; s.side = null; s.ta = s.gone ? 0 : 1; }
      this.slots = { on: [], by: [], see: [] };
      this.focusFrom = this.focus; this.focusTo = 0;
      if (was && this.preFocus) this.flyTo(this.preFocus, 900);
      this.preFocus = null;
    }
    this.startTween(performance.now(), 900);
  }

  zoomBy(f: number) {
    const k = Math.max(0.06, Math.min(6, this.t.k * f));
    const cx = (this.W / 2 - this.t.x) / this.t.k, cy = (this.H / 2 - this.t.y) / this.t.k;
    this.flyTo(zoomIdentity.translate(this.W / 2 - cx * k, this.H / 2 - cy * k).scale(k), 320);
  }
  fit() { this.flyTo(this.fitTransform(), 800); }

  snapshot(): SkySnapshot {
    const vis = this.list.filter((s) => !s.gone);
    return {
      width: this.W, height: this.H, k: this.t.k, selected: this.selected, focus: this.focus,
      stars: vis.map((s) => { const p = this.screen(s.x, s.y); return { id: s.n.id, x: p.x, y: p.y, r: this.sr(s), a: s.a, side: s.side }; }),
      labels: this.labels.map((l) => ({ ...l })),
      lineage: { on: [...this.slots.on], by: [...this.slots.by], see: [...this.slots.see] }, hidden: { ...this.hiddenCounts },
      groups: this.layout?.groups.length || 0, animating: !!(this.tween || this.flight),
    };
  }

  /** Finish every move at once (a test, or a person who asked for no motion, wants the end). */
  settle() {
    if (this.tween) { for (const s of this.list) { s.x = s.tx; s.y = s.ty; s.a = s.ta; } this.focus = this.focusTo; this.tween = null; this.namesIn = 1; this.groupsIn = 1; this.arranging = false; }
    if (this.flight) { const v = this.flight.i(1); this.apply(this.viewToT(v)); this.flight = null; }
    this.drawOn.t0 = -1e9;
    this.list = this.list.filter((s) => !(s.gone && s.a <= 0.001));
    for (const s of [...this.stars.values()]) if (s.gone && s.a <= 0.001) this.stars.delete(s.n.id);
    this.draw(performance.now());
  }

  // ------------------------------------------------------------------ layout of a focus

  private placeFocus(animate: boolean) {
    const m = this.m, id = this.selected;
    if (!m || !id) return;
    const l = lineage(m, id);
    const alive = (x: { id: string }) => { const s = this.stars.get(x.id); return !!s && !s.gone; };
    const on = l.reliesOn.filter(alive).map((x) => x.id), by = l.reliedOnBy.filter(alive).map((x) => x.id), see = l.related.filter(alive).map((x) => x.id);
    const { slots, hidden, narrow } = lineageSlots(on, by, see, this.W, this.H);
    this.hiddenCounts = hidden;
    this.narrow = narrow;
    this.slots = { on: slots.filter((s) => s.side === "on").map((s) => s.id), by: slots.filter((s) => s.side === "by").map((s) => s.id), see: slots.filter((s) => s.side === "see").map((s) => s.id) };
    const kf = this.focusZoom();
    const c = this.stars.get(id)!;
    const bySlot = new Map(slots.map((s) => [s.id, s]));
    for (const s of this.list) {
      const slot = bySlot.get(s.n.id);
      if (s.n.id === id) { s.tx = s.hx; s.ty = s.hy; s.side = null; s.ta = 1; }
      else if (slot) { s.tx = c.hx + slot.dx / kf; s.ty = c.hy + slot.dy / kf; s.side = slot.side; s.ta = 1; }
      else { s.tx = s.hx; s.ty = s.hy; s.side = null; s.ta = s.gone ? 0 : 0.2; }
    }
    this.focusFrom = this.focus; this.focusTo = 1;
    this.drawOn.t0 = performance.now() + (animate && !this.reduced ? 380 : -1e9);
    // Centre the camera on the whole arrangement, not just the note, so the see-also row fits.
    const dys = slots.map((s) => s.dy);
    const mid = dys.length ? (Math.min(0, ...dys) + Math.max(0, ...dys)) / 2 : 0;
    const target = zoomIdentity.translate(this.W / 2 - c.hx * kf, this.H / 2 - (c.hy + mid / kf) * kf).scale(kf);
    if (animate) this.flyTo(target, 1000); else this.apply(target);
  }

  /** Close enough in that a note reads as a subject; never so close the sky is lost. */
  private focusZoom() { return Math.min(2.4, Math.max(1.7, this.t.k)); }

  // ------------------------------------------------------------------ camera

  private fitTransform(): ZoomTransform {
    const b = this.layout?.bounds || { x0: -100, y0: -100, x1: 100, y1: 100 };
    const pad = 36;
    const k = Math.max(0.06, Math.min(2.2, Math.min((this.W - pad * 2) / (b.x1 - b.x0), (this.H - pad * 2) / (b.y1 - b.y0))));
    const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2;
    return zoomIdentity.translate(this.W / 2 - cx * k, this.H / 2 - cy * k).scale(k);
  }
  private tToView(t: ZoomTransform): [number, number, number] { return [(this.W / 2 - t.x) / t.k, (this.H / 2 - t.y) / t.k, this.W / t.k]; }
  private viewToT(v: number[]): ZoomTransform { const k = this.W / v[2]; return zoomIdentity.translate(this.W / 2 - v[0] * k, this.H / 2 - v[1] * k).scale(k); }
  private apply(t: ZoomTransform) { this.zb.transform(this.sel, t); this.t = t; }

  private flyTo(target: ZoomTransform, ms: number) {
    if (this.reduced) { this.flight = null; this.apply(target); this.kick(); return; }
    const i = interpolateZoom(this.tToView(this.t), this.tToView(target));
    // Long journeys take a little longer, but never so long that it feels like waiting.
    const dur = Math.max(420, Math.min(1400, Math.max(ms * 0.6, i.duration * 0.55)));
    this.flight = { t0: performance.now(), dur, i };
    this.kick();
  }

  private startTween(now: number, dur: number) {
    for (const s of this.list) { s.sx = s.x; s.sy = s.y; s.sa = s.a; }
    this.focusFrom = this.focus;
    if (this.reduced) { this.tween = { t0: now - 1e9, dur: 1 }; } else this.tween = { t0: now, dur };
    this.kick();
  }

  // ------------------------------------------------------------------ the loop

  private kick() {
    this.dirty = true;
    if (this.running || this.destroyed) return;
    this.running = true;
    this.raf = requestAnimationFrame(this.frame);
  }

  private frame = (now: number) => {
    if (this.destroyed) return;
    let busy = false;
    if (this.flight) {
      const p = Math.min(1, (now - this.flight.t0) / this.flight.dur);
      const v = this.flight.i(easeCubicInOut(p));
      this.apply(this.viewToT(v));
      if (p >= 1) this.flight = null; else busy = true;
    }
    if (this.tween) {
      const { t0, dur } = this.tween;
      let done = true;
      for (const s of this.list) {
        const p = Math.max(0, Math.min(1, (now - t0 - s.delay) / dur));
        const e = easeQuintOut(p);
        s.x = s.sx + (s.tx - s.sx) * e; s.y = s.sy + (s.ty - s.sy) * e; s.a = s.sa + (s.ta - s.sa) * e;
        if (p < 1) done = false;
      }
      const pf = Math.max(0, Math.min(1, (now - t0) / (dur * 0.7)));
      this.groupsIn = this.arranging ? Math.max(0, Math.min(1, (now - t0 - dur * 0.45) / (dur * 0.45))) : 1;
      this.namesIn = this.focusTo === 1 ? Math.max(0, Math.min(1, (now - t0 - dur * 0.55) / (dur * 0.35))) : 1;
      this.focus = this.focusFrom + (this.focusTo - this.focusFrom) * easeQuintOut(pf);
      if (done && pf >= 1) {
        this.tween = null;
        this.namesIn = 1; this.groupsIn = 1; this.arranging = false;
        this.list = this.list.filter((s) => !(s.gone && s.a <= 0.001));
        for (const [id, s] of [...this.stars]) if (s.gone && s.a <= 0.001) this.stars.delete(id);
      } else busy = true;
    }
    // Ambient life (twinkle, breathing, particles) keeps the loop alive, but only while it is seen.
    const ambient = !this.reduced && typeof document !== "undefined" && document.visibilityState !== "hidden";
    if (busy || this.dirty || ambient) this.draw(now);
    this.dirty = false;
    if (busy || ambient) this.raf = requestAnimationFrame(this.frame);
    else this.running = false;
  };

  // ------------------------------------------------------------------ geometry helpers

  private screen(x: number, y: number) { return { x: x * this.t.k + this.t.x, y: y * this.t.k + this.t.y }; }
  private sr(s: Star) {
    const base = s.r * this.t.k;
    const inFocus = this.selected && (s.n.id === this.selected || s.side);
    const cap = inFocus ? 6.5 : this.selected ? 3.5 : 7.5;   // the sky behind a focus stays small
    return Math.max(inFocus ? 3.4 : 0.9, Math.min(cap, base)) * (s.n.id === this.selected ? 1.4 : 1);
  }
  private recolour() {
    for (const s of this.list) {
      const v = this.colourMode === "level" ? `var(--${s.n.level.toLowerCase()})` : freshnessLevelColour(s.n.age_days);
      const k = v.replace(/^var\((--[\w-]+)\)$/, "$1");
      s.colour = this.tokens[k] || this.tokens["--faint"];
    }
  }
  private hit(px: number, py: number): string | null {
    let best: string | null = null, bd = Infinity;
    for (const s of this.list) {
      if (s.gone || s.a < 0.15) continue;
      const p = this.screen(s.x, s.y);
      const d = Math.hypot(p.x - px, p.y - py);
      const reach = Math.max(9, this.sr(s) + 5);
      const pref = this.selected && (s.side || s.n.id === this.selected) ? 0.6 : 1;   // the focus wins ties
      if (d <= reach && d * pref < bd) { bd = d * pref; best = s.n.id; }
    }
    return best;
  }

  private onMove = (e: PointerEvent) => {
    if (e.buttons) return;
    const r = this.canvas.getBoundingClientRect();
    const id = this.hit(e.clientX - r.left, e.clientY - r.top);
    this.canvas.style.cursor = id ? "pointer" : "grab";
    if (id !== this.hovered) { this.hovered = id; this.kick(); }
    const s = id ? this.stars.get(id) : null;
    const p = s ? this.screen(s.x, s.y) : { x: 0, y: 0 };
    this.cb.hover(id, p.x, p.y);
  };
  private onLeave = () => { if (this.hovered) { this.hovered = null; this.kick(); } this.cb.hover(null, 0, 0); };
  private onClick = (e: MouseEvent) => {
    const r = this.canvas.getBoundingClientRect();
    const id = this.hit(e.clientX - r.left, e.clientY - r.top);
    this.cb.select(id === this.selected ? null : id);
  };

  // ------------------------------------------------------------------ drawing

  private curve(ax: number, ay: number, bx: number, by: number, bend = 0.16) {
    const mx = (ax + bx) / 2, my = (ay + by) / 2, dx = bx - ax, dy = by - ay;
    return { ax, ay, bx, by, cx: mx - dy * bend, cy: my + dx * bend };
  }

  private draw(now: number) {
    const ctx = this.ctx;
    this.labels = [];
    if (!ctx || !this.layout || !this.m) { this.placeLabelsOnly(); return; }
    const { W, H, dpr } = this;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
    ctx.fillStyle = this.tokens["--bg"];
    ctx.fillRect(0, 0, W, H);
    const tk = this.tokens, dark = this.dark, f = this.focus;

    // a faint centre-lit vignette
    const vg = ctx.createRadialGradient(W / 2, H * 0.45, 0, W / 2, H / 2, Math.max(W, H) * 0.75);
    vg.addColorStop(0, dark ? "rgba(255,255,255,0.035)" : "rgba(255,255,255,0.6)");
    vg.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = vg; ctx.fillRect(0, 0, W, H);

    // starfield, with a little parallax
    const par = 0.12, tw = !this.reduced;
    ctx.fillStyle = tk["--fg"];
    for (const st of this.starfield) {
      const x = ((st.x * W * 1.6 + this.t.x * par) % (W * 1.6) + W * 1.6) % (W * 1.6) - W * 0.3;
      const y = ((st.y * H * 1.6 + this.t.y * par) % (H * 1.6) + H * 1.6) % (H * 1.6) - H * 0.3;
      ctx.globalAlpha = (dark ? 0.22 : 0.12) * (tw ? 0.55 + 0.45 * Math.sin(now / 1400 + st.tw) : 0.8) * (1 - f * 0.5);
      ctx.beginPath(); ctx.arc(x, y, st.r, 0, Math.PI * 2); ctx.fill();
    }

    // nebulae: a soft glow for each group, tinted by its main level
    const k = this.t.k;
    for (const g of this.layout.groups) {
      const p = this.screen(g.x, g.y), R = g.R * k * 1.35 + 20;
      if (p.x + R < 0 || p.x - R > W || p.y + R < 0 || p.y - R > H) continue;
      const col = this.dominant(g);
      const gr = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, R);
      gr.addColorStop(0, col); gr.addColorStop(1, "rgba(0,0,0,0)");
      ctx.globalAlpha = (dark ? 0.11 : 0.05) * (1 - f * 0.75) * this.groupsIn;
      ctx.fillStyle = gr; ctx.beginPath(); ctx.arc(p.x, p.y, R, 0, Math.PI * 2); ctx.fill();
    }

    // the web of relations, faint: it is texture until something is chosen
    const focusIds = new Set<string>(this.selected ? [this.selected, ...this.slots.on, ...this.slots.by, ...this.slots.see] : []);
    const hv = this.hovered;
    ctx.lineCap = "round";
    // A big memory has thousands of links; each is fainter so the whole reads as a haze, not a mesh.
    const thin = Math.min(1, 14 / Math.sqrt(Math.max(1, this.m.g.edges.length)));
    for (const e of this.m.g.edges) {
      const a = this.stars.get(e.source), b = this.stars.get(e.target);
      if (!a || !b || a.a < 0.02 || b.a < 0.02) continue;
      if (this.selected && (focusIds.has(e.source) && focusIds.has(e.target)) && (e.source === this.selected || e.target === this.selected)) continue;
      const pa = this.screen(a.x, a.y), pb = this.screen(b.x, b.y);
      if (Math.max(pa.x, pb.x) < -40 || Math.min(pa.x, pb.x) > W + 40 || Math.max(pa.y, pb.y) < -40 || Math.min(pa.y, pb.y) > H + 40) continue;
      const lit = hv && !this.selected && (e.source === hv || e.target === hv);
      const base = e.dependency ? (dark ? 0.16 : 0.2) : (dark ? 0.08 : 0.1);
      ctx.globalAlpha = Math.min(a.a, b.a) * (lit ? 0.85 : base * thin * (1 - f * 0.85));
      ctx.strokeStyle = lit ? tk["--fg"] : tk["--fg-2"];
      ctx.lineWidth = lit ? 1.2 : e.dependency ? 0.8 : 0.6;
      const c = this.curve(pa.x, pa.y, pb.x, pb.y, 0.12);
      ctx.beginPath(); ctx.moveTo(c.ax, c.ay); ctx.quadraticCurveTo(c.cx, c.cy, c.bx, c.by); ctx.stroke();
    }

    // every star outside the focus
    const breath = this.reduced ? 0 : (Math.sin(now / 900) + 1) / 2;
    for (const s of this.list) {
      if (s.a < 0.01 || focusIds.has(s.n.id)) continue;
      this.dot(ctx, s, s.n.id === hv, breath);
    }

    if (f > 0.001 && this.selected) this.drawFocus(ctx, now, f, breath);
    this.drawLabels(ctx, f);
  }

  private dominant(g: SkyGroup) {
    const c: Record<string, number> = {};
    for (const n of g.notes) c[n.level] = (c[n.level] || 0) + 1;
    const top = Object.entries(c).sort((a, b) => b[1] - a[1])[0]?.[0] || "L0";
    return this.tokens["--" + top.toLowerCase()];
  }

  private dot(ctx: CanvasRenderingContext2D, s: Star, hot: boolean, breath: number) {
    const p = this.screen(s.x, s.y);
    if (p.x < -20 || p.x > this.W + 20 || p.y < -20 || p.y > this.H + 20) return;
    const r = this.sr(s) * (hot ? 1.3 : 1);
    ctx.fillStyle = s.colour;
    if (r > 2.2 || hot) {
      ctx.globalAlpha = s.a * (hot ? 0.3 : 0.12);
      ctx.beginPath(); ctx.arc(p.x, p.y, r * 2.1, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = s.a;
    ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
    if (s.n.review_needed && r > 1.8) {
      ctx.strokeStyle = this.tokens["--flag"]; ctx.lineWidth = 1.3; ctx.globalAlpha = s.a;
      ctx.beginPath(); ctx.arc(p.x, p.y, r + 2.6, 0, Math.PI * 2); ctx.stroke();
    }
    if ((s.n.age_days ?? 999) <= 7 && r > 1.6 && breath) {
      ctx.strokeStyle = s.colour; ctx.lineWidth = 1; ctx.globalAlpha = s.a * 0.5 * (1 - breath);
      ctx.beginPath(); ctx.arc(p.x, p.y, r + 2 + breath * 6, 0, Math.PI * 2); ctx.stroke();
    }
  }

  private drawFocus(ctx: CanvasRenderingContext2D, now: number, f: number, breath: number) {
    const c = this.stars.get(this.selected!);
    if (!c) return;
    const { W, H } = this, tk = this.tokens;
    // Pull the rest of the sky back behind a veil, so the focus reads like a stage.
    const pc = this.screen(c.x, c.y);
    const veil = ctx.createRadialGradient(pc.x, pc.y, 40, pc.x, pc.y, Math.max(W, H) * 0.8);
    veil.addColorStop(0, tk["--bg"]); veil.addColorStop(1, tk["--bg"]);
    ctx.globalAlpha = 0.72 * f; ctx.fillStyle = veil; ctx.fillRect(0, 0, W, H);
    const spot = ctx.createRadialGradient(pc.x, pc.y, 0, pc.x, pc.y, Math.min(W, H) * 0.55);
    spot.addColorStop(0, c.colour); spot.addColorStop(1, "rgba(0,0,0,0)");
    ctx.globalAlpha = (this.dark ? 0.1 : 0.07) * f; ctx.fillStyle = spot; ctx.fillRect(0, 0, W, H);

    // column headings, aligned with the edge the names hang from
    const col = (ids: string[]) => {
      const ss = ids.map((i) => this.stars.get(i)).filter(Boolean) as Star[];
      if (!ss.length) return null;
      const ps = ss.map((q) => ({ p: this.screen(q.x, q.y), r: this.sr(q) }));
      return { xs: ps.map((q) => q.p.x), top: Math.min(...ps.map((q) => q.p.y)), bottom: Math.max(...ps.map((q) => q.p.y)), off: Math.max(...ps.map((q) => q.r)) + 9 };
    };
    ctx.textBaseline = "middle";
    const heading = (text: string, x: number, y: number, align: CanvasTextAlign) => {
      const font = "600 10px Geist, ui-sans-serif, system-ui, sans-serif";
      ctx.font = font; ctx.globalAlpha = 0.75 * f * this.namesIn; ctx.fillStyle = tk["--muted"]; ctx.textAlign = align;
      ctx.fillText(text, x, y);
      this.labels.push({ id: "head:" + text, kind: "group", ...this.box(text, x, y, align, 10, font) });
    };
    const note = (text: string, x: number, y: number, align: CanvasTextAlign) => {
      ctx.font = "450 11px Geist, ui-sans-serif, system-ui, sans-serif";
      ctx.globalAlpha = 0.7 * f * this.namesIn; ctx.fillStyle = tk["--faint"]; ctx.textAlign = align; ctx.fillText(text, x, y);
    };
    if (this.narrow && this.namesIn > 0.01) {
      for (const [ids, text, more] of [[this.slots.on, "RELIES ON", this.hiddenCounts.on], [this.slots.by, "RELIED ON BY", this.hiddenCounts.by], [this.slots.see, "SEE ALSO", this.hiddenCounts.see]] as [string[], string, number][]) {
        const cc = col(ids);
        if (!cc) continue;
        const x = Math.min(...cc.xs) - 4;
        heading(more ? `${text}  +${more} MORE IN THE PANEL` : text, x, cc.top - 22, "left");
      }
    }
    const wide = this.namesIn > 0.01 && !this.narrow;
    const cOn = wide ? col(this.slots.on) : null, cBy = wide ? col(this.slots.by) : null, cSee = wide ? col(this.slots.see) : null;
    if (cOn) {
      const x = Math.max(...cOn.xs) - cOn.off;
      heading("RELIES ON", x, cOn.top - 24, "right");
      if (this.hiddenCounts.on) note(`+${this.hiddenCounts.on} more in the panel`, x, cOn.bottom + 24, "right");
    }
    if (cBy) {
      const x = Math.min(...cBy.xs) + cBy.off;
      heading("RELIED ON BY", x, cBy.top - 24, "left");
      if (this.hiddenCounts.by) note(`+${this.hiddenCounts.by} more in the panel`, x, cBy.bottom + 24, "left");
    }
    if (cSee) {
      const x = Math.min(...cSee.xs) + cSee.off;
      heading("SEE ALSO", x, cSee.top - 22, "left");
      if (this.hiddenCounts.see) note(`+${this.hiddenCounts.see} more in the panel`, x, cSee.bottom + 22, "left");
    }

    // the relation curves, drawn on, with the direction of change running along dependencies
    const prog = this.reduced ? 1 : Math.max(0, Math.min(1, (now - this.drawOn.t0) / 520));
    const ep = easeQuintOut(prog);
    const m = this.m!;
    const depOf = (id: string) => (m.out.get(this.selected!) || []).concat(m.inn.get(this.selected!) || []).find((e) => e.source === id || e.target === id);
    // Curves leave the note sideways (or downward, for see-also) and arrive level with each
    // neighbour, like the branches of a tree diagram: they never cross the note's own name.
    const curves: { c: Cubic; dep: boolean; flowIn: boolean }[] = [];
    const rc = this.sr(c) + 5;
    for (const side of ["on", "by", "see"] as Side[]) {
      for (const id of this.slots[side]) {
        const s = this.stars.get(id);
        if (!s) continue;
        const ps = this.screen(s.x, s.y), rs = this.sr(s) + 4;
        const e = depOf(id);
        let cv: Cubic;
        if (side === "see" || this.narrow) {
          const ax = pc.x, ay = pc.y + rc, bx = ps.x - rs, by = ps.y;
          const lead = this.narrow ? -18 : -Math.max(10, (bx - ax) * 0.5);
          cv = { ax, ay, c1x: ax, c1y: ay + (by - ay) * 0.7, c2x: bx + lead, c2y: by, bx, by };
        } else {
          const sg = side === "on" ? -1 : 1;
          const ax = pc.x + sg * rc, ay = pc.y, bx = ps.x - sg * rs, by = ps.y, dx = bx - ax;
          cv = { ax, ay, c1x: ax + dx * 0.5, c1y: ay, c2x: bx - dx * 0.5, c2y: by, bx, by };
        }
        curves.push({ c: cv, dep: side !== "see" && !!e?.dependency, flowIn: side === "on" });
      }
    }
    ctx.lineCap = "round";
    for (const { c: cv, dep } of curves) {
      ctx.strokeStyle = dep ? tk["--fg-2"] : tk["--muted"];
      ctx.globalAlpha = f * (dep ? 0.55 : 0.35);
      ctx.lineWidth = dep ? 1.3 : 1;
      ctx.setLineDash(dep ? [] : [2, 4]);
      ctx.beginPath(); ctx.moveTo(cv.ax, cv.ay);
      const steps = 32, upto = Math.max(1, Math.round(steps * ep));
      for (let i = 1; i <= upto; i++) { const q = cpoint(cv, i / steps); ctx.lineTo(q.x, q.y); }
      ctx.stroke();
    }
    ctx.setLineDash([]);
    if (!this.reduced && ep >= 1) {
      for (const { c: cv, dep, flowIn } of curves) {
        if (!dep) continue;
        for (let j = 0; j < 2; j++) {
          let t = ((now / 1700) + j / 2) % 1;
          t = flowIn ? 1 - t : t;             // a change travels from the note relied on to the note relying
          const q = cpoint(cv, t);
          ctx.globalAlpha = f * 0.9 * Math.sin(Math.PI * (flowIn ? 1 - t : t));
          ctx.fillStyle = tk["--fg"];
          ctx.beginPath(); ctx.arc(q.x, q.y, 1.8, 0, Math.PI * 2); ctx.fill();
        }
      }
    }
    for (const side of ["on", "by", "see"] as Side[]) for (const id of this.slots[side]) {
      const s = this.stars.get(id); if (s) this.dot(ctx, s, id === this.hovered, breath);
    }
    // the chosen note: a halo that settles
    const r = this.sr(c);
    ctx.fillStyle = c.colour;
    ctx.globalAlpha = 0.18 * f; ctx.beginPath(); ctx.arc(pc.x, pc.y, r * 3.6, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = c.colour; ctx.lineWidth = 1.2; ctx.globalAlpha = 0.6 * f;
    ctx.beginPath(); ctx.arc(pc.x, pc.y, r + 5 + (this.reduced ? 0 : breath * 2), 0, Math.PI * 2); ctx.stroke();
    this.dot(ctx, c, false, 0);
  }

  // ------------------------------------------------------------------ labels

  private width(text: string, font: string, px: number) {
    const key = font + "|" + text;
    let w = this.widths.get(key);
    if (w == null) {
      if (this.ctx) { this.ctx.font = font; w = this.ctx.measureText(text).width || text.length * px * 0.55; }
      else w = text.length * px * 0.55;
      this.widths.set(key, w);
    }
    return w;
  }
  private box(text: string, x: number, y: number, align: CanvasTextAlign, px: number, font = `600 ${px}px Geist`) {
    const w = this.width(text, font, px), h = px + 6;
    const x0 = align === "right" ? x - w : align === "center" ? x - w / 2 : x;
    return { x: x0 - 3, y: y - h / 2, w: w + 6, h };
  }
  private obstacles: { id: string; x: number; y: number; r: number }[] = [];
  private free(b: { x: number; y: number; w: number; h: number }, own?: string) {
    if (b.x < 2 || b.y < 2 || b.x + b.w > this.W - 2 || b.y + b.h > this.H - 2) return false;
    for (const o of this.labels) if (b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y) return false;
    // A name may not sit on another note's dot, only beside its own.
    for (const d of this.obstacles) {
      if (d.id === own) continue;
      const nx = Math.max(b.x, Math.min(d.x, b.x + b.w)), ny = Math.max(b.y, Math.min(d.y, b.y + b.h));
      if ((nx - d.x) ** 2 + (ny - d.y) ** 2 < (d.r + 1) ** 2) return false;
    }
    return true;
  }

  /** Names go down greedily, most important first, and a name only goes where it touches no
   *  other: at a distance you read the areas, and closer in the notes, and never a pile-up. */
  private drawLabels(ctx: CanvasRenderingContext2D | null, f: number) {
    const tk = this.tokens, k = this.t.k;
    const put = (id: string, kind: LabelBox["kind"], text: string, x: number, y: number, align: CanvasTextAlign, px: number, weight: number, colour: string, alpha: number, force = false) => {
      const font = `${weight} ${px}px Geist, ui-sans-serif, system-ui, sans-serif`;
      const b = this.box(text, x, y, align, px, font);
      if (!force && !this.free(b, id)) return false;
      this.labels.push({ id, kind, ...b });
      if (ctx) {
        ctx.font = font; ctx.textAlign = align; ctx.textBaseline = "middle";
        ctx.globalAlpha = alpha * 0.9; ctx.fillStyle = tk["--bg"];
        ctx.lineWidth = 3; ctx.strokeStyle = tk["--bg"]; ctx.lineJoin = "round";
        ctx.strokeText(text, x, y);
        ctx.globalAlpha = alpha; ctx.fillStyle = colour; ctx.fillText(text, x, y);
      }
      return true;
    };
    // The dots names must keep clear of: every star on screen in the sky, only the focus in focus.
    this.obstacles = [];
    for (const s of this.list) {
      if (s.gone || s.a < 0.3) continue;
      if (this.selected && f > 0.5 && !(s.side || s.n.id === this.selected)) continue;
      const p = this.screen(s.x, s.y);
      if (p.x < -20 || p.x > this.W + 20 || p.y < -20 || p.y > this.H + 20) continue;
      this.obstacles.push({ id: s.n.id, x: p.x, y: p.y, r: this.sr(s) + 1.5 });
    }
    const trim = (t: string, n = 38) => (t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t);

    if (this.selected && f > 0.02) {
      const c = this.stars.get(this.selected);
      if (c) {
        const p = this.screen(c.x, c.y);
        const cf = "600 14px Geist, ui-sans-serif, system-ui, sans-serif";
        put(c.n.id, "centre", this.fitText(c.n.title, cf, 14, Math.min(420, this.W - 32)), p.x, p.y - this.sr(c) - 20, "center", 14, 600, tk["--fg"], f * (0.35 + 0.65 * this.namesIn), true);
      }
      const font = "500 12.5px Geist, ui-sans-serif, system-ui, sans-serif";
      for (const side of ["on", "by", "see"] as Side[]) for (const id of this.slots[side]) {
        const s = this.stars.get(id); if (!s) continue;
        const p = this.screen(s.x, s.y), off = this.sr(s) + 9;
        const leftSide = side === "on" && !this.narrow;
        const align: CanvasTextAlign = leftSide ? "right" : "left";
        const x = leftSide ? p.x - off : p.x + off;
        const room = leftSide ? x - 8 : this.W - x - 8;
        if (this.namesIn > 0.01) put(id, side, this.fitText(s.n.title, font, 12.5, Math.min(room, 300)), x, p.y, align, 12.5, 500, id === this.hovered ? tk["--fg"] : tk["--fg-2"], f * this.namesIn, false);
      }
    }
    if (f < 0.98) {
      const a = 1 - f;
      // area names, always, above their group
      for (const g of this.layout?.groups || []) {
        const p = this.screen(g.x, g.y - g.R);
        if (this.groupsIn <= 0.01) continue;
        // Above the group; failing that, below it; failing that, the name waits for a closer zoom.
        const text = g.label.toUpperCase() + "  " + g.notes.length, al = a * 0.95 * this.groupsIn;
        if (!put("group:" + g.key, "group", text, p.x, p.y - 14, "center", 10.5, 600, tk["--muted"], al)) {
          const q = this.screen(g.x, g.y + g.R);
          put("group:" + g.key, "group", text, q.x, q.y + 14, "center", 10.5, 600, tk["--muted"], al);
        }
      }
      if (this.hovered) {
        const s = this.stars.get(this.hovered);
        if (s) { const p = this.screen(s.x, s.y); put(s.n.id, "hover", trim(s.n.title), p.x + this.sr(s) + 8, p.y, "left", 12.5, 500, tk["--fg"], a, true); }
      }
      if (k >= 0.5 && this.groupsIn > 0.99) {
        const W = this.W, H = this.H;
        const cand = this.list.filter((s) => !s.gone && s.a > 0.3 && s.n.id !== this.hovered).map((s) => ({ s, p: this.screen(s.x, s.y) }))
          .filter(({ p }) => p.x > -10 && p.x < W && p.y > 0 && p.y < H)
          .sort((x, y) => (this.m!.degree.get(y.s.n.id) || 0) * 3 + y.s.n.observations - ((this.m!.degree.get(x.s.n.id) || 0) * 3 + x.s.n.observations));
        let placed = 0;
        const fade = Math.min(1, (k - 0.5) / 0.35);
        for (const { s, p } of cand) {
          if (placed >= 140) break;
          if (put(s.n.id, "note", trim(s.n.title, 30), p.x + this.sr(s) + 6, p.y, "left", 11.5, 450, tk["--fg-2"], a * fade * 0.85)) placed++;
        }
      }
    }
  }
  private fitText(text: string, font: string, px: number, room: number) {
    if (this.width(text, font, px) <= room) return text;
    let lo = 4, hi = text.length;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (this.width(text.slice(0, mid).trimEnd() + "\u2026", font, px) <= room) lo = mid; else hi = mid - 1; }
    return text.slice(0, lo).trimEnd() + "\u2026";
  }
  private placeLabelsOnly() { this.drawLabels(null, this.focus); }
}
