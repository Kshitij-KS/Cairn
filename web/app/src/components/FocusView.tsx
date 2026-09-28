import * as React from "react";
import { AnimatePresence, motion, useIsPresent } from "motion/react";
import { ArrowLeft, ArrowRight, Link2 } from "lucide-react";
import { useAtlas } from "@/lib/store";
import { ago, briefWithheld, lineage, levelColour, freshnessLevelColour, type Edge, type Model, type Note } from "@/lib/data";
import { Dot, dotSize } from "./Dot";
import { Badge } from "./ui/badge";
import { Kbd } from "./ui/kbd";
import { cn } from "@/lib/utils";

/** A curve between two boxes: leaves and arrives horizontally, so lines read as routes rather
 *  than a scribble, and sag a little when both ends sit on one row. */
export function curve(a: { x: number; y: number }, b: { x: number; y: number }) {
  const dx = b.x - a.x, dy = b.y - a.y;
  if (Math.abs(dy) < 6) {
    const lift = Math.min(60, 18 + Math.abs(dx) * 0.18);
    return `M${a.x},${a.y} C${a.x + dx * 0.25},${a.y - lift} ${b.x - dx * 0.25},${b.y - lift} ${b.x},${b.y}`;
  }
  const k = Math.max(40, Math.abs(dx) * 0.5);
  const s = Math.sign(dx) || 1;
  return `M${a.x},${a.y} C${a.x + k * s},${a.y} ${b.x - k * s},${b.y} ${b.x},${b.y}`;
}

const COL_CAP = 10;
const EASE = [0.23, 1, 0.32, 1] as const;

function useColour() {
  const mode = useAtlas((s) => s.colour);
  return (n: Note) => (mode === "level" ? levelColour(n.level) : freshnessLevelColour(n.age_days));
}

/** One neighbour in the lineage. Its dot carries a layoutId, so choosing it slides that very dot
 *  into the centre: you watch the note you picked become the subject. */
function Neighbour({ n, e, side, index, anchor }: {
  n: Note; e: Edge; side: "left" | "right" | "below"; index: number;
  anchor: (id: string) => (el: HTMLElement | null) => void;
}) {
  const select = useAtlas((s) => s.select);
  const colour = useColour();
  // While it animates out, a neighbour of the previous note is no longer part of this lineage.
  const present = useIsPresent();
  return (
    <motion.button
      data-present={present ? "" : undefined}
      disabled={!present}
      layout="position"
      ref={anchor(n.id)}
      type="button"
      data-lineage={side}
      data-note={n.id}
      initial={{ opacity: 0, x: side === "left" ? -10 : side === "right" ? 10 : 0, y: side === "below" ? 8 : 0 }}
      animate={{ opacity: 1, x: 0, y: 0 }}
      exit={{ opacity: 0, transition: { duration: 0.12 } }}
      transition={{ duration: 0.26, ease: EASE, delay: Math.min(index, 10) * 0.035 }}
      onClick={() => select(n.id, { focus: true })}
      className={cn(
        "pressable group/n flex w-full min-w-0 items-center gap-2.5 rounded-xl bg-panel px-3 py-2.5 text-left shadow-sm hover:shadow-md",
        side === "right" && "flex-row-reverse text-right",
        side === "below" && "w-auto max-w-[260px]",
      )}
    >
      <Dot colour={colour(n)} size={dotSize(n.observations)} layoutId={"fdot-" + n.id} flagged={!!n.review_needed} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium text-fg">{n.title}</span>
        <span className="block truncate font-mono text-[10.5px] text-muted">{e.type.replace(/_/g, " ")} · {n.level}</span>
      </span>
    </motion.button>
  );
}

function Column({ title, hint, icon, items, side, m, anchor, empty }: {
  title: string; hint: string; icon: React.ReactNode; items: { id: string; e: Edge }[]; side: "left" | "right";
  m: Model; anchor: (id: string) => (el: HTMLElement | null) => void; empty: string;
}) {
  const [all, setAll] = React.useState(false);
  const shown = all ? items : items.slice(0, COL_CAP);
  return (
    <div className={cn("flex min-w-0 flex-col gap-2", side === "right" && "items-stretch")} data-column={side}>
      <p className={cn("mb-1 flex items-center gap-1.5 px-1 text-[11px] font-medium uppercase tracking-[0.06em] text-muted", side === "right" && "flex-row-reverse")}>
        {icon}{title}<span className="font-mono normal-case tracking-normal text-faint">{items.length}</span>
      </p>
      <p className={cn("-mt-1 mb-1 px-1 text-[11.5px] leading-snug text-faint", side === "right" && "text-right")}>{hint}</p>
      <AnimatePresence initial={true}>
        {shown.map((x, i) => (
          <Neighbour key={x.id} n={m.byId.get(x.id)!} e={x.e} side={side} index={i} anchor={anchor} />
        ))}
      </AnimatePresence>
      {!items.length && (
        <p className={cn("rounded-xl px-3 py-3 text-[12.5px] text-faint shadow-[inset_0_0_0_1px_var(--line)] border-dashed", side === "right" && "text-right")}>{empty}</p>
      )}
      {items.length > COL_CAP && (
        <button type="button" onClick={() => setAll((v) => !v)} className="pressable self-start rounded-full px-2.5 py-1 text-[12px] text-muted hover:bg-hover hover:text-fg">
          {all ? "Show fewer" : `Show all ${items.length}`}
        </button>
      )}
    </div>
  );
}

