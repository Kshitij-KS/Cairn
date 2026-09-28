import * as React from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { Toaster } from "sonner";
import { buildModel, dataFile, type Graph, type Model } from "@/lib/data";
import { useAtlas } from "@/lib/store";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Header, Briefing, Toolbar } from "@/components/Chrome";
import { MapView } from "@/components/MapView";
import { FocusView } from "@/components/FocusView";
import { SkyView } from "@/components/SkyView";
import { Rail } from "@/components/Rail";
import { CommandMenu } from "@/components/CommandMenu";
import { HelpDialog } from "@/components/HelpDialog";
import { readHash, writeHash } from "@/lib/route";

type Boot = { state: "loading" } | { state: "error"; why: string } | { state: "old"; schema?: number } | { state: "ready"; m: Model };

/** The fields this page reads. A file without them is from an older (or a foreign) build, and
 *  the page says so rather than drawing an empty sky. Schema 3 files have them all. */
function readable(g: Graph | null): boolean {
  return !!g && Array.isArray(g.nodes) && Array.isArray(g.edges) && Array.isArray(g.activity)
    && !!g.levels && !!g.stats && !!g.queue && Array.isArray(g.queue.proposals) && Array.isArray(g.queue.review_needed)
    && !!g.health && typeof g.health.score === "number";
}

function readLastVisit(): Date | null {
  try {
    const raw = localStorage.getItem("atlas-last-visit");
    const d = raw ? new Date(raw) : null;
    localStorage.setItem("atlas-last-visit", new Date().toISOString());
    return d && !isNaN(+d) ? d : null;
  } catch { return null; }
}

function Skeleton() {
  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-[1fr_380px]" data-boot aria-busy="true">
      <div className="p-5">
        <div className="skeleton h-6 w-[46%]" />
        <div className="skeleton mt-3 h-3 w-[22%]" />
        <div className="mt-8 columns-[300px] gap-4">
          {[5, 9, 4, 7, 6, 3].map((k, i) => (
            <div key={i} className="mb-4 break-inside-avoid rounded-2xl bg-panel p-4 shadow-sm">
              <div className="skeleton h-3 w-1/3" />
              <div className="mt-4 flex flex-wrap gap-1.5">{Array.from({ length: k }, (_, j) => <div key={j} className="skeleton h-7 rounded-full" style={{ width: 70 + ((i * 7 + j * 13) % 60) }} />)}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="hidden border-l border-line p-5 lg:block">
        {[45, 80, 65, 74, 58].map((w, i) => <div key={i} className="skeleton mt-3 h-3" style={{ width: w + "%" }} />)}
      </div>
    </div>
  );
}

function Problem({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="grid h-full place-items-center p-6" data-problem>
      <div className="max-w-[58ch] rounded-2xl bg-panel p-6 shadow-md">
        <h2 className="text-[17px] font-semibold text-fg">{title}</h2>
        <div className="mt-2 space-y-3 text-[13.5px] leading-relaxed text-fg-2 [&_code]:rounded-md [&_code]:bg-hover [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[12px]">{children}</div>
      </div>
    </div>
  );
}

function useKeys() {
  const st = useAtlas;
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const s = st.getState();
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); s.setPalette(!s.palette); return; }
      if (s.palette || s.help || typing) return;
      if (e.key === "/") { e.preventDefault(); s.setPalette(true); }
      else if (e.key === "Escape") s.back();
      else if ((e.key === "f" || e.key === "F") && !e.metaKey && !e.ctrlKey && !e.altKey && s.selected && s.mode === "grid") s.setView(s.view === "focus" ? "map" : "focus");
      else if ((e.key === "g" || e.key === "G") && !e.metaKey && !e.ctrlKey && !e.altKey) s.setMode(s.mode === "sky" ? "grid" : "sky");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [st]);
}

/** Below the side-by-side layout the rail sits under the map, out of sight. A small pill says
 *  which note is selected and takes you to it; it is not a card and it holds no content. */
function ReadPill({ m }: { m: Model }) {
  const selected = useAtlas((s) => s.selected);
  const setTab = useAtlas((s) => s.setTab);
  const n = selected ? m.byId.get(selected) : undefined;
  return (
    <AnimatePresence>
      {n && (
        <motion.button key="pill" type="button" data-read-pill
          initial={{ x: "-50%", y: 16, opacity: 0 }} animate={{ x: "-50%", y: 0, opacity: 1 }} exit={{ x: "-50%", y: 16, opacity: 0, transition: { duration: 0.15 } }}
          transition={{ type: "spring", duration: 0.35, bounce: 0 }}
          onClick={() => { setTab("note"); document.querySelector("[data-rail]")?.scrollIntoView({ behavior: "smooth", block: "start" }); }}
          className="pressable fixed bottom-4 left-1/2 z-40 flex max-w-[calc(100vw-32px)] items-center gap-2 rounded-full bg-fg py-2 pl-3 pr-4 text-[13px] font-medium text-bg shadow-lg lg:hidden">
          <span className="truncate">{n.title}</span><span className="opacity-60">Read</span>
        </motion.button>
      )}
    </AnimatePresence>
  );
}

