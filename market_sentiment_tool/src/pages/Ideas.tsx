import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { PlayCheckButton } from "@/components/PlayCheck";
import { useApi } from "@/hooks/usePaperPortfolio";
import { EARLY_N } from "@/lib/sample";
import { claimLabel, KIND_LABEL, STATUS_LABEL, verdictTone, type IdeaKind, type PublicIdea, type ShadowSummary } from "@/lib/workshop";
import { toneClass } from "@/pages/Workshop";

const KIND_ORDER: IdeaKind[] = ["event", "long_short", "wrapped", "long_only"];

export const signedPct = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`);

export const pText = (p: number | null | undefined) => (p == null ? null : p < 0.001 ? "p < 0.001" : `p = ${p.toFixed(3)}`);

type SortKey = "grouped" | "value" | "p" | "newest" | "title";

const SORT_LABEL: Record<SortKey, string> = {
  grouped: "Grouped by type",
  value: "Strongest result",
  p: "Most significant (lowest p)",
  newest: "Newest first",
  title: "Title A–Z",
};

/** One line of paper record: idea vs benchmark since go-live, its as-of, and the failing flag. */
export function PaperLine({ live }: { live: ShadowSummary }) {
  if (live.days === 0)
    return live.state === "stale"
      ? <p className="text-sm text-amber-300">No paper days recorded since going live · stale</p>
      : <p className="text-sm text-slate-400">Paper record starts on the next trading day.</p>;
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
      <span className="font-mono text-lg text-white">{signedPct(live.return_pct)}</span>
      <span className="text-slate-400">benchmark {signedPct(live.bench_return_pct)}</span>
      <span className="text-slate-500">
        {live.days} days · as of {live.as_of}
        {live.state === "stale" && " · stale"}
      </span>
      {live.days < EARLY_N ? (
        <span className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-300">Too early to say</span>
      ) : live.failing ? (
        <span className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-xs text-rose-300">Claim failing on paper</span>
      ) : null}
    </div>
  );
}

function IdeaCard({ idea, showKind = false }: { idea: PublicIdea; showKind?: boolean }) {
  return (
    <li className="relative h-full rounded-xl border border-slate-800 bg-slate-900/60 p-4 hover:border-slate-600">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${toneClass[verdictTone(idea.latest_verdict)]}`}>{idea.latest_verdict ?? "Not run"}</span>
        <span className="text-xs text-slate-500">{STATUS_LABEL[idea.status]}</span>
        <span className="text-xs text-slate-500">· {idea.variations} {idea.variations === 1 ? "run" : "runs"}</span>
        {showKind && <span className="text-xs text-slate-500">· {KIND_LABEL[idea.kind]}</span>}
      </div>
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
      {idea.live && <div className="mt-3"><PaperLine live={idea.live} /></div>}
      {idea.kind !== "event" && (
        <div className="relative z-10 mt-3">
          <PlayCheckButton ideaId={idea.id} source="public" title={idea.title} />
        </div>
      )}
    </li>
  );
}

/** The public Ideas record (Trading HQ spec §4.1): every published idea, fails and kills included. */
export default function Ideas() {
  const { data, error, loading } = useApi<PublicIdea[]>("/api/ideas");
  const { data: summary } = useApi<{ tested: number; passed: number; failed: number; not_enough_data: number; published: number }>("/api/ideas/summary");
  const [sort, setSort] = useState<SortKey>("grouped");
  const flat = sort === "value" || sort === "p";
  const sortedAll = useMemo(() => {
    const all = [...(data ?? [])];
    if (sort === "value") all.sort((a, b) => (b.result_value ?? -Infinity) - (a.result_value ?? -Infinity));
    else if (sort === "p") all.sort((a, b) => (a.result_p ?? Infinity) - (b.result_p ?? Infinity));
    else if (sort === "newest") all.sort((a, b) => b.published_at.localeCompare(a.published_at));
    else if (sort === "title") all.sort((a, b) => a.title.localeCompare(b.title));
    return all;
  }, [data, sort]);
  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
      <h1 className="text-2xl font-bold tracking-tight text-white">Ideas</h1>
      <p className="mt-1 text-sm text-slate-400">Every idea published here stays here, pass, fail or killed.</p>
      {summary && (
        <p className="mt-1 text-xs text-slate-500">
          Workshop record: {summary.tested} ideas tested · {summary.passed} passed · {summary.failed} failed · {summary.not_enough_data} not enough data · {summary.published} published here
        </p>
      )}
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
          {flat && <span className="text-xs text-slate-500">across all types — the claim differs by idea, so read the metric with its claim</span>}
        </div>
      )}
      {loading && <Loader2 className="mt-8 h-5 w-5 animate-spin text-slate-400" aria-label="Loading" />}
      {error && <p role="alert" className="mt-8 text-sm text-rose-300">{error}</p>}
      {data && data.length === 0 && <p className="mt-8 text-sm text-slate-400">No ideas published yet.</p>}
      {flat ? (
        <section className="mt-8">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            All ideas <span className="text-slate-600">· {sortedAll.length} · {SORT_LABEL[sort].toLowerCase()}</span>
          </h2>
          <ul className="mt-3 grid gap-3 sm:grid-cols-2">
            {sortedAll.map((idea) => <IdeaCard key={idea.id} idea={idea} showKind />)}
          </ul>
        </section>
      ) : (
        /* Grouped by type, in a grid (Kevin, 2026-11-02): the flat list stopped scanning
            once the published set grew past a screenful. */
        KIND_ORDER.map((kind) => {
          const group = sortedAll.filter((i) => i.kind === kind);
          if (group.length === 0) return null;
          return (
            <section key={kind} className="mt-8">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
                {KIND_LABEL[kind]} <span className="text-slate-600">· {group.length}</span>
              </h2>
              <ul className="mt-3 grid gap-3 sm:grid-cols-2">
                {group.map((idea) => <IdeaCard key={idea.id} idea={idea} />)}
              </ul>
            </section>
          );
        })
      )}
    </div>
  );
}
