import { useMemo, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ctDateTime } from "@/lib/format";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  CURVE_RANGES,
  curveRange,
  curveTradingDays,
  fmtPct,
  fmtPts,
  tone,
  type ClosedPayload,
  type CurveRange,
  type PortfolioPayload,
} from "@/lib/paperPortfolio";
import { Box, REFRESH_MS } from "./shared";

/** Tab 2: Performance (2026-11-12 redesign). The curve against SPY with
 * its stats, and the closed trades with the tested-vs-discretionary
 * split. The deeper build (QQQ on the curve, drawdown band, daily
 * return bars, P&L by idea and sector) lands in the follow-up PR. */

export default function PerformanceTab({ data, book }: { data: PortfolioPayload; book: string }) {
  return (
    <div className="space-y-2">
      <Performance data={data} />
      <RecentTrades book={book} />
    </div>
  );
}

function Performance({ data }: { data: PortfolioPayload }) {
  const [range, setRange] = useState<CurveRange>("All");
  const s = data.scoreboard;
  const view = useMemo(() => curveRange(data.curve, range), [data.curve, range]);
  const last = view[view.length - 1];
  const stats: { label: string; value: string; className?: string }[] = [
    { label: `Portfolio, ${range}`, value: fmtPct(last?.portfolio_pct), className: tone(last?.portfolio_pct) },
    { label: `SPY, ${range}`, value: fmtPct(last?.spy_pct) },
    { label: "Ahead of SPY", value: fmtPts(last ? last.portfolio_pct - last.spy_pct : null), className: tone(last ? last.portfolio_pct - last.spy_pct : null) },
    { label: "Max drawdown", value: fmtPct(s.max_drawdown_pct) },
    // A Sharpe ratio on under a month of trading days is noise (it read -10.01
    // after 8 trading days, 2026-11-11: the guard counted curve snapshots --
    // 65 of them -- not days, so it never held).
    { label: "Sharpe", value: curveTradingDays(data.curve) < 20 ? "after 1 month" : s.sharpe == null ? "—" : s.sharpe.toFixed(2) },
    { label: "Closed-trade wins", value: s.win_rate == null ? "—" : `${s.win_rate.toFixed(0)}%` },
  ];
  return (
    <Box title="Performance vs SPY"
         right={(
           <div role="group" aria-label="Chart range" className="flex gap-1">
             {CURVE_RANGES.map((r) => (
               <button key={r} type="button" aria-pressed={r === range} onClick={() => setRange(r)}
                       className={`rounded px-2 py-0.5 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${r === range ? "bg-slate-700 font-semibold text-white" : "text-slate-400 hover:text-white"}`}>
                 {r}
               </button>
             ))}
           </div>
         )}>
      {view.length > 1 ? (
        <div className="h-32" aria-label={`Portfolio vs SPY, ${range}`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={view} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <XAxis dataKey="t" hide />
              <YAxis tickFormatter={(v: number) => `${v.toFixed(1)}%`} stroke="#64748b" fontSize={11} width={46} domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
                formatter={(v: number, name: string) => [fmtPct(v), name === "portfolio_pct" ? "Portfolio" : "SPY"]}
                labelFormatter={(t: string) => ctDateTime(t)}
              />
              <Line type="monotone" dataKey="portfolio_pct" stroke="#34d399" strokeWidth={2.5} dot={false} />
              <Line type="monotone" dataKey="spy_pct" stroke="#94a3b8" strokeWidth={2} strokeDasharray="4 3" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="text-sm text-slate-400">Not enough snapshots in this range for a curve.</p>
      )}
      <dl className="mt-2 grid grid-cols-3 gap-x-3 gap-y-1 border-t border-slate-800 pt-2">
        {stats.map((st) => (
          <div key={st.label}>
            <dt className="truncate text-[11px] text-slate-400">{st.label}</dt>
            <dd className={`mt-0.5 text-sm font-semibold tabular-nums ${st.className ?? "text-white"}`}>{st.value}</dd>
          </div>
        ))}
      </dl>
    </Box>
  );
}

/** The last few closed trades, as a box (the full record stays one click
 * away on Trades and Orders). */
function RecentTrades({ book }: { book: string | null }) {
  const { data } = useApi<ClosedPayload>(book ? `/api/portfolio/closed?book=${book}` : "/api/portfolio/closed", REFRESH_MS);
  if (!data || data.state === "not_connected" || !Array.isArray(data.trades)) return null;
  const total = data.trades.reduce((sum, t) => sum + t.pnl, 0);
  const recent = [...data.trades].slice(-3).reverse();
  const list = (items: typeof recent) => (
    <ul className="space-y-1">
      {items.map((t, i) => (
        <li key={`${t.symbol}-${t.exited_at}-${i}`} className="flex items-baseline justify-between gap-3 text-xs">
          <span className="text-slate-200">
            <span className="font-semibold text-white">{t.symbol}</span>
            {t.qty < 0 && <span className="ml-1 text-slate-400">short</span>}
            <span className="ml-2 text-slate-500">{t.exited_at.slice(0, 10)} · {t.held_days}d</span>
          </span>
          <span className={`tabular-nums ${tone(t.pnl)}`}>
            {fmtUsd(t.pnl, { signed: true })} <span className="text-slate-500">({fmtPct(t.return_pct)})</span>
          </span>
        </li>
      ))}
    </ul>
  );
  return (
    <Box title="Recent closed trades" full={data.trades.length > 3 ? list([...data.trades].slice(-30).reverse()) : undefined}
         right={<span className={`text-xs tabular-nums ${tone(total)}`}>{data.trades.length} closed · {fmtUsd(total, { signed: true })}</span>}>
      {recent.length === 0 ? (
        <p className="text-xs text-slate-400">No closed trades yet.</p>
      ) : list(recent)}
      {data.results_split && data.trades.length > 0 && (
        <p className="mt-2 border-t border-slate-800/70 pt-1.5 text-xs tabular-nums text-slate-400">
          Tested ideas <span className={tone(data.results_split.tested.pnl)}>{fmtUsd(data.results_split.tested.pnl, { signed: true })}</span>
          {" · "}Discretionary <span className={tone(data.results_split.discretionary.pnl)}>{fmtUsd(data.results_split.discretionary.pnl, { signed: true })}</span>
        </p>
      )}
    </Box>
  );
}