export function FocusView({ m }: { m: Model }) {
  const id = useAtlas((s) => s.selected)!;
  const trail = useAtlas((s) => s.trail);
  const select = useAtlas((s) => s.select);
  const setView = useAtlas((s) => s.setView);
  const colour = useColour();
  const n = m.byId.get(id);
  const host = React.useRef<HTMLDivElement>(null);
  const centreRef = React.useRef<HTMLDivElement>(null);
  const els = React.useRef(new Map<string, HTMLElement>());
  const refs = React.useRef(new Map<string, (el: HTMLElement | null) => void>());
  const anchor = React.useCallback((nid: string) => {
    let r = refs.current.get(nid);
    if (!r) { r = (el) => { if (el) els.current.set(nid, el); else els.current.delete(nid); }; refs.current.set(nid, r); }
    return r;
  }, []);
  const [paths, setPaths] = React.useState<{ key: string; d: string; dep: boolean }[]>([]);

  const l = React.useMemo(() => (n ? lineage(m, id) : { reliesOn: [], reliedOnBy: [], related: [] }), [m, id, n]);

  const measure = React.useCallback(() => {
    const h = host.current, c = centreRef.current;
    if (!h || !c) return;
    const hr = h.getBoundingClientRect(), cr = c.getBoundingClientRect();
    const out: { key: string; d: string; dep: boolean }[] = [];
    const side = (el: HTMLElement) => el.getAttribute("data-lineage");
    for (const [nid, el] of els.current) {
      if (!el.isConnected || !el.hasAttribute("data-present")) continue;
      const r = el.getBoundingClientRect();
      const s = side(el);
      if (s === "left") out.push({ key: "l" + nid, dep: true, d: curve({ x: r.right - hr.left, y: r.top - hr.top + r.height / 2 }, { x: cr.left - hr.left, y: cr.top - hr.top + cr.height / 2 }) });
      else if (s === "right") out.push({ key: "r" + nid, dep: true, d: curve({ x: cr.right - hr.left, y: cr.top - hr.top + cr.height / 2 }, { x: r.left - hr.left, y: r.top - hr.top + r.height / 2 }) });
      else if (s === "below") {
        // See-also hangs under the subject: a light vertical curve, with no flow, because a
        // relates_to link does not carry a change anywhere.
        const a = { x: cr.left - hr.left + cr.width / 2, y: cr.bottom - hr.top };
        const b = { x: r.left - hr.left + r.width / 2, y: r.top - hr.top };
        const k = Math.max(24, (b.y - a.y) * 0.5);
        out.push({ key: "b" + nid, dep: false, d: `M${a.x},${a.y} C${a.x},${a.y + k} ${b.x},${b.y - k} ${b.x},${b.y}` });
      }
    }
    setPaths(out);
  }, []);

  React.useLayoutEffect(() => {
    measure();
    const t = window.setTimeout(measure, 420);
    const again = () => requestAnimationFrame(measure);
    window.addEventListener("resize", again);
    const ro = typeof ResizeObserver !== "undefined" && host.current ? new ResizeObserver(again) : null;
    if (ro && host.current) ro.observe(host.current);
    return () => { window.clearTimeout(t); window.removeEventListener("resize", again); ro?.disconnect(); };
  }, [measure, id, l]);

  if (!n) return null;
  const withheld = briefWithheld(m.g, n);

  return (
    <div className="relative min-h-full p-3 pb-16 sm:p-5" data-view="focus">
      <nav aria-label="Where you have been" className="mb-5 flex flex-wrap items-center gap-1 text-[12.5px]">
        <button type="button" onClick={() => setView("map")} className="pressable inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-muted hover:bg-hover hover:text-fg">
          <ArrowLeft className="size-3.5" /> Map
        </button>
        {trail.map((t, i) => {
          const tn = m.byId.get(t);
          if (!tn) return null;
          const last = i === trail.length - 1;
          return (
            <React.Fragment key={t + i}>
              <span className="text-faint">/</span>
              <button type="button" disabled={last} aria-current={last ? "page" : undefined}
                onClick={() => select(t, { focus: true })}
                className={cn("max-w-[200px] truncate rounded-md px-1.5 py-0.5", last ? "font-medium text-fg" : "pressable text-muted hover:bg-hover hover:text-fg")}>
                {tn.title}
              </button>
            </React.Fragment>
          );
        })}
        <span className="ml-auto hidden items-center gap-1.5 text-[11.5px] text-faint sm:flex"><Kbd>Esc</Kbd> back</span>
      </nav>

      <div ref={host} className="relative">
        <svg className="pointer-events-none absolute inset-0 hidden size-full overflow-visible md:block" aria-hidden="true">
          {paths.map((p) => (
            <g key={p.key + id}>
              <motion.path d={p.d} fill="none" stroke={p.dep ? "var(--edge-dep)" : "var(--edge)"} strokeWidth={p.dep ? 1.4 : 1}
                strokeLinecap="round" strokeDasharray={p.dep ? undefined : "2 4"}
                initial={{ pathLength: 0, opacity: 0 }} animate={{ pathLength: 1, opacity: 1 }}
                transition={{ duration: 0.3, ease: EASE, delay: 0.08 }} />
              {p.dep && <path d={p.d} fill="none" stroke="var(--fg)" strokeOpacity={0.5} strokeWidth={1.4} strokeLinecap="round" className="edge-flow" />}
            </g>
          ))}
        </svg>
      <div className="relative grid grid-cols-1 items-center gap-6 md:grid-cols-[minmax(0,1fr)_minmax(280px,360px)_minmax(0,1fr)] md:gap-14">

        <Column title="Relies on" hint="If one of these changes, this note may be out of date." icon={<ArrowRight className="size-3" />}
          items={l.reliesOn} side="left" m={m} anchor={anchor} empty="Relies on nothing. It is a foundation." />

        <motion.div
          ref={centreRef}
          key={"c" + id}
          data-centre={id}
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ type: "spring", duration: 0.4, bounce: 0 }}
          className="relative z-10 rounded-2xl bg-panel p-5 shadow-lg"
        >
          <div className="mb-3 flex items-center gap-2.5">
            <Dot colour={colour(n)} size={dotSize(n.observations, 10)} layoutId={"fdot-" + n.id} glow flagged={!!n.review_needed} />
            <Badge variant="outline">{n.level} · {m.g.levels[n.level]?.label || n.level}</Badge>
            {n.review_needed && <Badge variant="flag">needs re-reading</Badge>}
          </div>
          <h2 className="text-[19px] font-semibold leading-tight tracking-[-0.015em] text-fg text-balance">{n.title}</h2>
          <p className="mt-1 font-mono text-[11px] text-muted">{n.path}</p>
          <p className="mt-3 text-[13.5px] leading-relaxed text-fg-2 text-pretty">
            {n.brief || <span className="text-muted">{withheld ? "The summary line is withheld at this level." : "No summary line."}</span>}
          </p>
          <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
            {[[n.observations, "facts"], [l.reliesOn.length, "relies on"], [l.reliedOnBy.length, "rely on it"]].map(([v, k]) => (
              <div key={k as string} className="rounded-lg bg-panel-2 px-2 py-2 shadow-[inset_0_0_0_1px_var(--line)]">
                <dt className="sr-only">{k}</dt>
                <dd className="font-mono text-[15px] font-medium tabular-nums text-fg">{v}</dd>
                <p className="text-[10.5px] text-muted" aria-hidden="true">{k}</p>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-[11.5px] text-faint">Changed {ago(n.updated)}</p>
        </motion.div>

        <Column title="Relied on by" hint="A change here reaches these next." icon={<ArrowRight className="size-3 rotate-180" />}
          items={l.reliedOnBy} side="right" m={m} anchor={anchor} empty="Nothing relies on this yet." />
      </div>

      {l.related.length > 0 && (
        <section className="relative mt-12 flex flex-col items-center" data-column="below">
          <p className="mb-2.5 flex items-center gap-1.5 px-1 text-[11px] font-medium uppercase tracking-[0.06em] text-muted">
            <Link2 className="size-3" /> See also <span className="font-mono normal-case tracking-normal text-faint">{l.related.length}</span>
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            <AnimatePresence>
              {l.related.map((x, i) => (
                <Neighbour key={x.id} n={m.byId.get(x.id)!} e={x.e} side="below" index={i} anchor={anchor} />
              ))}
            </AnimatePresence>
          </div>
        </section>
      )}
      </div>
    </div>
  );
}
