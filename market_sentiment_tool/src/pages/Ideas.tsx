import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Loader2, Plus } from "lucide-react";

import { PlayCheckButton } from "@/components/PlayCheck";
import { useApi } from "@/hooks/usePaperPortfolio";
import NewIdeaBox from "@/components/NewIdeaBox";
import { FullView } from "@/components/Panel";
import { SectorTonePanel } from "@/components/SectorTonePanel";
import { useAdminSession } from "@/components/RequireAdmin";
import { TradeLabels } from "@/components/TradeLabels";
import { EARLY_N } from "@/lib/sample";
import {
  claimLabel, KIND_LABEL, STATUS_LABEL, toneClass, verdictTone,
  type IdeaRow, type PublicIdea, type ShadowSummary, type WorkshopDashboard,
} from "@/lib/workshop";
import { fmtUsd } from "@/lib/paperPortfolio";
import { adminCall, DashCard, Fig, PEEK, PeekRows, Segments } from "@/pages/portfolio/shared";

export const signedPct = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`);

export const pText = (p: number | null | undefined) => (p == null ? null : p < 0.001 ? "p < 0.001" : `p = ${p.toFixed(3)}`);

type SortKey = "grouped" | "value" | "p" | "newest" | "title";
type GroupKey = "bet" | "sector" | "tag";

/**
 * The shadow ideas (standing, not trading), grouped (Kevin, 2026-11-05): by bet (ideas on the same names),
 * by the sector most of an idea's names are in, or by Kevin's own tags -- an idea sits under each of its tags.
 * A bet whose lead is trading says so, since the lead sits in the section above.
 */
export function groupShadow(standingIdeas: PublicIdea[], by: GroupKey):
    { key: string; label: string; note?: string; ideas: PublicIdea[] }[] {
  const tradingIds = new Set(standingIdeas.filter((i) => (i.live_books ?? []).length > 0).map((i) => i.id));
  const shadow = standingIdeas.filter((i) => !tradingIds.has(i.id));
  const groups = new Map<string, { key: string; label: string; note?: string; ideas: PublicIdea[] }>();
  const add = (key: string, label: string, idea: PublicIdea, note?: string) => {
    if (!groups.has(key)) groups.set(key, { key, label, note, ideas: [] });
    groups.get(key)!.ideas.push(idea);
  };
  for (const idea of shadow) {
    if (by === "sector") add(`s:${idea.sector ?? "Other"}`, idea.sector ?? "Other", idea);
    else if (by === "tag") {
      const tags = idea.tags ?? [];
      if (!tags.length) add("t:", "No tag", idea);
      for (const t of tags) add(`t:${t.toLowerCase()}`, t, idea);
    } else if (idea.family && idea.family.size > 1) {
      const leadTrading = idea.family.members.some((m) => tradingIds.has(m));
      add(`b:${idea.family.key}`, `One bet · ${idea.family.tickers.join(" · ")}`, idea, leadTrading ? "lead trading above" : undefined);
    } else add("b:standalone", "Standalone", idea);
  }
  const best = (g: { ideas: PublicIdea[] }) => Math.max(...g.ideas.map((i) => i.result_value ?? -Infinity));
  return [...groups.values()]
    .map((g) => ({ ...g, ideas: [...g.ideas].sort((a, b) => (b.result_value ?? -Infinity) - (a.result_value ?? -Infinity)) }))
    .sort((a, b) => Number(a.key === "b:standalone" || a.key === "t:") - Number(b.key === "b:standalone" || b.key === "t:")
      || best(b) - best(a));
}

const SORT_LABEL: Record<SortKey, string> = {
  grouped: "Grouped by bet",
  value: "Strongest result",
  p: "Most significant (lowest p)",
  newest: "Newest first",
  title: "Title A–Z",
};

/** Standing under the current hub-wide standard (Kevin, 2026-11-03): live,
 * tracking, or still passing. Everything else was trimmed to the Removed
 * disclosure below -- kept on the record, out of the way. */
export function standing(idea: PublicIdea): boolean {
  if ((idea.live_books ?? []).length > 0) return true; // trading on a book: in view whatever its verdict
  return (idea.verdict_now ?? idea.latest_verdict) === "PASS";
}

/** One line of forward record: idea vs benchmark since the anchor (go-live for a
 * traded idea, tracking start for a tracked one -- Kevin, 2026-11-02: a tracked
 * idea's performance against its metric belongs on the card, at a glance), its
 * as-of, and the claim's current state. */
export function PaperLine({ live, mode = "paper" }: { live: ShadowSummary; mode?: "paper" | "forward" }) {
  if (live.days === 0)
    return live.state === "stale"
      ? <p className="text-sm text-amber-300">{mode === "forward" ? "No forward days recorded since tracking began" : "No paper days recorded since going live"} · stale</p>
      : <p className="text-sm text-slate-400">{mode === "forward" ? "Forward" : "Paper"} record starts on the next trading day.</p>;
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
      {mode === "forward" && <span className="text-xs font-semibold uppercase tracking-wide text-sky-300">Forward</span>}
      <span className="font-mono text-lg text-white">{signedPct(live.return_pct)}</span>
      <span className="text-slate-400">benchmark {signedPct(live.bench_return_pct)}</span>
      <span className="text-slate-500">
        {live.days} days · as of {live.as_of}
        {live.state === "stale" && " · stale"}
      </span>
      {live.days < EARLY_N ? (
        <span className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-300">Too early to say</span>
      ) : live.failing ? (
        <span className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-xs text-rose-300">Claim failing</span>
      ) : live.claim?.holds ? (
        <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300">Claim holding · {live.claim.label}</span>
      ) : null}
    </div>
  );
}

function IdeaCard({ idea, to, showKind = false, compact = false }: { idea: PublicIdea; to: (id: number) => string; showKind?: boolean; compact?: boolean }) {
  const verdict = idea.verdict_now ?? idea.latest_verdict;
  const demoted = idea.verdict_now != null && idea.latest_verdict != null && idea.verdict_now !== idea.latest_verdict;
  const chips = (
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${toneClass[verdictTone(verdict)]}`}>{verdict ?? "Not run"}</span>
        <span className="text-xs text-slate-500">{STATUS_LABEL[idea.status]}</span>
        {idea.gate_overridden && (
          <span className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs font-semibold text-amber-300">Gate overridden</span>
        )}
        {idea.hindsight_selected && (
          <span className="rounded border border-slate-600 bg-slate-800 px-2 py-0.5 text-xs font-semibold text-slate-300">Hindsight-selected</span>
        )}
        {(idea.live_books ?? []).map((b) => (
          <span key={b} className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-300">
            Live · {b === "big" ? "$1M" : "Main"}
          </span>
        ))}
        {Object.entries(idea.critic ?? {}).map(([book, c]) => (
          <span key={book} title={c.reasons.join(" ")}
            className={`rounded border px-2 py-0.5 text-xs font-semibold ${c.recommendation === "PAUSE" ? "border-rose-500/40 bg-rose-500/10 text-rose-300" : c.recommendation === "WATCH" ? "border-amber-500/40 bg-amber-500/10 text-amber-300" : "border-slate-600 bg-slate-800 text-slate-300"}`}>
            Critic · {c.recommendation}{c.degradation != null ? ` · ${c.degradation >= 0 ? "+" : ""}${c.degradation.toFixed(1)} vs claim` : ""}{book === "big" ? " · $1M" : ""}
          </span>
        ))}
        {idea.status === "tracking" && (
          <span className="rounded border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-xs font-semibold text-sky-300">
            Tracking{idea.tracked_at ? ` since ${idea.tracked_at.slice(0, 10)}` : ""}
          </span>
        )}
        {idea.status === "killed" && (
          <span className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-xs font-semibold text-rose-300">Killed</span>
        )}
        <span className="text-xs text-slate-500">· {idea.variations} {idea.variations === 1 ? "run" : "runs"}</span>
        {idea.registry?.test_number != null && (
          <span className="text-xs text-slate-500">· test #{idea.registry.test_number} of {idea.registry.tests_total ?? "—"}</span>
        )}
        {showKind && <span className="text-xs text-slate-500">· {KIND_LABEL[idea.kind]}</span>}
      </div>
  );
  if (compact) {
    // One line per idea for the trading list (2026-11-06: one screen per page); the full card is on its page.
    return (
      <li className="relative grid gap-x-4 gap-y-1 border-t border-slate-800 py-2 first:border-t-0 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-center">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-white">
            <Link to={to(idea.id)} className="after:absolute after:inset-0 hover:underline underline-offset-2">{idea.title}</Link>
          </h3>
          <div className="mt-1 [&_span]:!text-[11px]">{chips}</div>
          {demoted && (
            <p className="mt-0.5 text-[11px] text-amber-300/90">
              Passed as run, demoted under the hub-wide standard
              {idea.wf_ok === false ? " (walk-forward)" : idea.p_ok === false ? " (p over 0.01)" : idea.fdr_pass === false ? " (FDR over all tests)" : ""}
            </p>
          )}
        </div>
        <div className="min-w-0 text-sm">
          {idea.result_line && (
            <p className="truncate font-semibold tabular-nums text-white">
              {idea.result_line}
              {pText(idea.result_p) && <span className="ml-2 text-xs font-normal text-slate-500">{pText(idea.result_p)}</span>}
            </p>
          )}
          {idea.live && <div className="[&_.text-lg]:!text-sm"><PaperLine live={idea.live} mode={idea.status === "live" ? "paper" : "forward"} /></div>}
        </div>
      </li>
    );
  }
  return (
    <li className="relative h-full rounded-lg border border-slate-800 bg-slate-900/60 p-3 hover:border-slate-600">
      {chips}
      {demoted && (
        <p className="mt-1 text-xs text-amber-300/90">
          Passed as run — demoted under the hub-wide standard
          {idea.wf_ok === false ? " (walk-forward)" : idea.p_ok === false ? " (p over 0.01)" : idea.fdr_pass === false ? " (FDR over all tests)" : ""}
        </p>
      )}
      <h3 className="mt-2 font-semibold text-white">
        <Link to={to(idea.id)} className="after:absolute after:inset-0">{idea.title}</Link>
      </h3>
      {idea.claim && <p className="mt-0.5 text-sm text-slate-400">{claimLabel(idea.claim)}</p>}
      {/* Performance is the card's headline (Kevin, 2026-11-02): the result a
          reader is scanning for gets the biggest type on the card. */}
      {idea.result_line && (
        <div className="mt-3">
          <p className="text-[1.45rem] font-semibold leading-tight tabular-nums text-white">{idea.result_line}</p>
          <p className="mt-0.5 text-xs text-slate-500">
            out-of-sample{pText(idea.result_p) && <> · {pText(idea.result_p)}</>}
          </p>
        </div>
      )}
      {idea.live && <div className="mt-3"><PaperLine live={idea.live} mode={idea.status === "live" ? "paper" : "forward"} /></div>}
      {idea.kind !== "event" && (
        <div className="relative z-10 mt-3">
          <PlayCheckButton ideaId={idea.id} source="public" title={idea.title} />
        </div>
      )}
    </li>
  );
}

