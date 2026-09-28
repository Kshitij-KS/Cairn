import { useAtlas } from "@/lib/store";
import { levelColour, LEVELS, type Model } from "@/lib/data";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "./ui/dialog";
import { Kbd } from "./ui/kbd";

const H = ({ children }: { children: React.ReactNode }) => <h3 className="mb-1.5 mt-5 text-[12px] font-semibold text-fg">{children}</h3>;
const P = ({ children }: { children: React.ReactNode }) => <p className="text-[13px] leading-relaxed text-fg-2">{children}</p>;

export function HelpDialog({ m }: { m: Model }) {
  const open = useAtlas((s) => s.help);
  const setOpen = useAtlas((s) => s.setHelp);
  const w = m.g.withheld || { bodies: 0, restricted: 0 };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-[600px]" data-help>
        <div className="scrollbar-thin max-h-[80vh] overflow-y-auto p-6">
          <DialogTitle className="text-[17px] font-semibold tracking-[-0.01em] text-fg">How to read this map</DialogTitle>
          <DialogDescription asChild>
            <P>Each star is one note in the team's shared memory. Each faint line is a relation the note declares, which is the same path an AI agent follows when it looks something up.</P>
          </DialogDescription>

          <H>Levels decide who may change a note</H>
          <ul className="flex flex-col gap-1.5" data-help-levels>
            {LEVELS.filter((l) => m.g.levels[l]).map((l) => (
              <li key={l} className="flex items-baseline gap-2 text-[13px] text-fg-2">
                <span className="size-2 shrink-0 translate-y-[-1px] rounded-full" style={{ background: levelColour(l) }} />
                <span><b className="font-semibold text-fg">{l}, {m.g.levels[l].label}.</b> Changed by {m.g.levels[l].may_change.join(" or ")}.</span>
              </li>
            ))}
          </ul>

          <H>The sky, and the grid</H>
          <P><b className="font-medium text-fg">The sky</b> puts every note in a cluster for its area (or for its month, by time). Each cluster is a sunflower spiral, the most connected notes at its heart. Names appear as you zoom in, wherever there is room for them, so they never pile up.</P>
          <div className="h-2" />
          <P>Select a star and the sky rearranges around it. What it relies on moves to the left: if one of those changes, this note may be out of date. What relies on it moves to the right: a change here reaches those next. Notes it only relates to wait below. Select any of them to move there; Escape walks you back.</P>
          <div className="h-2" />
          <P><b className="font-medium text-fg">The grid</b> shows the same notes as cards of labelled chips, for reading down a list. Double-click a chip there for the same lineage, laid out as columns.</P>

          <H>What the marks mean</H>
          <ul className="list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-fg-2">
            <li>A star's size is how many facts the note holds; its colour is its level (or, if you choose, how recently it changed).</li>
            <li>The glow behind a cluster is the colour of the level most of its notes are at.</li>
            <li>A solid curve is a dependency: <code className="font-mono text-[12px]">depends_on</code>, <code className="font-mono text-[12px]">implements</code>, <code className="font-mono text-[12px]">part_of</code>, <code className="font-mono text-[12px]">supersedes</code>. Light running along it goes the way a change travels.</li>
            <li>A dotted curve is <code className="font-mono text-[12px]">relates_to</code>, meaning see also. It does not carry a change outward.</li>
            <li>An amber ring means a planning change landed upstream and nobody has re-read the note yet.</li>
          </ul>

          <H>Getting around</H>
          <ul className="space-y-1.5 text-[13px] text-fg-2">
            <li><Kbd>⌘</Kbd> <Kbd>K</Kbd> or <Kbd>/</Kbd> finds any note, and runs any action.</li>
            <li>Scroll or pinch to zoom the sky, drag to pan. <Kbd>G</Kbd> switches between the sky and the grid.</li>
            <li><Kbd>Esc</Kbd> steps back: through the notes you visited, then to the map, then clears the selection.</li>
            <li>The address always matches what you see, so a link you paste opens exactly this.</li>
          </ul>

          <H>Why most notes show only a summary line</H>
          <P>{m.g.mode === "public"
            ? `This build withholds the contents of ${w.bodies || 0} notes and omits ${w.restricted || 0} restricted notes completely, along with every commit message. You can see what exists, who changed it and how it connects, without the text itself. To read the notes, run build_atlas.py --full on your own machine.`
            : "This is the full local build. Nothing is withheld, so do not deploy this file."}</P>
        </div>
      </DialogContent>
    </Dialog>
  );
}
