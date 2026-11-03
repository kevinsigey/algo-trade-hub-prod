import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { PlayCheckButton } from "@/components/PlayCheck";
import { useApi } from "@/hooks/usePaperPortfolio";
import NewIdeaBox from "@/components/NewIdeaBox";
import { adminJson } from "@/lib/workshop";
import { EARLY_N } from "@/lib/sample";
import { claimLabel, KIND_LABEL, STATUS_LABEL, verdictTone, type PublicIdea, type ShadowSummary } from "@/lib/workshop";
import { toneClass } from "@/pages/Workshop";

export const signedPct = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`);

export const pText = (p: number | null | undefined) => (p == null ? null : p < 0.001 ? "p < 0.001" : `p = ${p.toFixed(3)}`);

type SortKey = "grouped" | "value" | "p" | "newest" | "title";

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
  if (idea.status === "live" || idea.status === "tracking") return true;
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

function IdeaCard({ idea, showKind = false }: { idea: PublicIdea; showKind?: boolean }) {
  const verdict = idea.verdict_now ?? idea.latest_verdict;
  const demoted = idea.verdict_now != null && idea.latest_verdict != null && idea.verdict_now !== idea.latest_verdict;
  return (
    <li className="relative h-full rounded-xl border border-slate-800 bg-slate-900/60 p-4 hover:border-slate-600">
      <div className="flex flex-wrap items-center gap-2">
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
      {demoted && (
        <p className="mt-1 text-xs text-amber-300/90">
          Passed as run — demoted under the hub-wide standard
          {idea.wf_ok === false ? " (walk-forward)" : idea.fdr_pass === false ? " (FDR over all tests)" : ""}
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
export default function Ideas() {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    let cancelled = false;
    adminJson("/api/admin/me").then(() => { if (!cancelled) setSignedIn(true); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);
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
  const families = useMemo(() => {
    const byKey = new Map<number, PublicIdea[]>();
    const singles: PublicIdea[] = [];
    for (const idea of standingIdeas) {
      if (idea.family && idea.family.size > 1) {
        const arr = byKey.get(idea.family.key) ?? [];
        arr.push(idea);
        byKey.set(idea.family.key, arr);
      } else singles.push(idea);
    }
    const groups = [...byKey.values()].sort((a, b) =>
      Math.max(...b.map((i) => i.result_value ?? -Infinity)) - Math.max(...a.map((i) => i.result_value ?? -Infinity)));
    return { groups, singles };
  }, [standingIdeas]);
  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
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
      {signedIn && <NewIdeaBox />}
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
          <ul className="mt-3 grid gap-3 sm:grid-cols-2">
            {sortedStanding.map((idea) => <IdeaCard key={idea.id} idea={idea} showKind />)}
          </ul>
        </section>
      ) : (
        <>
          {families.groups.map((group) => (
            <section key={group[0].family!.key} className="mt-8">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
                One bet · {group[0].family!.tickers.join(" · ")} <span className="text-slate-600">· {group.length} ideas, one position underneath</span>
              </h2>
              <ul className="mt-3 grid gap-3 sm:grid-cols-2">
                {group.map((idea) => <IdeaCard key={idea.id} idea={idea} />)}
              </ul>
            </section>
          ))}
          {families.singles.length > 0 && (
            <section className="mt-8">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
                Standalone <span className="text-slate-600">· {families.singles.length}</span>
              </h2>
              <ul className="mt-3 grid gap-3 sm:grid-cols-2">
                {families.singles.map((idea) => <IdeaCard key={idea.id} idea={idea} />)}
              </ul>
            </section>
          )}
        </>
      )}
      {removed.length > 0 && (
        <details className="mt-10">
          <summary className="cursor-pointer text-sm font-semibold uppercase tracking-wide text-slate-500">
            Removed under the current standard <span className="text-slate-600">· {removed.length} · kept on the record</span>
          </summary>
          <ul className="mt-3 grid gap-3 sm:grid-cols-2">
            {removed.map((idea) => <IdeaCard key={idea.id} idea={idea} showKind />)}
          </ul>
        </details>
      )}
    </div>
  );
}
