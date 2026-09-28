import * as React from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { motion, useReducedMotion } from "motion/react";
import { toast } from "sonner";
import { ArrowUpRight, Crosshair, Link as LinkIcon, Lock, TriangleAlert } from "lucide-react";
import { useAtlas, type RailTab } from "@/lib/store";
import { ago, briefWithheld, levelColour, lineage, type Model, type Note } from "@/lib/data";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { AnimatedNumber } from "./AnimatedNumber";
import { cn } from "@/lib/utils";

const Tick = ({ level }: { level: string }) => (
  <span className="inline-block size-2 shrink-0 rounded-full" data-level={level} style={{ background: levelColour(level) }} aria-hidden="true" />
);

function Section({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h3 className="mb-2 flex items-center text-[11px] font-medium uppercase tracking-[0.06em] text-muted">
        {title}{aside && <span className="ml-auto normal-case tracking-normal">{aside}</span>}
      </h3>
      {children}
    </section>
  );
}

function NoteDetail({ m, n }: { m: Model; n: Note }) {
  const select = useAtlas((s) => s.select);
  const view = useAtlas((s) => s.view);
  const mode = useAtlas((s) => s.mode);
  const repo = m.g.repo_url;
  const l = lineage(m, n.id);
  const groupsOf = [
    { k: "Relies on", items: l.reliesOn },
    { k: "Relied on by", items: l.reliedOnBy },
    { k: "See also", items: l.related },
  ].filter((g) => g.items.length);
  const total = l.reliesOn.length + l.reliedOnBy.length + l.related.length;
  const copy = async () => {
    const url = location.href;
    try { await navigator.clipboard.writeText(url); toast.success("Link copied", { description: "It opens this note, in this view." }); }
    catch { toast("Copy this address", { description: url }); }
  };
  return (
    <motion.div key={n.id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }} data-detail={n.id}>
      <div className="flex items-center gap-2 text-[11.5px] text-muted">
        <Tick level={n.level} />
        <span>{n.level}, {m.g.levels[n.level]?.label || n.level}</span>
        <span className="text-faint">·</span><span>{n.type}</span>
        {n.status && <><span className="text-faint">·</span><span>{n.status}</span></>}
        {n.confidentiality !== "internal" && <Badge variant="outline">{n.confidentiality}</Badge>}
      </div>
      <h2 className="mt-2 text-[18px] font-semibold leading-snug tracking-[-0.012em] text-fg text-balance">{n.title}</h2>

      {n.review_needed && (
        <div className="mt-3 flex gap-2 rounded-xl bg-[color-mix(in_srgb,var(--flag)_10%,transparent)] p-3 text-[12.5px] leading-relaxed text-fg-2" data-notice="review">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-flag" />
          <p><b className="font-semibold text-fg">Needs re-reading.</b> A planning note this depends on changed: <code className="font-mono text-[11.5px]">{n.review_needed}</code>. Treat this note as possibly out of date and prefer the note it names.</p>
        </div>
      )}

      {n.brief ? <p className="mt-3 text-[13.5px] leading-relaxed text-fg-2 text-pretty" data-brief>{n.brief}</p>
        : briefWithheld(m.g, n) ? <p className="mt-3 text-[13px] text-muted">The summary line is withheld for {n.level} notes on the published site.</p> : null}

      <div className="mt-4 flex flex-wrap gap-2">
        {mode === "grid" && view !== "focus" && (
          <Button size="sm" variant="default" onClick={() => select(n.id, { focus: true })} data-action="focus"><Crosshair /> Focus</Button>
        )}
        <Button size="sm" variant="outline" onClick={copy} data-action="copy"><LinkIcon /> Copy link</Button>
        {repo && (
          <Button size="sm" variant="ghost" asChild>
            <a href={`${repo}/blob/main/${n.path}`} target="_blank" rel="noopener noreferrer">GitHub <ArrowUpRight /></a>
          </Button>
        )}
      </div>

      <Section title="Who wrote it">
        <dl className="grid grid-cols-[96px_1fr] gap-x-3 gap-y-1.5 text-[12.5px]">
          <dt className="text-muted">Created by</dt><dd className="text-fg-2">{n.author || "not recorded"}</dd>
          <dt className="text-muted">Last edited</dt><dd className="text-fg-2">{n.updated_by || "not recorded"}{n.agent ? `, using ${n.agent}` : ""}</dd>
          <dt className="text-muted">Created</dt><dd className="text-fg-2">{n.created || "not recorded"}</dd>
          <dt className="text-muted">Changed</dt><dd className="text-fg-2">{ago(n.updated)}</dd>
          <dt className="text-muted">File</dt><dd className="break-all font-mono text-[11.5px] text-fg-2">{n.path}</dd>
        </dl>
      </Section>

      {Object.keys(n.categories || {}).length > 0 && (
        <Section title={`${n.observations} facts`}>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(n.categories).sort((a, b) => b[1] - a[1]).map(([c, k]) => (
              <Badge key={c}><b className="font-semibold text-fg">{k}</b> {c}</Badge>
            ))}
          </div>
        </Section>
      )}

      {n.observation_list ? (
        <Section title="What it says">
          <ul className="flex flex-col gap-2">
            {n.observation_list.map((o, i) => (
              <li key={i} className="grid grid-cols-[auto_1fr] gap-2 text-[12.5px] leading-relaxed">
                <span className="mt-[3px] h-fit rounded-md bg-hover px-1.5 font-mono text-[10.5px] text-muted">{o.category}</span>
                <span className="text-fg-2">{o.text}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : (
        <div className="mt-6 flex gap-2 rounded-xl bg-panel-2 p-3 text-[12.5px] leading-relaxed text-muted shadow-[inset_0_0_0_1px_var(--line)]" data-notice="locked">
          <Lock className="mt-0.5 size-3.5 shrink-0" />
          <p><b className="font-medium text-fg-2">The text is not published.</b> This build shows the summary line but not the note itself. Run <code className="font-mono text-[11.5px]">build_atlas.py --full</code> on your own machine to read it.</p>
        </div>
      )}

      <Section title={`${total} relations`}>
        {total === 0 ? (
          <p className="text-[12.5px] text-muted">None. Nothing links to this note, so a search through the graph will never reach it. Add a relation to connect it.</p>
        ) : groupsOf.map((g) => (
          <div key={g.k} className="mb-3">
            <p className="mb-1 text-[11.5px] text-faint">{g.k}</p>
            <ul className="flex flex-col" data-rel-group={g.k}>
              {g.items.map((x) => {
                const o = m.byId.get(x.id)!;
                return (
                  <li key={x.id}>
                    <button type="button" data-id={o.id} onClick={() => select(o.id)}
                      className="pressable flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg">
                      <Tick level={o.level} /><span className="min-w-0 flex-1 truncate">{o.title}</span>
                      <span className="font-mono text-[10.5px] text-faint">{x.e.type.replace(/_/g, " ")}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </Section>

      {n.tags.length > 0 && (
        <Section title="Tags">
          <div className="flex flex-wrap gap-1.5">{n.tags.map((t) => <Badge key={t} variant="outline">{t}</Badge>)}</div>
        </Section>
      )}
    </motion.div>
  );
}

function Changes({ m, isNew }: { m: Model; isNew: (iso: string) => boolean }) {
  const select = useAtlas((s) => s.select);
  const acts = m.g.activity;
  const [current, setCurrent] = React.useState<number | null>(null);
  if (!acts.length) return <p className="text-[12.5px] text-muted">No commits yet. The first sync will fill this in.</p>;
  return (
    <>
      <p className="mb-3 text-[12px] text-muted">Newest first. Select an entry to open the first note it touched.</p>
      <ol className="relative flex flex-col" data-feed>
        <span className="absolute bottom-3 left-[7px] top-3 w-px bg-line-2" aria-hidden="true" />
        {acts.map((a, i) => (
          <motion.li key={a.sha + i}
            initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.22, ease: [0.23, 1, 0.32, 1], delay: Math.min(i, 12) * 0.03 }}>
            <button type="button" aria-current={current === i}
              onClick={() => { setCurrent(i); const t = a.touched.find((p) => m.byId.has(p)); if (t) select(t); }}
              className={cn("pressable relative flex w-full gap-3 rounded-xl py-2 pl-0 pr-2 text-left hover:bg-hover", current === i && "bg-hover")}>
              <span className="relative z-10 mt-1.5 grid size-[15px] shrink-0 place-items-center rounded-full bg-panel shadow-[0_0_0_1px_var(--line-2)]">
                <span className="size-[7px] rounded-full" style={{ background: levelColour(a.level) }} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5 text-[12.5px]">
                  <span className="truncate font-medium text-fg">{a.author || "someone"}</span>
                  {a.actor === "agent" && <span className="truncate text-muted">using {a.agent || "an agent"}</span>}
                  {isNew(a.at) && <Badge variant="solid" className="h-4 px-1 text-[10px]">new</Badge>}
                  <span className="ml-auto shrink-0 font-mono text-[10.5px] text-faint">{ago(a.at)}</span>
                </span>
                <span className={cn("mt-0.5 block text-[12.5px] leading-snug", a.message ? "text-fg-2" : "text-muted")}>
                  {a.message || `${a.files} file${a.files === 1 ? "" : "s"} changed. The message is not published.`}
                </span>
                <span className="mt-0.5 block truncate font-mono text-[10.5px] text-faint">
                  {a.paths.slice(0, 3).join(", ")}{a.files > 3 ? `, and ${a.files - 3} more` : ""}
                </span>
              </span>
            </button>
          </motion.li>
        ))}
      </ol>
    </>
  );
}

function Item({ title, why, level, author, age, onClick, id }: {
  title: string; why?: string | null; level: string; author?: string | null; age?: number | null; onClick: () => void; id: string;
}) {
  return (
    <button type="button" data-id={id} onClick={onClick}
      className="pressable mb-2 block w-full rounded-xl bg-panel p-3 text-left shadow-sm hover:shadow-md">
      <span className="block text-[13px] font-medium text-fg">{title}</span>
      {why && <span className="mt-1 block text-[12.5px] leading-snug text-fg-2">{why}</span>}
      <span className="mt-2 flex items-center gap-2 font-mono text-[10.5px] text-muted">
        <Tick level={level} />{level}{author && <span>{author}</span>}{age != null && <span>{age} days old</span>}
      </span>
    </button>
  );
}

function Needs({ m }: { m: Model }) {
  const select = useAtlas((s) => s.select);
  const { proposals, review_needed } = m.g.queue;
  const open = proposals.filter((p) => (p.status || "open") === "open");
  const go = (id: string) => m.byId.has(id) && select(id);
  return (
    <div data-needs>
      <h3 className="mb-1 text-[11px] font-medium uppercase tracking-[0.06em] text-muted">Proposals</h3>
      <p className="mb-3 text-[12px] text-muted">An agent wrote these and cannot promote them. Someone with the right role decides.</p>
      {open.length ? open.map((p) => <Item key={p.id} id={p.id} title={p.title} why={p.brief} level={p.level} author={p.author} age={p.age_days} onClick={() => go(p.id)} />)
        : <p className="mb-2 text-[12.5px] text-ok">Nothing waiting.</p>}
      <h3 className="mb-1 mt-7 text-[11px] font-medium uppercase tracking-[0.06em] text-muted">Flagged by a change upstream</h3>
      <p className="mb-3 text-[12px] text-muted">A planning note these depend on has changed. Re-read each one, then update it or clear the flag.</p>
      {review_needed.length ? review_needed.map((r) => <Item key={r.id} id={r.id} title={r.title} why={r.why} level={r.level} age={r.age_days} onClick={() => go(r.id)} />)
        : <p className="text-[12.5px] text-ok">Nothing stale.</p>}
    </div>
  );
}

function ScoreRing({ score }: { score: number }) {
  const reduced = useReducedMotion();
  const C = 2 * Math.PI * 42;
  const colour = score >= 80 ? "var(--ok)" : score >= 55 ? "var(--l2)" : "var(--l3)";
  return (
    <div className="relative size-[112px]">
      <svg viewBox="0 0 100 100" className="size-full -rotate-90" aria-hidden="true">
        <circle cx="50" cy="50" r="42" fill="none" stroke="var(--line-2)" strokeWidth="7" />
        <motion.circle cx="50" cy="50" r="42" fill="none" stroke={colour} strokeWidth="7" strokeLinecap="round"
          strokeDasharray={C} initial={{ strokeDashoffset: reduced ? C * (1 - score / 100) : C }}
          animate={{ strokeDashoffset: C * (1 - score / 100) }} transition={{ duration: 0.9, ease: [0.23, 1, 0.32, 1] }} />
      </svg>
      <p className="absolute inset-0 grid place-content-center text-center">
        <AnimatedNumber value={score} className="text-[26px] font-semibold tabular-nums tracking-tight text-fg" />
        <span className="text-[10.5px] text-muted">out of 100</span>
      </p>
    </div>
  );
}

function Gaps({ m }: { m: Model }) {
  const select = useAtlas((s) => s.select);
  const h = m.g.health, repo = m.g.repo_url;
  const verdict = h.score >= 80 ? "The memory is in good shape." : h.score >= 55 ? "Usable, with parts going out of date."
    : "Much of this memory is still placeholder text, or cannot be reached from any other note.";
  const labels: Record<string, string> = {
    orphans: "notes nothing links to, so a search through the graph will never reach them",
    placeholders: "unfilled TODO markers, which agents read first and find empty",
    review_needed: "notes flagged by an upstream change and not yet re-read",
    stale: "notes untouched for 90 days or more",
    broken_links: "relations pointing at a note that does not exist",
  };
  const rows = Object.entries(h.counts).filter(([, v]) => v > 0);
  const worst = h.issues.filter((i) => i.severity === "major").slice(0, 10);
  return (
    <div data-gaps>
      <div className="flex items-center gap-4">
        <ScoreRing score={h.score} />
        <p className="flex-1 text-[12.5px] leading-relaxed text-fg-2">{verdict} <span className="text-muted">The score falls for unfilled placeholders, unreachable notes, notes going stale, and links that do not resolve.</span></p>
      </div>
      <div className="mt-5 flex flex-col gap-1.5">
        {rows.length ? rows.map(([k, v]) => (
          <p key={k} className="flex items-baseline gap-2.5 text-[12.5px]"><b className="w-8 text-right font-mono font-medium tabular-nums text-fg">{v}</b><span className="text-fg-2">{labels[k] || k}</span></p>
        )) : <p className="text-[12.5px] text-ok">No gaps found.</p>}
      </div>
      {worst.length > 0 && (
        <>
          <h3 className="mb-2 mt-7 text-[11px] font-medium uppercase tracking-[0.06em] text-muted">Fix these first</h3>
          {worst.map((i) => {
            const node = m.byId.get(i.id);
            return (
              <div key={i.kind + i.id} className="mb-2 rounded-xl bg-panel p-3 shadow-sm">
                <button type="button" data-id={i.id} className="block w-full text-left" onClick={() => node && select(i.id)}>
                  <span className="block text-[13px] font-medium text-fg hover:underline">{i.title}</span>
                  <span className="mt-1 block text-[12.5px] leading-snug text-fg-2">{i.detail}</span>
                </button>
                <span className="mt-2 flex items-center gap-2 font-mono text-[10.5px] text-muted">
                  {node && <Tick level={node.level} />}
                  {repo && node ? <a className="hover:text-fg" href={`${repo}/blob/main/${node.path}`} target="_blank" rel="noopener noreferrer">Open the file</a> : <span>{i.id}</span>}
                </span>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

const TABS: { v: RailTab; label: string }[] = [
  { v: "note", label: "Note" }, { v: "changes", label: "Changes" }, { v: "needs", label: "Needs you" }, { v: "gaps", label: "Gaps" },
];

export function Rail({ m, isNew }: { m: Model; isNew: (iso: string) => boolean }) {
  const tab = useAtlas((s) => s.tab);
  const setTab = useAtlas((s) => s.setTab);
  const selected = useAtlas((s) => s.selected);
  const n = selected ? m.byId.get(selected) : undefined;
  const open = m.g.queue.proposals.filter((p) => (p.status || "open") === "open").length + m.g.queue.review_needed.length;
  const h = m.g.health.counts;
  const bad = (h.orphans || 0) + (h.placeholders || 0) + (h.review_needed || 0);
  const counts: Partial<Record<RailTab, number>> = { needs: open, gaps: bad };
  return (
    <Tabs.Root value={tab} onValueChange={(v) => setTab(v as RailTab)} className="flex h-full min-h-0 flex-col" data-rail>
      <Tabs.List aria-label="Views" className="flex shrink-0 gap-0.5 px-3 pt-3">
        {TABS.map((t) => (
          <Tabs.Trigger key={t.v} value={t.v} data-tab={t.v}
            className="pressable relative flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px] font-medium text-muted outline-none hover:text-fg data-[state=active]:text-fg focus-visible:ring-2 focus-visible:ring-[var(--ring)]">
            {tab === t.v && <motion.span layoutId="rail-tab" className="absolute inset-0 rounded-lg bg-hover" transition={{ type: "spring", duration: 0.3, bounce: 0 }} />}
            <span className="relative">{t.label}</span>
            {counts[t.v] != null && (
              <span className={cn("relative rounded-full px-1.5 font-mono text-[10px] leading-4 tabular-nums", counts[t.v] ? "bg-fg text-bg" : "bg-hover text-faint")} data-count={counts[t.v]}>{counts[t.v]}</span>
            )}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
      <div className="mx-3 mt-2 h-px shrink-0 bg-line" />
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <Tabs.Content value="note" className="outline-none" data-panel="note">
          {n ? <NoteDetail m={m} n={n} /> : (
            <div className="py-10 text-center">
              <p className="text-[13px] font-medium text-fg">No note selected</p>
              <p className="mt-1 text-[12.5px] text-muted">Select a note on the map to read it here. Double-click one to focus on it.</p>
            </div>
          )}
        </Tabs.Content>
        <Tabs.Content value="changes" className="outline-none" data-panel="changes"><Changes m={m} isNew={isNew} /></Tabs.Content>
        <Tabs.Content value="needs" className="outline-none" data-panel="needs"><Needs m={m} /></Tabs.Content>
        <Tabs.Content value="gaps" className="outline-none" data-panel="gaps"><Gaps m={m} /></Tabs.Content>
      </div>
    </Tabs.Root>
  );
}