/** The public Ideas record: what still stands leads, grouped by the bet it
 * actually is; everything that no longer passes sits under Removed, still
 * on the record (Kevin, 2026-11-03 trim). */
/** The idea that speaks for a bet: one trading now, else the best result on unseen years. */
export function betLead(group: PublicIdea[]): PublicIdea {
  return [...group].sort((a, b) => Number((b.live_books ?? []).length > 0) - Number((a.live_books ?? []).length > 0)
    || (b.result_value ?? -Infinity) - (a.result_value ?? -Infinity))[0];
}

// ---- The page: a glanceable dashboard; every list is 5 rows with Show all (DESIGN-RULES 1-3) ----

/** Where an idea stands in its lifecycle, as a chip beside the verdict. Drafts show no chip. */
export function LifecycleChip({ row }: { row: IdeaRow }) {
  const chip = row.killed_at
    ? { label: "Killed", cls: toneClass.bad }
    : row.live_at
      ? { label: "Live", cls: toneClass.ok }
      : row.tracked_at
        ? { label: "Tracking", cls: "border-sky-500/40 bg-sky-500/10 text-sky-300" }
        : row.published_at
          ? { label: "Published", cls: toneClass.flat }
          : null;
  if (!chip) return null;
  return <span className={`rounded-full border px-2 py-0.5 font-semibold ${chip.cls}`}>{chip.label}</span>;
}

