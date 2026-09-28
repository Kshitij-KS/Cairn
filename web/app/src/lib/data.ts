// The Atlas's model of graph.json (schema 4, written by scripts/build_atlas.py). Everything the
// page shows comes from here; nothing is fetched from anywhere else.

export type Level = "L0" | "L1" | "L2" | "L3";
export const LEVELS: Level[] = ["L0", "L1", "L2", "L3"];

export interface Note {
  id: string; path: string; title: string; folder: string; type: string; level: Level;
  confidentiality: string; author: string | null; updated_by: string | null; agent: string | null;
  status: string | null; created: string | null; updated: string | null; age_days: number | null;
  tags: string[]; observations: number; categories: Record<string, number>; todos: number;
  review_needed: string | null; brief: string | null; body: string | null;
  observation_list: { category: string; text: string }[] | null; claims: number;
  feature?: Record<string, unknown>; trial?: Record<string, unknown>;
}
export interface Edge { source: string; target: string; type: string; dependency: boolean }
export interface Activity {
  sha: string; author: string | null; at: string; level: string; actor: string; agent: string | null;
  files: number; paths: string[]; touched: string[]; message: string | null;
}
export interface Graph {
  schema: number; mode: "public" | "full"; project: string; generated_at: string; source_commit: string;
  source_commit_at: string; repo_url: string | null;
  levels: Record<string, { label: string; paths: string[]; may_change: string[] }>;
  publication: { brief_levels?: string[]; publish_authors?: boolean };
  withheld: { restricted: number; bodies: number; briefs: number; experiments: number };
  stats: Record<string, number>;
  nodes: Note[]; edges: Edge[]; activity: Activity[];
  queue: { proposals: { id: string; title: string; status: string; author: string | null; age_days: number | null; level: string; brief: string | null }[];
           review_needed: { id: string; title: string; level: string; why: string | null; age_days: number | null }[] };
  health: { score: number; counts: Record<string, number>; issues: { kind: string; severity: string; id: string; title: string; detail: string }[] };
  features: unknown[]; gaps: unknown[]; trials: unknown[]; playbooks: unknown[];
  arrangements?: unknown;
}

export interface Model {
  g: Graph;
  byId: Map<string, Note>;
  out: Map<string, Edge[]>;   // edges leaving a note (it relates to / depends on the target)
  inn: Map<string, Edge[]>;   // edges arriving at a note
  degree: Map<string, number>;
}

export function buildModel(g: Graph): Model {
  const byId = new Map(g.nodes.map((n) => [n.id, n]));
  const out = new Map<string, Edge[]>(), inn = new Map<string, Edge[]>();
  for (const n of g.nodes) { out.set(n.id, []); inn.set(n.id, []); }
  for (const e of g.edges) {
    if (!byId.has(e.source) || !byId.has(e.target)) continue;
    out.get(e.source)!.push(e);
    inn.get(e.target)!.push(e);
  }
  const degree = new Map(g.nodes.map((n) => [n.id, out.get(n.id)!.length + inn.get(n.id)!.length]));
  return { g, byId, out, inn, degree };
}

/** What a note relies on, what relies on it, and what it merely relates to. Dependencies point
 *  from the note that relies to the note relied on; relates_to has no direction. */
export function lineage(m: Model, id: string) {
  const out = m.out.get(id) || [], inn = m.inn.get(id) || [];
  const seen = new Set<string>();
  const pick = (arr: { id: string; e: Edge }[]) =>
    arr.filter((x) => x.id !== id && m.byId.has(x.id) && !seen.has(x.id) && (seen.add(x.id), true));
  const reliesOn = pick(out.filter((e) => e.dependency).map((e) => ({ id: e.target, e })));
  const reliedOnBy = pick(inn.filter((e) => e.dependency).map((e) => ({ id: e.source, e })));
  const related = pick([...out.filter((e) => !e.dependency).map((e) => ({ id: e.target, e })),
                        ...inn.filter((e) => !e.dependency).map((e) => ({ id: e.source, e }))]);
  return { reliesOn, reliedOnBy, related };
}

