import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { PlayCheckButton } from "@/components/PlayCheck";
import { useApi } from "@/hooks/usePaperPortfolio";
import { EARLY_N } from "@/lib/sample";
import { claimLabel, KIND_LABEL, STATUS_LABEL, verdictTone, type IdeaKind, type PublicIdea, type ShadowSummary } from "@/lib/workshop";
import { toneClass } from "@/pages/Workshop";

const KIND_ORDER: IdeaKind[] = ["event", "long_short", "wrapped", "long_only"];

export const signedPct = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`);

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

/** The public Ideas record (Trading HQ spec §4.1): every published idea, fails and kills included. */
export default function Ideas() {
  const { data, error, loading } = useApi<PublicIdea[]>("/api/ideas");
  const { data: summary } = useApi<{ tested: number; passed: number; failed: number; not_enough_data: number; published: number }>("/api/ideas/summary");
  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
      <h1 className="text-2xl font-bold tracking-tight text-white">Ideas</h1>
      <p className="mt-1 text-sm text-slate-400">Every idea published here stays here, pass, fail or killed.</p>
      {summary && (
        <p className="mt-1 text-xs text-slate-500">
          Workshop record: {summary.tested} ideas tested · {summary.passed} passed · {summary.failed} failed · {summary.not_enough_data} not enough data · {summary.published} published here
        </p>
      )}
      {loading && <Loader2 className="mt-8 h-5 w-5 animate-spin text-slate-400" aria-label="Loading" />}
      {error && <p role="alert" className="mt-8 text-sm text-rose-300">{error}</p>}
      {data && data.length === 0 && <p className="mt-8 text-sm text-slate-400">No ideas published yet.</p>}
      {/* Grouped by type, in a grid (Kevin, 2026-11-02): the flat list stopped scanning
          once the published set grew past a screenful. */}
      {KIND_ORDER.map((kind) => {
        const group = (data ?? []).filter((i) => i.kind === kind);
        if (group.length === 0) return null;
        return (
          <section key={kind} className="mt-8">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
              {KIND_LABEL[kind]} <span className="text-slate-600">· {group.length}</span>
            </h2>
            <ul className="mt-3 grid gap-3 sm:grid-cols-2">
              {group.map((idea) => (
                <li key={idea.id} className="relative h-full rounded-xl border border-slate-800 bg-slate-900/60 p-4 hover:border-slate-600">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${toneClass[verdictTone(idea.latest_verdict)]}`}>{idea.latest_verdict ?? "Not run"}</span>
                    <span className="text-xs text-slate-500">{STATUS_LABEL[idea.status]}</span>
                    <span className="text-xs text-slate-500">· {idea.variations} {idea.variations === 1 ? "run" : "runs"}</span>
                  </div>
                  <h3 className="mt-2 font-semibold text-white">
                    <Link to={`/ideas/${idea.id}`} className="after:absolute after:inset-0">{idea.title}</Link>
                  </h3>
                  {idea.claim && <p className="mt-0.5 text-sm text-slate-400">{claimLabel(idea.claim)}</p>}
                  {idea.result_line && <p className="mt-0.5 text-sm font-medium tabular-nums text-slate-200">{idea.result_line}</p>}
                  {idea.live && <div className="mt-3"><PaperLine live={idea.live} /></div>}
                  {idea.kind !== "event" && (
                    <div className="relative z-10 mt-3">
                      <PlayCheckButton ideaId={idea.id} source="public" title={idea.title} />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
