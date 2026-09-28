import * as React from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, ArrowRight, Crosshair, Link2, X } from "lucide-react";
import { useAtlas } from "@/lib/store";
import { groups, levelColour, levelMix, lineage, LEVELS, type Group, type Model } from "@/lib/data";
import { NoteChip, type Rel } from "./NoteChip";
import { Button } from "./ui/button";
import { cn } from "@/lib/utils";

/** Chips a group shows before folding the rest into "+N more". A group is a card in the page's
 *  own flow, so opening it only makes that card taller: nothing can land on top of anything. */
export const CAP = 18;
/** Each "more" reveals this many, so a group of hundreds opens in readable steps. */
export const STEP = 60;

/** The level mix of a group, as the few dots and counts a header has room for. */
function Mix({ notes }: { notes: Group["notes"] }) {
  const mix = levelMix(notes);
  return (
    <span className="flex items-center gap-2" aria-hidden="true">
      {LEVELS.filter((l) => mix[l]).map((l) => (
        <span key={l} className="flex items-center gap-1 font-mono text-[10.5px] tabular-nums text-faint">
          <span className="size-1.5 rounded-full" style={{ background: levelColour(l) }} />{mix[l]}
        </span>
      ))}
    </span>
  );
}

const GroupCard = React.memo(function GroupCard({ m, g, rels, index, selected }: {
  m: Model; g: Group; rels: Map<string, Rel> | null; index: number; selected: string | null;
}) {
  const limit = useAtlas((s) => s.expanded[g.key] ?? CAP);
  const showMore = useAtlas((s) => s.showMore);
  const showFewer = useAtlas((s) => s.showFewer);
  let shown = g.notes.slice(0, limit);
  // The selected note is always on show, even when it sits in the folded part.
  if (selected && !shown.some((n) => n.id === selected)) {
    const s = g.notes.find((n) => n.id === selected);
    if (s) shown = [...shown, s];
  }
  const folded = g.notes.length - shown.length;
  const foldedLinked = rels ? g.notes.filter((n) => !shown.includes(n) && rels.has(n.id)).length : 0;
  const quiet = !!rels && !g.notes.some((n) => rels.has(n.id) || n.id === selected);
  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.26, ease: [0.23, 1, 0.32, 1], delay: Math.min(index, 12) * 0.025 }}
      data-group={g.key}
      className="group-card mb-3 break-inside-avoid rounded-xl bg-panel px-3.5 pb-3.5 pt-3 shadow-sm"
      aria-label={`${g.label}, ${g.notes.length} notes`}
    >
      <header className="mb-2.5 flex items-center gap-2">
        <h3 className={cn("truncate text-[12.5px] font-semibold tracking-[-0.005em] transition-colors duration-200", quiet ? "text-faint" : "text-fg")}>{g.label}</h3>
        {g.sub && <span className="truncate text-[11px] text-faint">{g.sub}</span>}
        <span className="ml-auto flex shrink-0 items-center gap-3">
          <Mix notes={g.notes} />
          <span className="font-mono text-[11px] tabular-nums text-muted">{g.notes.length}</span>
        </span>
      </header>
      <div className="flex flex-wrap gap-1.5">
        {shown.map((n) => (
          <NoteChip key={n.id} m={m} n={n} rel={rels?.get(n.id)} dim={!!rels && n.id !== selected && !rels.has(n.id)} />
        ))}
        {folded > 0 && (
          <button
            type="button"
            data-more={g.key}
            title={folded > STEP ? `Show the next ${STEP}` : "Show the rest"}
            onClick={(e) => { e.stopPropagation(); showMore(g.key, STEP, CAP); }}
            className={cn(
              "pressable inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium text-muted hover:bg-hover hover:text-fg",
              "shadow-[inset_0_0_0_1px_var(--line-2)]",
              foldedLinked > 0 && "text-fg",
            )}
          >
            +{folded} more
            {foldedLinked > 0 && <span className="rounded-full bg-fg px-1.5 text-[10.5px] leading-4 text-bg" data-folded-linked={foldedLinked}>{foldedLinked} linked</span>}
          </button>
        )}
        {limit > CAP && (
          <button type="button" data-fewer={g.key} onClick={(e) => { e.stopPropagation(); showFewer(g.key); }}
            className="pressable inline-flex h-7 items-center rounded-full px-2.5 text-[12px] font-medium text-muted hover:bg-hover hover:text-fg">
            Show fewer
          </button>
        )}
      </div>
    </motion.section>
  );
});

