import * as React from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Maximize2, Minus, Plus } from "lucide-react";
import { useAtlas } from "@/lib/store";
import type { Model } from "@/lib/data";
import { SkyEngine, type SkySnapshot } from "./sky/engine";
import { NotePreview } from "./NoteChip";
import { Button } from "./ui/button";

declare global { interface Window { __atlasSky?: { snapshot: () => SkySnapshot; settle: () => void } } }

/** The main view: the memory as a sky. The canvas does the drawing; this component wires it to
 *  the app's state and lays the few HTML controls over it. */
export function SkyView({ m }: { m: Model }) {
  const host = React.useRef<HTMLDivElement>(null);
  const canvas = React.useRef<HTMLCanvasElement>(null);
  const engine = React.useRef<SkyEngine | null>(null);
  const reduced = !!useReducedMotion();
  const arrangement = useAtlas((s) => s.arrangement);
  const hidden = useAtlas((s) => s.hidden);
  const colour = useAtlas((s) => s.colour);
  const selected = useAtlas((s) => s.selected);
  const select = useAtlas((s) => s.select);
  const [tip, setTip] = React.useState<{ id: string; x: number; y: number } | null>(null);

  React.useEffect(() => {
    const c = canvas.current!;
    const e = new SkyEngine(c, {
      hover: (id, x, y) => setTip(id ? { id, x, y } : null),
      select: (id) => { setTip(null); select(id); },
    }, reduced);
    engine.current = e;
    window.__atlasSky = { snapshot: () => e.snapshot(), settle: () => e.settle() };
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => e.resize()) : null;
    if (ro && host.current) ro.observe(host.current);
    // The palette of the sky is the page's own tokens: re-read them when the theme changes.
    const mo = new MutationObserver(() => e.readTokens());
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onScheme = () => e.readTokens();
    mq?.addEventListener?.("change", onScheme);
    return () => { e.destroy(); ro?.disconnect(); mo.disconnect(); mq?.removeEventListener?.("change", onScheme); engine.current = null; delete window.__atlasSky; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => { engine.current?.setReduced(reduced); }, [reduced]);
  React.useEffect(() => { engine.current?.setData(m, arrangement, hidden, colour); }, [m, arrangement, hidden]); // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => { engine.current?.setColour(colour); }, [colour]);
  React.useEffect(() => { engine.current?.setSelected(selected); setTip(null); }, [selected]);

  const tn = tip && tip.id !== selected ? m.byId.get(tip.id) : undefined;
  const W = host.current?.clientWidth || 0;
  return (
    <div ref={host} className="relative size-full overflow-hidden rounded-2xl" data-view="sky" data-selected={selected || undefined}>
      <canvas ref={canvas} className="block cursor-grab touch-none active:cursor-grabbing" role="img"
        aria-label={`A map of ${m.g.nodes.length} notes. Select a note to see what it relies on and what relies on it. The grid view lists the same notes as text.`} />
      <AnimatePresence>
        {tn && (
          <motion.div key={tn.id} role="tooltip" data-sky-tip
            initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, transition: { duration: 0.08 } }}
            transition={{ duration: 0.14, ease: [0.23, 1, 0.32, 1] }}
            className="pointer-events-none absolute z-20 w-[280px] rounded-xl bg-panel px-3 py-2.5 shadow-lg"
            style={{ left: Math.min(Math.max(8, tip!.x + 14), Math.max(8, W - 296)), top: tip!.y + 16, transformOrigin: "left top" }}>
            <NotePreview m={m} n={tn} />
          </motion.div>
        )}
      </AnimatePresence>
      <div className="absolute bottom-3 left-3 z-10 flex gap-1 rounded-xl bg-panel/90 p-1 shadow-md" data-sky-controls>
        <Button size="icon-sm" variant="ghost" aria-label="Zoom in" onClick={() => engine.current?.zoomBy(1.5)}><Plus /></Button>
        <Button size="icon-sm" variant="ghost" aria-label="Zoom out" onClick={() => engine.current?.zoomBy(1 / 1.5)}><Minus /></Button>
        <Button size="icon-sm" variant="ghost" aria-label="Show the whole sky" onClick={() => { if (selected) select(null); else engine.current?.fit(); }}><Maximize2 /></Button>
      </div>
      <p className="pointer-events-none absolute bottom-4 right-4 z-10 hidden text-[11px] text-faint sm:block">
        {selected ? "Esc to step back · click a neighbour to move there" : "Scroll to zoom · drag to pan · click a star"}
      </p>
    </div>
  );
}
