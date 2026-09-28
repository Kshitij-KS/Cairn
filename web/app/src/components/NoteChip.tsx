import * as React from "react";
import { useAtlas } from "@/lib/store";
import { ago, briefWithheld, freshnessLevelColour, levelColour, type Model, type Note } from "@/lib/data";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";
import { Dot, dotSize } from "./Dot";
import { ArrowLeft, ArrowRight, Link2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function noteColour(n: Note, mode: "level" | "freshness") {
  return mode === "level" ? levelColour(n.level) : freshnessLevelColour(n.age_days);
}

function RelMark({ rel }: { rel: Rel }) {
  const I = REL[rel].icon;
  return (
    <span className="-mr-1 grid size-4 shrink-0 place-items-center rounded-full bg-hover text-muted" aria-hidden="true" data-mark={rel}>
      <I className="size-2.5" strokeWidth={2.4} />
    </span>
  );
}

export function NotePreview({ m, n }: { m: Model; n: Note }) {
  const deps = (m.inn.get(n.id) || []).filter((e) => e.dependency).length;
  const on = (m.out.get(n.id) || []).filter((e) => e.dependency).length;
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-[13px] font-semibold text-fg leading-snug">{n.title}</p>
      <p className="flex items-center gap-1.5 text-[11.5px] text-muted">
        <span className="size-1.5 rounded-full" style={{ background: levelColour(n.level) }} />
        {n.level} · {m.g.levels[n.level]?.label || n.level} · {ago(n.updated)}
        {n.review_needed && <span className="text-flag">· needs re-reading</span>}
      </p>
      <p className="text-[12.5px] leading-relaxed text-fg-2">
        {n.brief || (briefWithheld(m.g, n) ? <span className="text-muted">The summary is withheld at this level.</span>
                                          : <span className="text-muted">No summary line.</span>)}
      </p>
      <p className="mt-0.5 flex gap-3 font-mono text-[11px] text-muted tabular-nums">
        <span>{n.observations} facts</span><span>{deps} rely on it</span><span>relies on {on}</span>
      </p>
    </div>
  );
}

export type Rel = "on" | "by" | "see";
const REL: Record<Rel, { icon: typeof ArrowLeft; label: string }> = {
  on: { icon: ArrowLeft, label: "the selected note relies on this" },
  by: { icon: ArrowRight, label: "this relies on the selected note" },
  see: { icon: Link2, label: "see also" },
};

/** A note on the map. When another note is selected, a chip it connects to carries a small mark
 *  saying which way (the same left/right as the focus view) instead of a line drawn across the
 *  page: the map stays a clean grid, and the lines live in focus, where there is room for them. */
export const NoteChip = React.memo(function NoteChip({ m, n, rel, dim }: {
  m: Model; n: Note; rel?: Rel; dim?: boolean;
}) {
  const colour = useAtlas((s) => (s.colour === "level" ? levelColour(n.level) : freshnessLevelColour(n.age_days)));
  const selected = useAtlas((s) => s.selected === n.id);
  const select = useAtlas((s) => s.select);
  const hover = useAtlas((s) => s.hover);
  const fresh = (n.age_days ?? 999) <= 7;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          data-note={n.id}
          data-rel={rel}
          aria-pressed={selected}
          aria-label={`${n.title}, ${n.level}, ${n.observations} facts${rel ? ", " + REL[rel].label : ""}`}
          onClick={(e) => { e.stopPropagation(); select(selected ? null : n.id); }}
          onDoubleClick={(e) => { e.stopPropagation(); select(n.id, { focus: true }); }}
          onPointerEnter={() => hover(n.id)}
          onPointerLeave={() => hover(null)}
          onFocus={() => hover(n.id)}
          onBlur={() => hover(null)}
          className={cn(
            "chip pressable group/chip relative z-20 inline-flex h-7 max-w-full items-center gap-2 rounded-full pl-2 pr-2.5 text-[12.5px] leading-none",
            "bg-panel text-fg-2 shadow-sm hover:text-fg hover:shadow-md",
            selected && "text-fg shadow-[0_0_0_1.5px_var(--ring),0_4px_14px_-4px_rgba(0,0,0,.3)]",
            fresh && "text-fg",
            dim && "opacity-30 hover:opacity-100",
            rel && "text-fg shadow-[0_0_0_1px_var(--line-2),0_2px_8px_-2px_rgba(0,0,0,.18)]",
          )}
        >
          <Dot colour={colour} size={dotSize(n.observations)} flagged={!!n.review_needed} glow={selected} />
          <span className="truncate">{n.title}</span>
          {rel && <RelMark rel={rel} />}
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" align="start"><NotePreview m={m} n={n} /></TooltipContent>
    </Tooltip>
  );
});
