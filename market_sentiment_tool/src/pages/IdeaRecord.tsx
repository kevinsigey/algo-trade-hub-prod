import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { getJson } from "@/lib/getJson";
import { fmtUsd } from "@/lib/paperPortfolio";
import { claimLabel, STATUS_LABEL, verdictTone, type PublicIdeaDetail } from "@/lib/workshop";
import { PaperLine, signedPct } from "@/pages/Ideas";
import { toneClass } from "@/pages/Workshop";

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
      <p className="mt-1 text-sm text-slate-400">
        {STATUS_LABEL[data.status]}
        {data.claim && ` · ${claimLabel(data.claim)}`}
        {data.killed_at && ` · killed ${data.killed_at.slice(0, 10)}`}
      </p>
      <p className="mt-3 text-slate-300">“{data.plain_words}”</p>

      {data.shadow && (
        <section className="mt-8">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Paper record since {data.live_at?.slice(0, 10)}</h2>
          <div className="mt-2"><PaperLine live={data.shadow} /></div>
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
        <ul className="mt-2 space-y-2">
          {data.runs.map((r) => (
            <li key={r.variation} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2 text-sm">
              <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${toneClass[verdictTone(r.verdict)]}`}>{r.verdict}</span>
              <span className="text-white">{r.headline}</span>
              <span className="ml-auto font-mono text-xs text-slate-500">
                #{r.variation}
                {r.p != null && r.bar != null && ` · p ${r.p.toFixed(3)} vs bar ${r.bar.toFixed(3)}`}
              </span>
            </li>
          ))}
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
