import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { PlayCheckButton } from "@/components/PlayCheck";
import { useApi } from "@/hooks/usePaperPortfolio";
import NewIdeaBox from "@/components/NewIdeaBox";
import { useAdminSession } from "@/components/RequireAdmin";
import { EARLY_N } from "@/lib/sample";
import { claimLabel, KIND_LABEL, STATUS_LABEL, verdictTone, type PublicIdea, type ShadowSummary } from "@/lib/workshop";
import { toneClass } from "@/pages/Workshop";

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

function IdeaCard({ idea, showKind = false, compact = false }: { idea: PublicIdea; showKind?: boolean; compact?: boolean }) {
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
            <Link to={`/ideas/${idea.id}`} className="after:absolute after:inset-0 hover:underline underline-offset-2">{idea.title}</Link>
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
        <Link to={`/ideas/${idea.id}`} className="after:absolute after:inset-0">{idea.title}</Link>
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

export default function Ideas() {
  const session = useAdminSession();
  const { data, error, loading } = useApi<PublicIdea[]>("/api/ideas");
  const { data: summary } = useApi<{ tested: number; passed: number; failed: number; not_enough_data: number; published: number }>("/api/ideas/summary");
  const { data: criticSummary } = useApi<{ counts: { PAUSE: number; WATCH: number; HOLD: number }; units: number; worst: { idea_id: number; title: string | null; book: string; degradation: number }[] }>("/api/ideas/critic-summary");
  const [sort, setSort] = useState<SortKey>("grouped");
  const flat = sort !== "grouped";
  const { standingIdeas, removed } = useMemo(() => {
    const all = data ?? [];
    return { standingIdeas: all.filter(standing), removed: all.filter((i) => !standing(i)) };
  }, [data]);
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
  return (
    <div className="mx-auto max-w-7xl px-4 py-5 md:px-6">
      <h1 className="text-2xl font-bold tracking-tight text-white">Ideas</h1>
      <p className="mt-1 text-sm text-slate-400">What still passes leads. Everything removed stays on the record, one click down.</p>
      {summary && (
        <p className="mt-1 text-xs text-slate-500">
          Workshop record: {summary.tested} ideas tested · {summary.passed} passed · {summary.failed} failed · {summary.not_enough_data} not enough data · {summary.published} published here
        </p>
      )}
      {criticSummary && typeof criticSummary.units === "number" && criticSummary.units > 0 && (
        <p className="mt-1 text-xs text-slate-500">
          Weekly critic: {criticSummary.counts.PAUSE} pause · {criticSummary.counts.WATCH} watch · {criticSummary.counts.HOLD} hold
          {criticSummary.worst.length > 0 && (
            <> · worst: {criticSummary.worst.slice(0, 3).map((w) => `${w.title ?? `#${w.idea_id}`} (${w.degradation >= 0 ? "+" : ""}${w.degradation.toFixed(1)})`).join(", ")}</>
          )}
        </p>
      )}
      {session === "admin" && <NewIdeaBox />}
      {data && data.length > 1 && (
        <div className="mt-4 flex items-center gap-2 text-sm">
          <label htmlFor="ideas-sort" className="text-slate-400">Sort</label>
          <select
            id="ideas-sort"
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100"
          >
            {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => (
              <option key={k} value={k}>{SORT_LABEL[k]}</option>
            ))}
          </select>
          {flat && <span className="text-xs text-slate-500">the standing list — the claim differs by idea, so read the metric with its claim</span>}
        </div>
      )}
      {loading && <Loader2 className="mt-8 h-5 w-5 animate-spin text-slate-400" aria-label="Loading" />}
      {error && <p role="alert" className="mt-8 text-sm text-rose-300">{error}</p>}
      {data && data.length === 0 && <p className="mt-8 text-sm text-slate-400">No ideas published yet.</p>}
      {flat ? (
        <section className="mt-8">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            Standing ideas <span className="text-slate-600">· {sortedStanding.length} · {SORT_LABEL[sort].toLowerCase()}</span>
          </h2>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {sortedStanding.map((idea) => <IdeaCard key={idea.id} idea={idea} showKind />)}
          </ul>
        </section>
      ) : (
        <>
          {trading.length > 0 && (
            <section aria-label="Trading now" className="mt-5">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-emerald-300">
                Trading now <span className="text-slate-600">· {trading.length} on a paper book</span>
              </h2>
              <ul className="mt-2 rounded-lg border border-slate-800 bg-slate-900/50 px-3">
                {trading.map((idea) => <IdeaCard key={idea.id} idea={idea} compact />)}
              </ul>
            </section>
          )}
          {shadowGroups.length > 0 && (
            <section aria-label="In shadow" className="mt-6">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-sky-300">
                  In shadow <span className="text-slate-600">· tracked or backtested, not trading</span>
                </h2>
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
                    {g.ideas.map((idea) => <IdeaCard key={`${g.key}-${idea.id}`} idea={idea} />)}
                  </ul>
                </details>
              ))}
            </section>
          )}
        </>
      )}
      {removed.length > 0 && (
        <details className="mt-10">
          <summary className="cursor-pointer text-sm font-semibold uppercase tracking-wide text-slate-500">
            Removed under the current standard <span className="text-slate-600">· {removed.length} · kept on the record</span>
          </summary>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {removed.map((idea) => <IdeaCard key={idea.id} idea={idea} showKind />)}
          </ul>
        </details>
      )}
    </div>
  );
}