export const neighbours = (m: Model, id: string) => {
  const l = lineage(m, id);
  return new Set([...l.reliesOn, ...l.reliedOnBy, ...l.related].map((x) => x.id));
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pretty = (s: string) => s.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()).trim();

export type Arrangement = "area" | "time";
export interface Group { key: string; label: string; sub: string | null; notes: Note[] }

export function importance(m: Model, n: Note) {
  return (m.degree.get(n.id) || 0) * 3 + n.observations + (30 - Math.min(30, n.age_days ?? 30));
}

/** Notes grouped the way a person looks for them: by the folder they live in, or by the month
 *  they last changed. The grouping is computed here from each note's own fields. */
export function groups(m: Model, arrangement: Arrangement, visible: (n: Note) => boolean): Group[] {
  const map = new Map<string, Group>();
  for (const n of m.g.nodes) {
    if (!visible(n)) continue;
    let key: string, label: string, sub: string | null = null;
    if (arrangement === "area") {
      const d = n.path.includes("/") ? n.path.slice(0, n.path.lastIndexOf("/")) : "";
      key = "area:" + d;
      const parts = d.split("/").filter(Boolean);
      label = parts.length ? pretty(parts[parts.length - 1]) : "Overview";
      sub = parts.length > 1 ? parts.slice(0, -1).map(pretty).join(" / ") : null;
    } else {
      const s = (n.updated || n.created || "").slice(0, 7);
      if (/^\d{4}-\d{2}$/.test(s)) {
        key = "time:" + s;
        label = MONTHS[+s.slice(5) - 1] + " " + s.slice(0, 4);
      } else { key = "time:undated"; label = "Undated"; }
    }
    if (!map.has(key)) map.set(key, { key, label, sub, notes: [] });
    map.get(key)!.notes.push(n);
  }
  const out = [...map.values()];
  for (const gr of out) gr.notes.sort((a, b) => importance(m, b) - importance(m, a) || a.title.localeCompare(b.title));
  if (arrangement === "time") out.sort((a, b) => (a.key === "time:undated" ? 1 : b.key === "time:undated" ? -1 : b.key.localeCompare(a.key)));
  else out.sort((a, b) => (a.key === "area:" ? -1 : b.key === "area:" ? 1 : b.notes.length - a.notes.length || a.label.localeCompare(b.label)));
  return out;
}

export function levelMix(notes: Note[]) {
  const mix: Record<string, number> = {};
  for (const n of notes) mix[n.level] = (mix[n.level] || 0) + 1;
  return mix;
}

export function ago(iso: string | null | undefined, now = Date.now()) {
  if (!iso) return "unknown";
  const then = new Date(iso.length <= 10 ? iso + "T12:00:00Z" : iso);
  if (isNaN(+then)) return "unknown";
  const s = (now - then.getTime()) / 1000;
  if (s < 90) return "just now";
  const m = s / 60, h = m / 60, d = h / 24;
  if (m < 60) return `${Math.round(m)} min ago`;
  if (h < 24) return `${Math.round(h)} hr ago`;
  if (d < 31) return `${Math.round(d)} day${Math.round(d) === 1 ? "" : "s"} ago`;
  if (d < 365) return `${Math.round(d / 30.4)} mo ago`;
  return `${(d / 365).toFixed(1)} yr ago`;
}

export function freshnessLevelColour(age: number | null): string {
  const d = age ?? 999;
  if (d <= 3) return "var(--l1)";
  if (d <= 14) return "var(--l0)";
  if (d <= 45) return "var(--l2)";
  if (d <= 120) return "var(--l3)";
  return "var(--faint)";
}

export const levelColour = (l: string) => `var(--${l.toLowerCase()})`;

export function briefWithheld(g: Graph, n: Note) {
  return !n.brief && g.mode === "public" && !((g.publication?.brief_levels || ["L0"]).includes(n.level));
}

export function dataFile(search: string) {
  const raw = new URLSearchParams(search).get("data");
  if (!raw || !/^data\/[A-Za-z0-9._-]+\.json$/.test(raw)) return "data/graph.json";
  return raw;
}