function ideaGroup(row: IdeaRow): "live" | "tracking" | "published" | "draft" | "killed" {
  if (row.killed_at) return "killed";
  if (row.live_at) return "live";
  if (row.tracked_at) return "tracking";
  if (row.published_at) return "published";
  return "draft";
}

const GROUP_LABEL = { live: "Live", tracking: "Tracking", published: "Published", draft: "Drafts", killed: "Killed" } as const;

/** The admin list: every idea, drafts included (what the Workshop's Ideas tab showed). */
function WorkshopRows({ rows }: { rows: IdeaRow[] }) {
  return (
    <ul className="mt-3 space-y-2">
      {rows.map((i) => (
        <li key={i.id} className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 hover:border-slate-600">
          <Link to={`/workshop/${i.id}`} className="flex items-center justify-between gap-3 py-2.5 hover:text-white">
            <span className="text-slate-200">{i.title}</span>
            <span className="flex shrink-0 flex-wrap items-center justify-end gap-3 text-xs text-slate-400">
              {i.runs} {i.runs === 1 ? "run" : "runs"}
              <LifecycleChip row={i} />
              <span className={`rounded-full border px-2 py-0.5 font-semibold ${toneClass[verdictTone(i.verdict_now ?? i.latest_verdict)]}`}>
                {i.verdict_now ?? i.latest_verdict ?? "Not run"}
              </span>
              {i.verdict_now != null && i.latest_verdict != null && i.verdict_now !== i.latest_verdict && (
                <span className="text-slate-500">as run {i.latest_verdict}</span>
              )}
              {i.batch && (
                <span className="text-slate-500">
                  Trial {i.batch.position} of {i.batch.size} in {i.batch.id}
                  {i.batch.trial != null && i.batch.trial !== i.batch.position ? ` · lab trial ${i.batch.trial}` : ""}
                </span>
              )}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

type View = "standing" | "removed" | "workshop";

/** Show all: the full list with its sort, grouping and filters; Removed is a filter, and the admin's
 * "All incl. drafts" is the old Workshop Ideas tab (every idea by lifecycle). */
function AllIdeas({ ideas, rows, admin, to }: { ideas: PublicIdea[]; rows: IdeaRow[] | null; admin: boolean; to: (id: number) => string }) {
  const [view, setView] = useState<View>("standing");
  const [sort, setSort] = useState<SortKey>("grouped");
  const flat = sort !== "grouped";
  const { standingIdeas, removed } = useMemo(
    () => ({ standingIdeas: ideas.filter(standing), removed: ideas.filter((i) => !standing(i)) }), [ideas]);
  const sortedStanding = useMemo(() => {
    const all = [...standingIdeas];
    if (sort === "value") all.sort((a, b) => (b.result_value ?? -Infinity) - (a.result_value ?? -Infinity));
    else if (sort === "p") all.sort((a, b) => (a.result_p ?? Infinity) - (b.result_p ?? Infinity));
    else if (sort === "newest") all.sort((a, b) => b.published_at.localeCompare(a.published_at));
    else if (sort === "title") all.sort((a, b) => a.title.localeCompare(b.title));
    return all;
  }, [standingIdeas, sort]);
  const [groupBy, setGroupBy] = useState<GroupKey>(() => {
    try {
      const v = window.localStorage.getItem("atr:ideas-group");
      return v === "sector" || v === "tag" ? v : "bet";
    } catch {
      return "bet";
    }
  });
  const chooseGroup = (g: GroupKey) => {
    setGroupBy(g);
    try { window.localStorage.setItem("atr:ideas-group", g); } catch { /* the choice lasts this visit */ }
  };
  const trading = useMemo(() => standingIdeas.filter((i) => (i.live_books ?? []).length > 0), [standingIdeas]);
  const shadowGroups = useMemo(() => groupShadow(standingIdeas, groupBy), [standingIdeas, groupBy]);
  const groups = (Object.keys(GROUP_LABEL) as (keyof typeof GROUP_LABEL)[])
    .map((g) => ({ g, rows: (rows ?? []).filter((i) => ideaGroup(i) === g) }))
    .filter((x) => x.rows.length > 0);
  const views: View[] = admin ? ["standing", "removed", "workshop"] : ["standing", "removed"];
  const VIEW_LABEL: Record<View, string> = { standing: "Standing", removed: "Removed", workshop: "All incl. drafts" };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <Segments label="Filter" options={views} value={view} onChange={setView} render={(v) => `${VIEW_LABEL[v]}${v === "removed" ? ` · ${removed.length}` : ""}`} />
        {view === "standing" && (
          <span className="flex items-center gap-2">
            <label htmlFor="ideas-sort" className="text-slate-400">Sort</label>
            <select id="ideas-sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}
                    className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100">
              {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => <option key={k} value={k}>{SORT_LABEL[k]}</option>)}
            </select>
          </span>
        )}
      </div>
      {view === "standing" && flat && (
        <section className="mt-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            Standing ideas <span className="text-slate-600">· {sortedStanding.length} · {SORT_LABEL[sort].toLowerCase()}</span>
          </h3>
          <p className="mt-1 text-xs text-slate-500">the claim differs by idea, so read the metric with its claim</p>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {sortedStanding.map((idea) => <IdeaCard key={idea.id} idea={idea} to={to} showKind />)}
          </ul>
        </section>
      )}
      {view === "standing" && !flat && (
        <>
          {trading.length > 0 && (
            <section aria-label="Trading now" className="mt-4">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-emerald-300">
                Trading now <span className="text-slate-600">· {trading.length} on a paper book</span>
              </h3>
              <ul className="mt-2 rounded-lg border border-slate-800 bg-slate-900/50 px-3">
                {trading.map((idea) => <IdeaCard key={idea.id} idea={idea} to={to} compact />)}
              </ul>
            </section>
          )}
          {shadowGroups.length > 0 && (
            <section aria-label="In shadow" className="mt-5">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-sky-300">
                  In shadow <span className="text-slate-600">· tracked or backtested, not trading</span>
                </h3>
                <div className="flex items-center gap-2 text-sm">
                  <label htmlFor="ideas-group" className="text-slate-400">Group by</label>
                  <select id="ideas-group" value={groupBy} onChange={(e) => chooseGroup(e.target.value as GroupKey)}
                          className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100">
                    <option value="bet">Bet</option>
                    <option value="sector">Sector</option>
                    <option value="tag">Tag</option>
                  </select>
                </div>
              </div>
              {shadowGroups.map((g) => (
                <details key={g.key} className="group/g mt-3 rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2">
                  <summary className="cursor-pointer list-none text-sm font-semibold text-slate-300 hover:text-white">
                    <span className="mr-1 inline-block transition-transform group-open/g:rotate-90" aria-hidden="true">›</span>
                    {g.label} <span className="font-normal text-slate-500">· {g.ideas.length}{g.note ? ` · ${g.note}` : ""}</span>
                    {g.ideas[0]?.result_line && (
                      <span className="ml-2 font-normal text-slate-400">top result: {g.ideas[0].title} · {g.ideas[0].result_line}</span>
                    )}
                  </summary>
                  <ul className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                    {g.ideas.map((idea) => <IdeaCard key={`${g.key}-${idea.id}`} idea={idea} to={to} />)}
                  </ul>
                </details>
              ))}
            </section>
          )}
          {trading.length === 0 && shadowGroups.length === 0 && <p className="mt-4 text-sm text-slate-400">Nothing standing.</p>}
        </>
      )}
      {view === "removed" && (
        <section aria-label="Removed" className="mt-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Removed under the current standard <span className="text-slate-600">· {removed.length} · kept on the record</span>
          </h3>
          {removed.length === 0 && <p className="mt-2 text-sm text-slate-400">Nothing removed.</p>}
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {removed.map((idea) => <IdeaCard key={idea.id} idea={idea} to={to} showKind />)}
          </ul>
        </section>
      )}
      {view === "workshop" && (
        <div className="mt-4 space-y-6">
          {rows === null && <p className="text-sm text-slate-400">Loading…</p>}
          {rows?.length === 0 && <p className="text-sm text-slate-400">No ideas yet.</p>}
          {groups.map(({ g, rows: rs }) => (
            <details key={g} open={g === "live" || g === "tracking"}>
              <summary className="cursor-pointer text-lg font-semibold text-white">
                {GROUP_LABEL[g]} <span className="text-sm font-normal text-slate-500">· {rs.length}</span>
              </summary>
              <WorkshopRows rows={rs} />
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

/** One list card: its top 5 rows, and Show all in a full view. */
function ListCard({ title, meta, rows, empty, full }: {
  title: string; meta?: ReactNode; rows: Parameters<typeof PeekRows>[0]["rows"]; empty?: string; full: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label={title} className="min-w-0 rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="truncate text-xs font-semibold uppercase tracking-wide text-slate-400">
          {title} {meta != null && <span className="font-normal normal-case text-slate-500">· {meta}</span>}
        </h2>
        <button type="button" onClick={() => setOpen(true)} aria-label={`Show all ${title}`} aria-haspopup="dialog"
                className="shrink-0 text-xs text-emerald-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
          Show all
        </button>
      </div>
      <div className="mt-2"><PeekRows rows={rows.slice(0, PEEK)} empty={empty} /></div>
      {open && <FullView title={title} onClose={() => setOpen(false)}>{full}</FullView>}
    </section>
  );
}

const verdictChip = (v: string | null | undefined, as: IdeaRow["latest_verdict"]) => (
  <span className={`rounded border px-1.5 py-0 text-[11px] font-semibold ${toneClass[verdictTone(as)]}`}>{v ?? "Not run"}</span>
);

/** Sector tone, one card (the Workshop's Sector tone tab): how many sectors' news tone is a standard deviation off. */
function ToneCard() {
  const [z, setZ] = useState<(number | null)[] | null>(null);
  useEffect(() => {
    adminCall<{ sectors?: { z: number | null }[] }>("/api/workshop/tone")
      .then((d) => setZ(Array.isArray(d?.sectors) ? d.sectors.map((s) => s.z) : null))
      .catch(() => setZ(null));
  }, []);
  if (z === null) return null;  // the panel is an extra; its absence must not break the page
  const known = z.filter((v): v is number => v != null);
  return (
    <DashCard title="Sector tone" value={known.length ? String(known.filter((v) => Math.abs(v) >= 1).length) : "—"}
              sub={`of ${known.length || "—"} sectors beyond ±1 z`} detail={<SectorTonePanel />} detailTitle="Sector news tone"
              hint="How many SPDR sectors' news tone is a standard deviation off its own 60 days" />
  );
}

export default function Ideas() {
  const session = useAdminSession();
  const admin = session === "admin";
  const to = (id: number) => (admin ? `/workshop/${id}` : `/ideas/${id}`);
  const { data, error, loading } = useApi<PublicIdea[]>("/api/ideas");
  const { data: summary } = useApi<{ tested: number; passed: number; failed: number; not_enough_data: number; published: number }>("/api/ideas/summary");
  const { data: criticSummary } = useApi<{ counts: { PAUSE: number; WATCH: number; HOLD: number }; units: number; worst: { idea_id: number; title: string | null; book: string; degradation: number }[] }>("/api/ideas/critic-summary");
  // Admin extras (drafts, the dashboard totals): never requested for a visitor.
  const [rows, setRows] = useState<IdeaRow[] | null>(null);
  const [dash, setDash] = useState<WorkshopDashboard | null>(null);
  const [adminError, setAdminError] = useState<string | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  useEffect(() => {
    if (!admin) return;
    adminCall<IdeaRow[]>("/api/workshop/ideas").then((d) => setRows(Array.isArray(d) ? d : [])).catch((e: Error) => setAdminError(e.message));
    adminCall<WorkshopDashboard>("/api/workshop/dashboard").then((d) => setDash(d?.ideas ? d : null)).catch(() => setDash(null));
  }, [admin]);

  const ideas = useMemo(() => (Array.isArray(data) ? data : []), [data]);
  const standingIdeas = useMemo(() => ideas.filter(standing), [ideas]);
  const trading = useMemo(() => standingIdeas.filter((i) => (i.live_books ?? []).length > 0), [standingIdeas]);
  const shadowGroups = useMemo(() => groupShadow(standingIdeas, "bet"), [standingIdeas]);
  const nShadow = standingIdeas.length - trading.length;
  const nTracking = standingIdeas.filter((i) => i.status === "tracking").length;
  const books = (b: string) => trading.filter((i) => (i.live_books ?? []).includes(b)).length;

  const all = <AllIdeas ideas={ideas} rows={rows} admin={admin} to={to} />;
  const num = (v: unknown) => (typeof v === "number" ? v : null);
  const verdicts = dash?.runs.latest_verdicts;
  const pass = verdicts ? (verdicts.PASS ?? 0) : num(summary?.passed);
  const fail = verdicts ? (verdicts.FAIL ?? 0) : num(summary?.failed);
  const ned = verdicts ? (verdicts.NOT_ENOUGH_DATA ?? 0) : num(summary?.not_enough_data);
  const asRun = dash?.runs.latest_verdicts_as_run?.PASS ?? 0;
  const dim = (v: number | null) => (v == null ? "—" : String(v));
  const critic = criticSummary && typeof criticSummary.units === "number" && criticSummary.units > 0 ? criticSummary : null;

  const tradingRows = trading.map((i) => ({
    key: String(i.id),
    label: <Link to={to(i.id)} className="hover:underline underline-offset-2">{i.title}</Link>,
    aside: (i.live_books ?? []).map((b) => (b === "big" ? "$1M" : "Main")).join(" · "),
    value: <>{signedPct(i.live?.return_pct)} vs {signedPct(i.live?.bench_return_pct)}{i.live?.state === "stale" ? " · stale" : ""} · {verdictChip(i.verdict_now ?? i.latest_verdict, i.verdict_now ?? i.latest_verdict)}</>,
  }));
  const shadowRows = shadowGroups.map((g) => ({
    key: g.key,
    label: <Link to={to(g.ideas[0].id)} className="inline-block min-w-[8rem] max-w-full truncate align-bottom hover:underline underline-offset-2">{g.ideas[0].title}</Link>,
    // The bet's name and tickers live in the full view; the row keeps title + result.
    // The result line is long; cap it so the title keeps its room (full text on hover).
    value: <span className="inline-block max-w-[9rem] truncate align-bottom xl:max-w-[14rem]" title={g.ideas[0].result_line ?? undefined}>{g.ideas[0].result_line ?? "—"}</span>,
  }));
  const activity = admin && dash
    ? dash.runs.recent.map((r, i) => ({
        key: `${r.idea_id}-${i}`,
        label: <Link to={to(r.idea_id)} className="hover:underline underline-offset-2">{r.title ?? `Idea ${r.idea_id}`}</Link>,
        aside: r.at?.slice(0, 10) ?? "—",
        value: verdictChip(r.verdict, r.verdict as IdeaRow["latest_verdict"]),
      }))
    : [...ideas].sort((a, b) => b.published_at.localeCompare(a.published_at)).map((i) => ({
        key: String(i.id),
        label: <Link to={to(i.id)} className="hover:underline underline-offset-2">{i.title}</Link>,
        aside: i.published_at.slice(0, 10),
        value: (i.verdict_now ?? i.latest_verdict) ? verdictChip(i.verdict_now ?? i.latest_verdict, i.verdict_now ?? i.latest_verdict) : "",
      }));

  return (
    <div className="mx-auto max-w-7xl px-4 py-5 md:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Ideas</h1>
          <p className="mt-1 text-sm text-slate-400">What still passes leads. Everything removed stays on the record.</p>
        </div>
        {admin && (
          <button type="button" onClick={() => setNewOpen(true)} aria-haspopup="dialog"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-sm font-medium text-emerald-300 hover:bg-emerald-500/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
            <Plus className="h-4 w-4" aria-hidden="true" /> New idea
          </button>
        )}
      </div>
      {newOpen && <FullView title="New idea" onClose={() => setNewOpen(false)}><NewIdeaBox /></FullView>}
      {loading && <Loader2 className="mt-8 h-5 w-5 animate-spin text-slate-400" aria-label="Loading" />}
      {error && <p role="alert" className="mt-8 text-sm text-rose-300">{error}</p>}
      {adminError && <p role="alert" className="mt-3 text-sm text-rose-300">{adminError}</p>}
      {data && ideas.length === 0 && <p className="mt-8 text-sm text-slate-400">No ideas published yet.</p>}

      <div className={`mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 ${admin ? "xl:grid-cols-6" : "xl:grid-cols-4"}`}>
        <DashCard title="Live" value={String(trading.length)} valueClass="text-emerald-300"
                  sub={`${books("main")} main · ${books("big")} on $1M`} detailTitle="Trading now"
                  detail={(
                    <div className="space-y-5">
                      <PeekRows rows={tradingRows} empty="Nothing is trading live." />
                      {admin && dash && (
                        <section aria-label="Closed paper P&L by idea">
                          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Closed paper P&L by idea</h3>
                          <div className="mt-2">
                            <PeekRows empty="No closed paper trades yet."
                                      rows={dash.fills.closed_pnl_by_idea.map((r) => ({
                                        key: r.idea, label: r.idea, aside: `${r.trades} trades`,
                                        value: fmtUsd(r.pnl, { signed: true }), valueClass: r.pnl >= 0 ? "text-emerald-300" : "text-rose-300" }))} />
                          </div>
                        </section>
                      )}
                    </div>
                  )} />
        <DashCard title="Shadow and tracking" value={String(nShadow)} sub={`${nTracking} tracking · ${nShadow - nTracking} backtest only`}
                  detailTitle="In shadow, by bet" detail={<PeekRows rows={shadowRows} empty="Nothing in shadow." />} />
        <DashCard title="Tests under the current bar" value={pass == null ? "—" : `${pass} PASS`}
                  sub={`${dim(fail)} fail · ${dim(ned)} not enough data${dash && asRun !== (verdicts?.PASS ?? 0) ? ` · as run ${asRun} PASS` : ""}`}
                  hint="Latest verdict per idea, judged against every test the hub has run"
                  detail={(
                    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                      <Fig label="Pass" value={dim(pass)} className="text-emerald-300" />
                      <Fig label="Fail" value={dim(fail)} className="text-rose-300" />
                      <Fig label="Not enough data" value={dim(ned)} />
                      {summary && typeof summary.tested === "number" && <Fig label="Ideas tested" value={summary.tested} />}
                      {summary && typeof summary.published === "number" && <Fig label="Published here" value={summary.published} />}
                      {dash && <Fig label="Tests kept" value={dash.runs.saved} hint={`${dash.runs.total} runs incl. previews`} />}
                      {dash && <Fig label="Runs incl. previews" value={dash.runs.total} />}
                      {dash && <Fig label="Passed as run" value={asRun} />}
                    </dl>
                  )} />
        <DashCard title="Weekly critic" value={critic ? `${critic.counts.PAUSE} pause` : "—"}
                  sub={critic ? `${critic.counts.WATCH} watch · ${critic.counts.HOLD} hold` : "no live ideas graded"}
                  detailTitle="Weekly critic" detail={critic && (
                    <PeekRows empty="Nothing flagged."
                              rows={critic.worst.map((w) => ({ key: `${w.idea_id}-${w.book}`, label: <Link to={to(w.idea_id)} className="hover:underline">{w.title ?? `#${w.idea_id}`}</Link>,
                                aside: w.book === "big" ? "$1M" : "Main", value: `${w.degradation >= 0 ? "+" : ""}${w.degradation.toFixed(1)} vs claim` }))} />
                  )} />
        {admin && (
          <DashCard title="Needs label" value={dash ? String(dash.fills.needs_label) : "—"} valueClass={dash && dash.fills.needs_label > 0 ? "text-amber-300" : "text-white"}
                    sub={dash ? (dash.fills.state === "live" ? `${dash.fills.attributed}/${dash.fills.total} fills attributed` : "account not connected") : undefined}
                    detailTitle="Trade labels" detail={<TradeLabels ideas={rows ?? []} />} />
        )}
        {admin && <ToneCard />}
      </div>

      <div className="mt-3 space-y-3">
        <ListCard title="Trading now" meta={`${trading.length} on a paper book`} rows={tradingRows} empty="Nothing is trading live." full={all} />
        <div className="grid gap-3 lg:grid-cols-2">
          <ListCard title="In shadow" meta="by bet" rows={shadowRows} empty="Nothing in shadow." full={all} />
          <ListCard title={admin && dash ? "Latest test activity" : "Newest ideas"} rows={activity} empty="No saved runs yet."
                    full={<PeekRows rows={activity} empty="No saved runs yet." />} />
        </div>
      </div>
    </div>
  );
}
