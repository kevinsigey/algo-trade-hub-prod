import { Link } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";

import { useApi } from "@/hooks/usePaperPortfolio";
import { fmtPct, fmtUsd, stateLabel, tone, type ClosedPayload } from "@/lib/paperPortfolio";

const day = (iso: string) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

export default function ClosedTrades() {
  const { data, error, loading } = useApi<ClosedPayload>("/api/portfolio/closed");
  const total = data?.trades.reduce((sum, t) => sum + t.pnl, 0) ?? null;

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Portfolio
      </Link>
      <h1 className="mt-3 text-2xl font-bold tracking-tight text-white">Closed trades</h1>

      {loading && (
        <div className="mt-8 flex items-center gap-2 text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Reading the account…
        </div>
      )}
      {error && <p className="mt-8 text-rose-300">Could not read closed trades: {error}</p>}

      {data && (
        <>
          <p className="mt-1 text-xs text-slate-400">{stateLabel(data.state, data.as_of)}</p>
          {data.trades.length === 0 ? (
            <p className="mt-8 text-slate-400">No closed trades yet.</p>
          ) : (
            <>
              <div className="mt-6 text-sm text-slate-400">
                {data.trades.length} closed · total{" "}
                <span className={`font-semibold tabular-nums ${tone(total)}`}>{fmtUsd(total, { signed: true })}</span>
              </div>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[44rem] text-sm tabular-nums">
                  <thead className="text-left text-slate-400">
                    <tr>
                      <th className="py-2 pr-4 font-medium">Holding</th>
                      <th className="py-2 pr-4 text-right font-medium">Shares</th>
                      <th className="py-2 pr-4 text-right font-medium">Entry</th>
                      <th className="py-2 pr-4 text-right font-medium">Exit</th>
                      <th className="py-2 pr-4 text-right font-medium">Result</th>
                      <th className="py-2 pr-4 text-right font-medium">Held</th>
                      <th className="py-2 font-medium">Idea</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trades.map((t, i) => (
                      <tr key={`${t.symbol}-${t.exited_at}-${i}`} className="border-t border-slate-800/80">
                        <td className="py-2 pr-4 font-semibold text-white">
                          {t.symbol}
                          {t.qty < 0 && <span className="ml-1.5 text-xs font-normal text-slate-400">short</span>}
                        </td>
                        <td className="py-2 pr-4 text-right text-slate-300">{Math.abs(t.qty)}</td>
                        <td className="py-2 pr-4 text-right text-slate-300">
                          {fmtUsd(t.entry_price)} <span className="text-xs text-slate-500">{day(t.entered_at)}</span>
                        </td>
                        <td className="py-2 pr-4 text-right text-slate-300">
                          {fmtUsd(t.exit_price)} <span className="text-xs text-slate-500">{day(t.exited_at)}</span>
                        </td>
                        <td className={`py-2 pr-4 text-right ${tone(t.pnl)}`}>
                          {fmtUsd(t.pnl, { signed: true })} <span className="text-xs">{fmtPct(t.return_pct)}</span>
                        </td>
                        <td className="py-2 pr-4 text-right text-slate-300">{t.held_days}d</td>
                        <td className="py-2 text-slate-300">{t.idea}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
