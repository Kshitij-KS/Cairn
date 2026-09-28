import * as React from "react";
import { motion } from "motion/react";
import { CircleHelp, LayoutGrid, Moon, Search, Sparkles, Sun } from "lucide-react";
import { useAtlas } from "@/lib/store";
import { ago, levelColour, LEVELS, type Model } from "@/lib/data";
import { Button } from "./ui/button";
import { Kbd } from "./ui/kbd";
import { Segmented } from "./ui/segmented";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";
import { AnimatedNumber } from "./AnimatedNumber";
import { cn } from "@/lib/utils";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

export function Brand() {
  return (
    <svg viewBox="0 0 32 32" className="size-7" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="var(--fg)" />
      <path d="M10 12.5 L19.5 19 L23 10.5" fill="none" stroke="var(--bg)" strokeOpacity=".45" strokeWidth="1.4" />
      <circle cx="10" cy="12.5" r="3.1" fill="var(--l0)" />
      <circle cx="19.5" cy="19" r="2.6" fill="var(--l2)" />
      <circle cx="23" cy="10.5" r="1.9" fill="var(--l1)" />
    </svg>
  );
}

function useTheme() {
  const read = () => {
    const a = document.documentElement.getAttribute("data-theme");
    if (a === "light" || a === "dark") return a;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  };
  const [theme, set] = React.useState<"light" | "dark">(read);
  const toggle = React.useCallback(() => {
    const next = read() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("atlas-theme", next); } catch { /* private window: the choice lasts this visit */ }
    set(next);
  }, []);
  return { theme, toggle };
}
export const themeToggle = { current: () => {} };

export function Header({ m }: { m: Model }) {
  const setPalette = useAtlas((s) => s.setPalette);
  const setHelp = useAtlas((s) => s.setHelp);
  const { theme, toggle } = useTheme();
  themeToggle.current = toggle;
  const g = m.g;
  const at = g.source_commit_at || g.generated_at;
  const stale = !!at && Date.now() - new Date(at).getTime() > 48 * 3600e3;
  return (
    <header className="glass sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-line bg-bg/80 px-4 backdrop-blur-md">
      <div className="flex min-w-0 items-center gap-2.5">
        <Brand />
        <div className="min-w-0 leading-tight">
          <h1 className="text-[14px] font-semibold tracking-[-0.01em] text-fg">Memory Atlas</h1>
          <p className="truncate text-[11.5px] text-muted" data-brand-sub>{g.project}, {g.mode === "public" ? "summary view" : "full view"}</p>
        </div>
      </div>

      <button type="button" onClick={() => setPalette(true)} data-open-palette
        className="pressable mx-auto hidden h-8 w-full max-w-[380px] items-center gap-2 rounded-lg bg-panel px-2.5 text-[13px] text-muted shadow-sm hover:text-fg-2 sm:flex">
        <Search className="size-3.5" />
        <span>Search notes and actions</span>
        <span className="ml-auto flex gap-1"><Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd><Kbd>K</Kbd></span>
      </button>

      <div className="ml-auto flex items-center gap-1 sm:ml-0">
        <Tooltip>
          <TooltipTrigger asChild>
            <p className={cn("mr-2 hidden items-center gap-1.5 font-mono text-[11px] lg:flex", stale ? "text-flag" : "text-muted")} data-freshness>
              <span className={cn("size-1.5 rounded-full", stale ? "bg-flag" : "live bg-ok")} />
              {ago(at)} <span className="text-faint">{g.source_commit}</span>
            </p>
          </TooltipTrigger>
          <TooltipContent>{stale ? "Older than two days. The rebuild may not have run." : `Generated from commit ${g.source_commit}.`}</TooltipContent>
        </Tooltip>
        <Button variant="ghost" size="icon" className="sm:hidden" onClick={() => setPalette(true)} aria-label="Search"><Search /></Button>
        <Button variant="ghost" size="icon" onClick={() => setHelp(true)} aria-label="How to read this" data-open-help><CircleHelp /></Button>
        <Button variant="ghost" size="icon" onClick={toggle} aria-label={`Switch to the ${theme === "dark" ? "light" : "dark"} theme`} data-theme-toggle>
          <motion.span key={theme} initial={{ rotate: -40, opacity: 0, scale: 0.9 }} animate={{ rotate: 0, opacity: 1, scale: 1 }} transition={{ duration: 0.22, ease: [0.23, 1, 0.32, 1] }} className="grid">
            {theme === "dark" ? <Sun /> : <Moon />}
          </motion.span>
        </Button>
      </div>
    </header>
  );
}

/** A link-like action inside a sentence. A real <button> is always an atomic inline box, so the
 *  full stop after it could wrap onto a line of its own; this stays part of the text. */
function InlineAction({ onClick, className, children }: { onClick: () => void; className?: string; children: React.ReactNode }) {
  return (
    <span role="button" tabIndex={0} onClick={onClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } }}
      className={cn("cursor-pointer underline decoration-1 underline-offset-4", className)}>
      {children}
    </span>
  );
}

