import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronDown, Loader2 } from "lucide-react";
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { PlayCheckButton } from "@/components/PlayCheck";
import { getJson } from "@/lib/getJson";
import { fmtUsd } from "@/lib/paperPortfolio";
import { claimLabel, STATUS_LABEL, verdictTone, type PublicIdeaDetail } from "@/lib/workshop";
import { PaperLine, signedPct } from "@/pages/Ideas";
import { toneClass } from "@/pages/Workshop";

const pct = (v: number | null | undefined, digits = 1) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}%`);

function Mark({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="text-slate-400">~</span>;
  return ok ? <span className="text-emerald-400">✓</span> : <span className="text-rose-400">✗</span>;
}

type PublicRun = PublicIdeaDetail["runs"][number];

const EMPTY_DETAIL: PublicRun["detail"] = {
  curve: [], reason: null, variations: null, claim: null, shuffle: null, t_test: null,
  periods: null, walk_forward: null, context: [], data_start: null, data_end: null,
  split_date: null, n_events: null, per_ticker: [], notes: null,
};

/**
 * One backtest run, opened (Kevin, 2026-11-02): the graph and the evidence that
 * already exist in the stored result -- the same curve and verdict table the
 * Workshop shows, on the public record. Nothing here is recomputed.
 */
function RunCard({ run }: { run: PublicRun }) {
  const [open, setOpen] = useState(false);
  const d = run.detail ?? EMPTY_DETAIL;
  return (
    <li className="rounded-lg border border-slate-800 bg-slate-900/60">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-3 px-3 py-2 text-left text-sm"
      >
        <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${toneClass[verdictTone(run.verdict)]}`}>{run.verdict}</span>
        <span className="text-white">{run.headline}</span>
        <span className="ml-auto flex items-center gap-2 font-mono text-xs text-slate-500">
          #{run.variation}
          {run.p != null && run.bar != null && ` · p ${run.p.toFixed(3)} vs bar ${run.bar.toFixed(3)}`}
          <ChevronDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
        </span>
      </button>
      {open && (
        <div className="border-t border-slate-800 px-3 py-3">
          {d.reason && <p className="text-sm text-slate-300">{d.reason}</p>}
          {(d.notes ?? []).map((n) => (
            <p key={n} className="mt-1 text-sm text-amber-200/90">{n}</p>
          ))}
          {d.curve.length > 1 && (
            <>
              <div className="mt-3 h-48" aria-label="Idea vs benchmark, cumulative">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={d.curve} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                    <XAxis dataKey="t" tickFormatter={(t: string) => t.slice(0, 4)} stroke="#64748b" fontSize={11} minTickGap={40} />
                    <YAxis tickFormatter={(v: number) => `${v.toFixed(0)}%`} stroke="#64748b" fontSize={11} width={48} />
                    <Tooltip
                      contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
                      formatter={(v: number, name: string) => [pct(v), name === "idea" ? "Idea" : "Benchmark"]}
                    />
                    {d.split_date && <ReferenceLine x={d.curve.find((p) => p.t >= d.split_date!)?.t} stroke="#94a3b8" strokeDasharray="3 3" label={{ value: "unseen years →", position: "insideTopRight", fill: "#94a3b8", fontSize: 11 }} />}
                    <Line type="monotone" dataKey="idea" stroke="#fbbf24" strokeWidth={2.5} dot={false} />
                    <Line type="monotone" dataKey="benchmark" stroke="#94a3b8" strokeWidth={2} strokeDasharray="4 3" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-1 text-xs text-slate-500">Cumulative return since {d.data_start}, % (not log)</p>
            </>
          )}
          {d.claim && d.shuffle && (
            <table className="mt-3 w-full text-sm">
              <tbody className="divide-y divide-slate-800/80">
                <tr><td className="py-1.5 text-slate-300">On the years it was built on</td><td className="py-1.5 text-slate-400">{d.claim.built.label}</td><td><Mark ok={d.claim.built.holds} /></td></tr>
                <tr><td className="py-1.5 text-slate-300">On the unseen years</td><td className="py-1.5 text-slate-400">{d.claim.unseen.label}</td><td><Mark ok={d.claim.unseen.holds} /></td></tr>
                <tr><td className="py-1.5 text-slate-300">Better than chance ({d.shuffle.method})</td><td className="py-1.5 text-slate-400">beats {d.shuffle.beats_pct.toFixed(0)}% of {d.shuffle.permutations.toLocaleString()} · p = {d.shuffle.p.toFixed(3)}, needs &lt; {d.shuffle.bar.toFixed(4).replace(/0+$/, "")}</td><td><Mark ok={d.shuffle.p < d.shuffle.bar} /></td></tr>
                {d.t_test && <tr><td className="py-1.5 text-slate-300">t-test, daily difference</td><td className="py-1.5 text-slate-400">{pct(d.t_test.mean_daily_diff, 3)}/day · p = {d.t_test.p.toFixed(3)}{d.t_test.p < 0.05 && d.t_test.mean_daily_diff < 0 ? " · significant, but the wrong way" : ""}</td><td><Mark ok={d.t_test.p < 0.05 ? d.t_test.mean_daily_diff > 0 : null} /></td></tr>}
                {d.periods && <tr><td className="py-1.5 text-slate-300">Holds in each market period</td><td className="py-1.5 text-slate-400">{d.periods.held} of {d.periods.of}</td><td><Mark ok={d.periods.held >= 4 ? true : d.periods.held <= 1 ? false : null} /></td></tr>}
                {d.walk_forward && <tr><td className="py-1.5 text-slate-300">Walk-forward, later stretches in order</td><td className="py-1.5 text-slate-400">{d.walk_forward.held} of {d.walk_forward.of} held</td><td><Mark ok={d.walk_forward.of === 0 ? null : d.walk_forward.held === d.walk_forward.of ? true : d.walk_forward.held === 0 ? false : null} /></td></tr>}
                {d.variations != null && <tr><td className="py-1.5 text-slate-300">Variations tried on this idea</td><td className="py-1.5 text-slate-400">{d.variations} · bar raised accordingly</td><td /></tr>}
                {d.batch && <tr><td className="py-1.5 text-slate-300">Search this idea belongs to</td><td className="py-1.5 text-slate-400">Trial {d.batch.position} of {d.batch.of} in {d.batch.id}{d.batch.trial != null && d.batch.trial !== d.batch.position ? ` · lab trial ${d.batch.trial}` : ""} · the bar above counts the whole search</td><td /></tr>}
              </tbody>
            </table>
          )}
          {d.walk_forward && d.walk_forward.folds.length > 0 && (
            <div className="mt-2 space-y-0.5 text-xs text-slate-400">
              {d.walk_forward.folds.map((f) => (
                <p key={f.start}>{f.start} → {f.end}: idea {pct(f.idea_cagr)} vs benchmark {pct(f.bench_cagr)} — {f.label}</p>
              ))}
            </div>
          )}
          {d.context.length > 0 && (
            <div className="mt-2 space-y-0.5 text-xs text-slate-400">
              {d.context.map((c) => (
                <p key={c.name}>{c.name}: built {pct(c.built_cagr)} · unseen {pct(c.unseen_cagr)}</p>
              ))}
            </div>
          )}
          {d.n_events != null && (
            <p className="mt-2 text-sm text-slate-300">{d.n_events} events measured.</p>
          )}
          {(d.per_ticker ?? []).length > 0 && (
            <table className="mt-2 w-full text-sm tabular-nums">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="py-1 font-medium">Ticker</th>
                  <th className="py-1 text-right font-medium">Events</th>
                  <th className="py-1 text-right font-medium">Mean</th>
                  <th className="py-1 text-right font-medium">Shrunk</th>
                  <th className="py-1 text-right font-medium">t</th>
                </tr>
              </thead>
              <tbody>
                {(d.per_ticker ?? []).map((t) => (
                  <tr key={t.ticker} className="border-t border-slate-800/60">
                    <td className="py-1 font-mono text-white">{t.ticker}</td>
                    <td className="py-1 text-right text-slate-300">{t.n}</td>
                    <td className="py-1 text-right text-slate-300">{pct(t.mean, 2)}</td>
                    <td className="py-1 text-right text-slate-300">{pct(t.shrunk, 2)}</td>
                    <td className="py-1 text-right text-slate-300">{t.t.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </li>
  );
}

/** One published idea: every verdict it got, its paper record since go-live, and the trades tagged to it. */
export default function IdeaRecord() {
  const raw = useParams().id ?? "";
  const id = /^\d+$/.test(raw) ? raw : null;
  const [data, setData] = useState<PublicIdeaDetail | null>(null);
  const [error, setError] = useState<string | null>(id ? null : "No such idea.");

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    getJson<PublicIdeaDetail>(`/api/ideas/${id}`)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setError("No such idea."));
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error) return <p className="mx-auto max-w-4xl px-4 py-8 text-sm text-slate-400 md:px-8">{error}</p>;
  if (!data) return <Loader2 className="mx-auto mt-16 h-5 w-5 animate-spin text-slate-400" aria-label="Loading" />;
  const curve = data.shadow?.curve ?? [];

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-8">
      <Link to="/ideas" className="text-sm text-slate-400 hover:text-white">← Ideas</Link>
      <h1 className="mt-3 text-2xl font-bold tracking-tight text-white">{data.title}</h1>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {data.status === "live" && (data.live_books ?? ["main"]).map((b) => (
          <span key={b} className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-300">
            Live · {b === "big" ? "$1M book" : "Main book"}{data.live_at ? ` · since ${data.live_at.slice(0, 10)}` : ""}
          </span>
        ))}
        {data.status === "tracking" && (
          <span className="rounded border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-xs font-semibold text-sky-300">
            Tracking{data.tracked_at ? ` since ${data.tracked_at.slice(0, 10)}` : ""} — not trading
          </span>
        )}
        {data.status === "killed" && (
          <span className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-xs font-semibold text-rose-300">
            Killed{data.killed_at ? ` ${data.killed_at.slice(0, 10)}` : ""}
          </span>
        )}
        {data.status === "backtest" && (
          <span className="rounded border border-slate-600 bg-slate-800 px-2 py-0.5 text-xs font-semibold text-slate-300">Backtest only</span>
        )}
        <span className="text-sm text-slate-400">
          {STATUS_LABEL[data.status]}
          {data.claim && ` · ${claimLabel(data.claim)}`}
        </span>
      </div>
      <p className="mt-3 text-slate-300">“{data.plain_words}”</p>
      {data.kind !== "event" && (
        <div className="mt-4">
          <PlayCheckButton ideaId={data.id} source="public" title={data.title} />
        </div>
      )}

      {data.shadow && (
        <section className="mt-8">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            {data.status === "live"
              ? `Paper record since ${data.live_at?.slice(0, 10)}`
              : `Forward record since tracking ${data.tracked_at?.slice(0, 10)}${data.killed_at ? ` · ended ${data.killed_at.slice(0, 10)}` : ""}`}
          </h2>
          <div className="mt-2"><PaperLine live={data.shadow} mode={data.status === "live" ? "paper" : "forward"} /></div>
          {data.shadow.claim && <p className="mt-1 text-sm text-slate-400">Last 3 months: {data.shadow.claim.label}</p>}
          {(data.shadow.exits?.length ?? 0) > 0 && (
            <p className="mt-1 flex flex-wrap gap-x-3 text-sm text-slate-400">
              Exits:
              {data.shadow.exits?.map((e) => <span key={e.day} className="text-amber-300">{e.why} · {e.day}</span>)}
            </p>
          )}
          {curve.length > 1 && (
            <div className="mt-4 h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={curve} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="t" tick={{ fill: "#94a3b8", fontSize: 11 }} minTickGap={40} />
                  <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v: number) => `${v.toFixed(0)}%`} width={40} />
                  <Tooltip formatter={(v: number) => signedPct(v)} contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
                  <Line type="monotone" dataKey="idea" name="Idea" stroke="#34d399" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="bench" name="Benchmark" stroke="#94a3b8" dot={false} strokeWidth={1.5} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>
      )}

      <section className="mt-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Every backtest run</h2>
        <p className="mt-1 text-xs text-slate-500">Open a run for its graph and the full evidence behind the verdict.</p>
        <ul className="mt-2 space-y-2">
          {data.runs.map((r) => <RunCard key={r.variation} run={r} />)}
        </ul>
      </section>

      {data.trades.length > 0 && (
        <section className="mt-8">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Paper trades on this idea</h2>
          <table className="mt-2 w-full text-sm">
            <tbody>
              {data.trades.map((t, i) => (
                <tr key={i} className="border-t border-slate-800">
                  <td className="py-2 font-mono text-white">{t.symbol}</td>
                  <td className="py-2 text-slate-400"><span className="whitespace-nowrap">{t.exited_at.slice(0, 10)}</span></td>
                  <td className="py-2 text-right font-mono text-slate-300">{signedPct(t.return_pct)}</td>
                  <td className="py-2 text-right font-mono text-slate-300">{fmtUsd(t.pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