/** A slim dock at the foot of the map while a note is selected. It floats (sticky), so it never
 *  pushes the cards around, and it holds no note content: that is the rail's job. Shown while a note is selected: what the marks on the lit chips mean, and the way into focus,
 *  where the same relations are laid out as a picture. */
function SelectionBar({ m, id, counts }: { m: Model; id: string; counts: Record<Rel, number> }) {
  const select = useAtlas((s) => s.select);
  const n = m.byId.get(id)!;
  const item = (I: typeof ArrowLeft, k: number, label: string) => (
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      <span className="grid size-4 place-items-center rounded-full bg-hover text-muted"><I className="size-2.5" strokeWidth={2.4} /></span>
      <span className="font-mono tabular-nums text-fg">{k}</span> {label}
    </span>
  );
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 10, transition: { duration: 0.12 } }}
      transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
      onClick={(e) => e.stopPropagation()}
      data-selection-bar
      className="pointer-events-auto flex max-w-full flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl bg-panel py-1.5 pl-3.5 pr-1.5 text-[12px] text-muted shadow-lg"
    >
      <span className="flex min-w-0 items-center gap-2">
        <span className="size-2 shrink-0 rounded-full" style={{ background: levelColour(n.level) }} />
        <span className="truncate font-medium text-fg">{n.title}</span>
      </span>
      {item(ArrowLeft, counts.on, "relies on")}
      {item(ArrowRight, counts.by, "rely on it")}
      {item(Link2, counts.see, "see also")}
      <span className="ml-auto flex items-center gap-1">
        <Button size="sm" variant="default" onClick={() => select(id, { focus: true })} data-action="focus-bar"><Crosshair /> Focus</Button>
        <Button size="icon-sm" variant="ghost" onClick={() => select(null)} aria-label="Clear the selection"><X /></Button>
      </span>
    </motion.div>
  );
}

export function MapView({ m }: { m: Model }) {
  const arrangement = useAtlas((s) => s.arrangement);
  const hidden = useAtlas((s) => s.hidden);
  const selected = useAtlas((s) => s.selected);
  const select = useAtlas((s) => s.select);

  const gs = React.useMemo(() => groups(m, arrangement, (n) => !hidden.has(n.level)), [m, arrangement, hidden]);

  // What the selected note connects to, and which way. A note both relied on and related to is
  // marked by the stronger tie, the dependency, as the lineage lists it.
  const rels = React.useMemo(() => {
    if (!selected || !m.byId.has(selected)) return null;
    const l = lineage(m, selected);
    const r = new Map<string, Rel>();
    for (const x of l.reliesOn) r.set(x.id, "on");
    for (const x of l.reliedOnBy) r.set(x.id, "by");
    for (const x of l.related) r.set(x.id, "see");
    return r;
  }, [m, selected]);
  const counts = React.useMemo(() => {
    const c: Record<Rel, number> = { on: 0, by: 0, see: 0 };
    rels?.forEach((v) => c[v]++);
    return c;
  }, [rels]);

  if (!gs.length) {
    return (
      <div className="grid h-full place-items-center p-10 text-center">
        <div>
          <p className="text-[15px] font-medium text-fg">Every level is hidden</p>
          <p className="mt-1 text-[13px] text-muted">Turn a level back on in the legend above to see its notes.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative min-h-full p-3 pb-16 sm:p-4" onClick={() => selected && select(null)} data-view="map">
      <div className="columns-[290px] gap-3">
        {gs.map((g, i) => (
          <GroupCard key={arrangement + g.key} m={m} g={g} rels={rels} index={i} selected={selected} />
        ))}
      </div>
      <div className="pointer-events-none sticky bottom-3 z-20 mt-2 flex h-0 items-end justify-center">
        <AnimatePresence>{selected && rels && <SelectionBar key="bar" m={m} id={selected} counts={counts} />}</AnimatePresence>
      </div>
    </div>
  );
}
