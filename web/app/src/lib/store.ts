import { create } from "zustand";
import type { Arrangement, Level } from "./data";

export type View = "map" | "focus";
/** The sky is the main view; the grid lists the same notes as cards, and is the plain alternative. */
export type Mode = "sky" | "grid";
export type RailTab = "note" | "changes" | "needs" | "gaps";
export type ColourMode = "level" | "freshness";

interface State {
  mode: Mode;
  setMode: (m: Mode) => void;
  arrangement: Arrangement;
  colour: ColourMode;
  hidden: Set<Level>;
  selected: string | null;
  hovered: string | null;
  view: View;
  tab: RailTab;
  palette: boolean;
  help: boolean;
  /** How many notes each group shows, when more than the first few have been asked for. */
  expanded: Record<string, number>;
  /** The notes walked through in the focus view, oldest first, so the way back is visible. */
  trail: string[];
  setArrangement: (a: Arrangement) => void;
  setColour: (c: ColourMode) => void;
  toggleLevel: (l: Level) => void;
  select: (id: string | null, opts?: { focus?: boolean }) => void;
  hover: (id: string | null) => void;
  setView: (v: View) => void;
  back: () => void;
  setTab: (t: RailTab) => void;
  setPalette: (o: boolean) => void;
  setHelp: (o: boolean) => void;
  showMore: (key: string, by: number, base: number) => void;
  showFewer: (key: string) => void;
}

export const useAtlas = create<State>((set, get) => ({
  mode: "sky",
  setMode: (mode) => set((s) => ({ mode, view: "map", trail: s.selected ? [s.selected] : [] })),
  arrangement: "area",
  colour: "level",
  hidden: new Set(),
  selected: null,
  hovered: null,
  view: "map",
  tab: "changes",
  palette: false,
  help: false,
  expanded: {},
  trail: [],
  setArrangement: (arrangement) => set({ arrangement, expanded: {} }),
  setColour: (colour) => set({ colour }),
  toggleLevel: (l) => set((s) => {
    const hidden = new Set(s.hidden);
    hidden.has(l) ? hidden.delete(l) : hidden.add(l);
    return { hidden };
  }),
  // In the sky, choosing a note IS focusing on it (the sky rearranges around it); in the grid,
  // focus is a separate view you step into.
  select: (id, opts) => set((s) => {
    if (!id) return { selected: null, hovered: null, view: "map", trail: [], tab: s.tab === "note" ? "changes" : s.tab };
    const focus = s.mode === "sky" || (opts?.focus ?? s.view === "focus");
    let trail = s.trail;
    if (focus) {
      const at = trail.indexOf(id);
      trail = at >= 0 ? trail.slice(0, at + 1) : [...trail, id].slice(-8);
    } else trail = [];
    return { selected: id, hovered: null, tab: "note", view: s.mode === "grid" && focus ? "focus" : "map", trail };
  }),
  hover: (hovered) => { if (get().hovered !== hovered) set({ hovered }); },
  setView: (view) => set((s) => ({
    view: view === "focus" && (!s.selected || s.mode === "sky") ? "map" : view,
    trail: s.selected && (view === "focus" || s.mode === "sky") ? [s.selected] : [],
  })),
  // One step back: through the focus trail, then out to the map, then clear the selection.
  back: () => set((s) => {
    const walking = s.mode === "sky" ? !!s.selected : s.view === "focus";
    if (walking && s.trail.length > 1) {
      const trail = s.trail.slice(0, -1);
      return { trail, selected: trail[trail.length - 1] };
    }
    if (s.mode === "grid" && s.view === "focus") return { view: "map", trail: [] };
    if (s.selected) return { selected: null, trail: [], tab: s.tab === "note" ? "changes" : s.tab };
    return {};
  }),
  setTab: (tab) => set({ tab }),
  setPalette: (palette) => set({ palette }),
  setHelp: (help) => set({ help }),
  showMore: (key, by, base) => set((s) => ({ expanded: { ...s.expanded, [key]: (s.expanded[key] ?? base) + by } })),
  showFewer: (key) => set((s) => {
    const expanded = { ...s.expanded };
    delete expanded[key];
    return { expanded };
  }),
}));
