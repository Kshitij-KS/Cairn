import * as React from "react";
import { Command } from "cmdk";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { CalendarDays, CircleHelp, Crosshair, FolderTree, LayoutGrid, Map as MapIcon, Palette, Sparkles, SunMoon } from "lucide-react";
import { useAtlas } from "@/lib/store";
import { levelColour, type Model } from "@/lib/data";
import { Kbd } from "./ui/kbd";
import { themeToggle } from "./Chrome";

/** ⌘K. It opens and closes with no animation at all: it is used hundreds of times a day from the
 *  keyboard, and motion there only reads as lag (Emil). */
export function CommandMenu({ m }: { m: Model }) {
  const open = useAtlas((s) => s.palette);
  const setOpen = useAtlas((s) => s.setPalette);
  const select = useAtlas((s) => s.select);
  const selected = useAtlas((s) => s.selected);
  const view = useAtlas((s) => s.view);
  const setView = useAtlas((s) => s.setView);
  const setArrangement = useAtlas((s) => s.setArrangement);
  const setColour = useAtlas((s) => s.setColour);
  const colour = useAtlas((s) => s.colour);
  const setHelp = useAtlas((s) => s.setHelp);
  const mode = useAtlas((s) => s.mode);
  const setMode = useAtlas((s) => s.setMode);
  const [q, setQ] = React.useState("");
  React.useEffect(() => { if (!open) setQ(""); }, [open]);
  const actions = ([
    { k: mode === "sky" ? "Show as a grid of cards" : "Show as the sky", icon: mode === "sky" ? LayoutGrid : Sparkles, f: () => setMode(mode === "sky" ? "grid" : "sky") },
    mode === "grid" && selected && view !== "focus" && { k: "Focus on the selected note", icon: Crosshair, f: () => setView("focus") },
    mode === "grid" && view === "focus" && { k: "Back to the grid", icon: MapIcon, f: () => setView("map") },
    { k: "Group by area", icon: FolderTree, f: () => { setView("map"); setArrangement("area"); } },
    { k: "Group by time", icon: CalendarDays, f: () => { setView("map"); setArrangement("time"); } },
    { k: colour === "level" ? "Colour by freshness" : "Colour by level", icon: Palette, f: () => setColour(colour === "level" ? "freshness" : "level") },
    { k: "Switch theme", icon: SunMoon, f: () => themeToggle.current() },
    { k: "How to read this map", icon: CircleHelp, f: () => setHelp(true) },
  ].filter(Boolean) as { k: string; icon: typeof MapIcon; f: () => void }[])
    .filter((a) => q.toLowerCase().split(/\s+/).filter(Boolean).every((t) => a.k.toLowerCase().includes(t)));
  const run = (f: () => void) => () => { setOpen(false); f(); };
  // Filtered here rather than by cmdk: a big memory has thousands of notes, and rendering every
  // one as an item to hide most of them makes the palette lag on the first key.
  const hits = React.useMemo(() => {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) {
      return [...m.g.nodes].sort((a, b) => (a.age_days ?? 9e9) - (b.age_days ?? 9e9) || a.title.localeCompare(b.title)).slice(0, 8);
    }
    const scored: [number, typeof m.g.nodes[number]][] = [];
    for (const n of m.g.nodes) {
      const t = n.title.toLowerCase();
      const hay = t + " " + n.path.toLowerCase() + " " + (n.tags || []).join(" ").toLowerCase() + " " + (n.brief || "").toLowerCase();
      if (!terms.every((x) => hay.includes(x))) continue;
      scored.push([t.startsWith(terms[0]) ? 0 : t.includes(terms[0]) ? 1 : 2, n]);
    }
    scored.sort((a, b) => a[0] - b[0] || a[1].title.localeCompare(b[1].title));
    return scored.slice(0, 40).map((x) => x[1]);
  }, [m, q]);
  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/30" />
        <DialogPrimitive.Content aria-label="Search notes and actions" data-palette
          className="fixed left-1/2 top-[14vh] z-50 w-[calc(100vw-32px)] max-w-[600px] -translate-x-1/2 overflow-hidden rounded-2xl bg-panel shadow-lg outline-none">
          <DialogPrimitive.Title className="sr-only">Search notes and actions</DialogPrimitive.Title>
          <Command label="Search notes and actions" loop shouldFilter={false}>
            <div className="flex items-center gap-2 border-b border-line px-4">
              <Command.Input value={q} onValueChange={setQ} autoFocus placeholder="Search a note by title, path, tag or summary"
                className="h-12 w-full bg-transparent text-[14px] text-fg outline-none placeholder:text-faint" />
              <Kbd>Esc</Kbd>
            </div>
            <Command.List className="scrollbar-thin max-h-[min(420px,60vh)] overflow-y-auto p-2">
              {!hits.length && !actions.length && <p className="px-3 py-8 text-center text-[13px] text-muted" data-empty>Nothing matches “{q}”.</p>}
              {hits.length > 0 && <Command.Group heading={q ? "Notes" : "Recently changed"} className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted">
                {hits.map((n) => (
                  <Command.Item key={n.id} value={"note:" + n.id}
                    onSelect={run(() => select(n.id, { focus: view === "focus" }))} data-note={n.id}
                    className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] text-fg-2 data-[selected=true]:bg-hover data-[selected=true]:text-fg">
                    <span className="size-2 shrink-0 rounded-full" style={{ background: levelColour(n.level) }} />
                    <span className="truncate">{n.title}</span>
                    <span className="ml-auto truncate pl-3 font-mono text-[11px] text-faint">{n.path}</span>
                  </Command.Item>
                ))}
              </Command.Group>}
              {actions.length > 0 && <Command.Group heading="Actions" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted">
                {actions.map((x) => {
                  return (
                    <Command.Item key={x.k} value={x.k} onSelect={run(x.f)} data-action={x.k}
                      className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] text-fg-2 data-[selected=true]:bg-hover data-[selected=true]:text-fg">
                      <x.icon className="size-4 text-muted" />{x.k}
                    </Command.Item>
                  );
                })}
              </Command.Group>}
            </Command.List>
            <div className="flex items-center gap-3 border-t border-line px-4 py-2 text-[11px] text-faint">
              <span className="flex items-center gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd> move</span>
              <span className="flex items-center gap-1"><Kbd>↵</Kbd> open</span>
              <span className="ml-auto">{m.g.nodes.length} notes</span>
            </div>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