function Atlas({ m }: { m: Model }) {
  const view = useAtlas((s) => s.view);
  const selected = useAtlas((s) => s.selected);
  const arrangement = useAtlas((s) => s.arrangement);
  const mode = useAtlas((s) => s.mode);
  const [lastVisit] = React.useState(readLastVisit);
  const isNew = React.useCallback((iso: string) => {
    if (!lastVisit || !iso) return false;
    const t = new Date(iso);
    return !isNaN(+t) && t > lastVisit;
  }, [lastVisit]);
  useKeys();

  // The address is the state: it is read once on arrival and on every hashchange, and written
  // whenever what you are looking at changes.
  React.useEffect(() => {
    const apply = () => {
      const r = readHash(location.hash);
      if (!r) return;
      const s = useAtlas.getState();
      if (r.mode !== s.mode) s.setMode(r.mode);
      if (r.arrangement !== s.arrangement) s.setArrangement(r.arrangement);
      if (r.id && m.byId.has(r.id)) { if (r.id !== s.selected || (r.focus ? "focus" : "map") !== s.view) s.select(r.id, { focus: r.focus }); }
      else if (s.selected) s.select(null);
    };
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, [m]);
  React.useEffect(() => { writeHash({ mode, arrangement, id: selected, focus: view === "focus" }); }, [mode, arrangement, selected, view]);

  return (
    <div className="grid h-full grid-rows-[auto_1fr]">
      <Header m={m} />
      {/* Below the lg breakpoint the whole page scrolls as one column; above it the stage and
          the rail scroll separately, side by side. */}
      <main className="scrollbar-thin grid min-h-0 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_400px] lg:overflow-hidden">
        <div className="scrollbar-thin flex flex-col lg:min-h-0 lg:overflow-y-auto" data-stage>
          <Briefing m={m} lastVisit={lastVisit} isNew={isNew} />
          <Toolbar m={m} />
          {mode === "sky" ? (
            <div className="mx-3 mb-3 h-[max(520px,calc(100dvh-236px))] shrink-0 rounded-2xl shadow-[0_0_0_1px_var(--line)] sm:mx-5 sm:mb-5" data-stage-sky>
              <SkyView m={m} />
            </div>
          ) : (
            <div className="canvas-grid mx-3 mb-3 min-h-[320px] flex-1 rounded-2xl shadow-[inset_0_0_0_1px_var(--line)] sm:mx-5 sm:mb-5">
              <AnimatePresence mode="wait" initial={false}>
                <motion.div key={view === "focus" && selected ? "focus" : "map"} className="h-full"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.14, ease: "easeOut" }}>
                  {view === "focus" && selected ? <FocusView m={m} /> : <MapView m={m} />}
                </motion.div>
              </AnimatePresence>
            </div>
          )}
          <footer className="flex gap-4 px-5 pb-4 text-[11.5px] text-faint">
            <a className="hover:text-fg" href="privacy.html">Privacy</a>
            <a className="hover:text-fg" href="terms.html">Terms</a>
          </footer>
        </div>
        <aside className="min-h-[60vh] border-t border-line bg-panel/60 lg:min-h-0 lg:border-l lg:border-t-0" aria-label="Details">
          <Rail m={m} isNew={isNew} />
        </aside>
      </main>
      <ReadPill m={m} />
      <CommandMenu m={m} />
      <HelpDialog m={m} />
    </div>
  );
}

export function App() {
  const [boot, setBoot] = React.useState<Boot>({ state: "loading" });
  const file = React.useMemo(() => dataFile(location.search), []);
  React.useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await fetch(file, { cache: "no-store" });
        if (!res.ok) throw new Error(`the server returned ${res.status}`);
        const g = (await res.json()) as Graph;
        if (!live) return;
        if (!readable(g)) { setBoot({ state: "old", schema: g && g.schema }); return; }
        setBoot({ state: "ready", m: buildModel(g) });
      } catch (err) {
        if (live) setBoot({ state: "error", why: err instanceof Error ? err.message : String(err) });
      }
    })();
    return () => { live = false; };
  }, [file]);

  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider>
        {boot.state === "loading" && <Skeleton />}
        {boot.state === "error" && (
          <Problem title="The map could not load">
            <p><code>{file}</code> was not readable: {boot.why}.</p>
            <p>Generate it from the repository root:<br /><code>uv run -q --script scripts/build_atlas.py</code></p>
            <p className="text-muted">Opening this file straight from disk will also fail, because browsers block <code>fetch</code> on <code>file://</code>. Serve the folder instead:<br /><code>python -m http.server -d web 8080</code></p>
          </Problem>
        )}
        {boot.state === "old" && (
          <Problem title="This data file is too old">
            <p>It {boot.schema ? <>is schema {boot.schema}, and</> : null} lacks fields this page reads (the notes, links, activity, queue and health). Rebuild it:<br /><code>uv run -q --script scripts/build_atlas.py</code></p>
          </Problem>
        )}
        {boot.state === "ready" && <Atlas m={boot.m} />}
        <Toaster position="bottom-center" theme="system" toastOptions={{ className: "!rounded-xl !bg-panel !text-fg !shadow-lg !border-0 !font-sans" }} />
      </TooltipProvider>
    </MotionConfig>
  );
}
