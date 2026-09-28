import type { Arrangement } from "./data";
import type { Mode } from "./store";

export interface Route { mode: Mode; arrangement: Arrangement; id: string | null; focus: boolean }

/** `#area~features/checkout` (the sky), `#grid:area~features/checkout!focus` (the grid, in focus).
 *  The older `#area/decisions~id` form, from the zoomable map, still opens in the sky: its group
 *  path is ignored, because groups no longer need opening. */
export function readHash(hash: string): Route | null {
  let raw = hash.replace(/^#/, "");
  if (!raw) return null;
  try { raw = decodeURIComponent(raw); } catch { return null; }
  let mode: Mode = "sky";
  if (raw.startsWith("grid:")) { mode = "grid"; raw = raw.slice(5); }
  let focus = false;
  if (raw.endsWith("!focus")) { focus = true; raw = raw.slice(0, -6); }
  const [head, note] = raw.split("~");
  const kind = head.split("/")[0];
  const arrangement: Arrangement = kind === "time" ? "time" : "area";
  const id = note ? note : null;
  return { mode, arrangement, id, focus: mode === "grid" && focus && !!id };
}

export function hashFor(r: Route) {
  return "#" + (r.mode === "grid" ? "grid:" : "") + r.arrangement + (r.id ? "~" + encodeURIComponent(r.id) + (r.mode === "grid" && r.focus ? "!focus" : "") : "");
}

export function writeHash(r: Route) {
  const h = hashFor(r);
  if (location.hash !== h) history.replaceState(null, "", h);
}