export function Briefing({ m, lastVisit, isNew }: { m: Model; lastVisit: Date | null; isNew: (iso: string) => boolean }) {
  const setTab = useAtlas((s) => s.setTab);
  const q = m.g.queue;
  const open = q.proposals.filter((p) => (p.status || "open") === "open");
  const flagged = q.review_needed;
  const fresh = m.g.activity.filter((a) => isNew(a.at)).length;
  const s = m.g.stats;
  const stats: [number, string][] = [[s.notes, "notes"], [s.observations, "facts"], [s.relations, "links"], [s.dependencies, "dependencies"], [s.authors, "authors"]];
  const oldest = open.length ? Math.max(...open.map((p) => p.age_days ?? 0)) : 0;
  return (
    <section className="flex flex-wrap items-end gap-x-8 gap-y-3 px-5 pb-4 pt-5" aria-live="polite">
      <div className="min-w-0 flex-1 basis-[420px]">
        <p className="text-[19px] font-medium leading-snug tracking-[-0.015em] text-fg text-balance" data-briefing>
          {open.length > 0 && (
            <InlineAction onClick={() => setTab("needs")} className="decoration-line-2 hover:decoration-fg">
              {open.length} proposal{open.length === 1 ? " is" : "s are"} waiting{oldest > 3 ? `, the oldest for ${oldest} days` : ""}
            </InlineAction>
          )}
          {open.length > 0 && flagged.length > 0 && ", and "}
          {flagged.length > 0 && (
            <InlineAction onClick={() => setTab("needs")} className="text-flag">
              {flagged.length} note{flagged.length === 1 ? " needs" : "s need"} re-reading
            </InlineAction>
          )}
          {(open.length > 0 || flagged.length > 0) ? ". " : <span className="text-fg">Nothing is waiting on a person. </span>}
          <span className="text-muted">
            {lastVisit ? (fresh ? `${fresh} change${fresh === 1 ? "" : "s"} landed since you last looked.` : "Nothing has changed since you last looked.")
              : `${m.g.activity.length} change${m.g.activity.length === 1 ? " is" : "s are"} on record.`}
          </span>
        </p>
        <p className="mt-1 text-[11.5px] text-faint" title="Kept in this browser only. It is not shared and not sent anywhere." data-since>
          {lastVisit ? `Last visit ${ago(lastVisit.toISOString())}` : "First visit from this browser"}
        </p>
      </div>
      <dl className="flex flex-wrap gap-x-6 gap-y-2" data-stats>
        {stats.map(([v, k]) => (
          <div key={k} className="flex flex-col">
            <dd className="font-mono text-[18px] font-medium tabular-nums tracking-tight text-fg"><AnimatedNumber value={v || 0} /></dd>
            <dt className="text-[11px] text-muted">{k}</dt>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function Toolbar({ m }: { m: Model }) {
  const arrangement = useAtlas((s) => s.arrangement), setArrangement = useAtlas((s) => s.setArrangement);
  const colour = useAtlas((s) => s.colour), setColour = useAtlas((s) => s.setColour);
  const hidden = useAtlas((s) => s.hidden), toggleLevel = useAtlas((s) => s.toggleLevel);
  const view = useAtlas((s) => s.view);
  const mode = useAtlas((s) => s.mode), setMode = useAtlas((s) => s.setMode);
  const counts = React.useMemo(() => {
    const c: Record<string, number> = {};
    for (const n of m.g.nodes) c[n.level] = (c[n.level] || 0) + 1;
    return c;
  }, [m]);
  return (
    <div className="flex flex-wrap items-center gap-2 px-5 pb-3" data-toolbar>
      <Segmented id="mode" label="Sky or grid" value={mode} onChange={setMode}
        options={[
          { value: "sky", label: <span className="flex items-center gap-1.5"><Sparkles className="size-3.5" />Sky</span>, title: "The memory as a sky: select a note to see what it relies on (G)" },
          { value: "grid", label: <span className="flex items-center gap-1.5"><LayoutGrid className="size-3.5" />Grid</span>, title: "The same notes as cards, grouped (G)" },
        ]} />
      {!(mode === "grid" && view === "focus") && (
        <Segmented id="group" label="Group notes by" value={arrangement} onChange={setArrangement}
          options={[{ value: "area", label: "By area", title: "Where a note lives: the shape of what the team knows" },
                    { value: "time", label: "By time", title: "The month it last changed: the shape of what has been happening" }]} />
      )}
      <Segmented id="colour" label="Colour notes by" value={colour} onChange={setColour}
        options={[{ value: "level", label: "Level" }, { value: "freshness", label: "Freshness" }]} />
      <div className="ml-auto flex flex-wrap items-center gap-1" role="group" aria-label="Show or hide a level" data-legend>
        {LEVELS.filter((l) => m.g.levels[l]).map((l) => {
          const meta = m.g.levels[l];
          const n = counts[l] || 0;
          const off = hidden.has(l);
          return (
            <Tooltip key={l}>
              <TooltipTrigger asChild>
                <button type="button" data-level={l} aria-pressed={!off} disabled={!n} onClick={() => toggleLevel(l)}
                  className={cn("pressable inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12px] text-fg-2 hover:bg-hover disabled:opacity-40",
                    off && "text-faint line-through decoration-faint")}>
                  <span className={cn("size-2 rounded-full transition-transform duration-200", off && "scale-75 opacity-40")} style={{ background: levelColour(l) }} />
                  <span className="font-mono text-[11px] text-muted">{l}</span> {meta.label}
                  <span className="font-mono text-[10.5px] tabular-nums text-faint">{n}</span>
                </button>
              </TooltipTrigger>
              <TooltipContent>{n ? `${meta.may_change.join(" or ")} may change this. Select to ${off ? "show" : "hide"} it.` : "None here."}</TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </div>
  );
}
