import { useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, Cell, ComposedChart, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { ctDateTime } from "@/lib/format";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  aheadOfQqqPts,
  betaToSpy,
  bestWorstDay,
  CURVE_RANGES,
  curveRange,
  curveTradingDays,
  dailyReturns,
  drawdownSeries,
  etDay,
  fmtPct,
  fmtPts,
  fmtUsd,
  maxDrawdown,
  pnlByIdea,
  pnlBySector,
  realizedByWeek,
  splitOverTime,
  tone,
  tradeStats,
  tradesInRange,
  volatilityPct,
  type ClosedPayload,
  type ClosedTrade,
  type CurveRange,
  type DailyReturn,
  type PnlSlice,
  type PortfolioPayload,
} from "@/lib/paperPortfolio";
import { Box, REFRESH_MS } from "./shared";

/** Tab 2: Performance (2026-11-12 redesign, deepened in PR 2). The curve
 * against SPY with its drawdown band and stats, daily returns, where the
 * P&L came from (by idea and by sector), the tested-vs-discretionary split
 * over time, realized P&L by week, and the full sortable closed-trade list.
 * QQQ joins the curve once the snapshots carry a QQQ price (migration,
 * Kevin's go); until then every benchmark figure is SPY. */

const dayLabel = (d: string) =>
  new Date(`${d}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

const tooltipStyle = { background: "#0f172a", border: "1px solid #1e293b" };

export default function PerformanceTab({ data, book }: { data: PortfolioPayload; book: string }) {
  const [range, setRange] = useState<CurveRange>("All");
  const { data: closed } = useApi<ClosedPayload>(
    book ? `/api/portfolio/closed?book=${book}` : "/api/portfolio/closed", REFRESH_MS);
  const trades = useMemo(
    () => (closed && closed.state !== "not_connected" && Array.isArray(closed.trades) ? closed.trades : []),
    [closed]);
  const daily = useMemo(() => dailyReturns(data.curve, data.today), [data.curve, data.today]);
  const ranged = useMemo(() => tradesInRange(trades, range), [trades, range]);
  return (
    <div className="space-y-2">
      <Performance data={data} range={range} setRange={setRange} daily={daily} />
      <DailyReturns daily={daily} />
      <Attribution data={data} trades={ranged} range={range} />
      {trades.length > 0 && <SplitOverTime trades={trades} />}
      {trades.length > 0 && <RealizedByWeek trades={trades} />}
      <ClosedTrades trades={ranged} range={range} />
    </div>
  );
}

function Performance({ data, range, setRange, daily }: {
  data: PortfolioPayload;
  range: CurveRange;
  setRange: (r: CurveRange) => void;
  daily: DailyReturn[];
}) {
  const s = data.scoreboard;
  const view = useMemo(() => curveRange(data.curve, range), [data.curve, range]);
  const chart = useMemo(() => {
    const dd = drawdownSeries(view);
    return view.map((p, i) => ({ ...p, dd_pct: dd[i]?.dd_pct ?? 0 }));
  }, [view]);
  const last = view[view.length - 1];
  // QQQ's last point can be null when its live print failed; the stat
  // cards then use the last point that has one instead of disappearing
  // (Claude's #514 review).
  const lastQqq = useMemo(() => {
    for (let i = view.length - 1; i >= 0; i--) {
      if (view[i].qqq_pct != null) return view[i];
    }
    return undefined;
  }, [view]);
  const tradingDays = curveTradingDays(data.curve);
  const mdd = useMemo(() => maxDrawdown(data.curve), [data.curve]);
  const beta = betaToSpy(daily);
  const stats: { label: string; value: string; className?: string }[] = [
    { label: `Portfolio, ${range}`, value: fmtPct(last?.portfolio_pct), className: tone(last?.portfolio_pct) },
    { label: `SPY, ${range}`, value: fmtPct(last?.spy_pct) },
    { label: "Ahead of SPY", value: fmtPts(last ? last.portfolio_pct - last.spy_pct : null), className: tone(last ? last.portfolio_pct - last.spy_pct : null) },
    ...(lastQqq?.qqq_pct != null ? [
      { label: `QQQ, ${range}`, value: fmtPct(lastQqq.qqq_pct) },
      { label: "Ahead of QQQ", value: fmtPts(aheadOfQqqPts(lastQqq.portfolio_pct, lastQqq.qqq_pct)), className: tone(aheadOfQqqPts(lastQqq.portfolio_pct, lastQqq.qqq_pct)) },
    ] : []),
    { label: "Volatility (annualized)", value: fmtPct(volatilityPct(daily)) },
    {
      label: mdd.at ? `Max drawdown · ${dayLabel(mdd.at.slice(0, 10))}` : "Max drawdown",
      value: fmtPct(s.max_drawdown_pct),
    },
    // Sharpe and beta on under a month of trading days are noise (the Sharpe
    // read -10.01 after 8 trading days, 2026-11-11: the guard counted curve
    // snapshots -- 65 of them -- not days, so it never held).
    { label: "Sharpe", value: tradingDays < 20 ? "after 1 month" : s.sharpe == null ? "—" : s.sharpe.toFixed(2) },
    { label: "Beta to SPY", value: tradingDays < 20 ? "after 1 month" : beta == null ? "—" : beta.toFixed(2) },
    { label: "Closed-trade wins", value: s.win_rate == null ? "—" : `${s.win_rate.toFixed(0)}%` },
  ];
  return (
    <Box title="Performance vs SPY & QQQ"
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
        <>
          <div className="h-32" aria-label={`Portfolio vs SPY and QQQ, ${range}`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chart} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="t" hide />
                <YAxis tickFormatter={(v: number) => `${v.toFixed(1)}%`} stroke="#64748b" fontSize={11} width={46} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  formatter={(v: number, name: string) => [fmtPct(v), name === "portfolio_pct" ? "Portfolio" : name === "qqq_pct" ? "QQQ" : "SPY"]}
                  labelFormatter={(t: string) => ctDateTime(t)}
                />
                <Line type="monotone" dataKey="portfolio_pct" stroke="#34d399" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="spy_pct" stroke="#94a3b8" strokeWidth={2} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="qqq_pct" stroke="#38bdf8" strokeWidth={2} strokeDasharray="2 2" dot={false} isAnimationActive={false} connectNulls={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-1 h-14" aria-label={`Drawdown, ${range}`}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chart} margin={{ top: 2, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="t" hide />
                <YAxis tickFormatter={(v: number) => `${v.toFixed(0)}%`} stroke="#64748b" fontSize={11} width={46} domain={["auto", 0]} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  formatter={(v: number) => [fmtPct(v), "Drawdown"]}
                  labelFormatter={(t: string) => ctDateTime(t)}
                />
                <Area type="monotone" dataKey="dd_pct" stroke="#fb7185" strokeWidth={1.5} fill="#fb7185" fillOpacity={0.25} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-0.5 text-right text-[11px] text-slate-500">Drawdown under the curve, same range</p>
        </>
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
      {daily.some((d) => d.provisional) && (
        <p className="mt-2 text-[11px] text-slate-500">
          Daily stats include today as a provisional day. Its value is fixed by the 4:00 PM ET snapshot;
          after-hours moves never enter these figures.
        </p>
      )}
    </Box>
  );
}

function DailyReturns({ daily }: { daily: DailyReturn[] }) {
  const { best, worst } = bestWorstDay(daily);
  if (daily.length === 0) return null;
  const note = (d: DailyReturn | null) =>
    d ? `${dayLabel(d.date)} ${fmtPct(d.portfolio_pct)}${d.provisional ? " (today, provisional)" : ""}` : "—";
  return (
    <Box title="Daily returns"
         right={(
           <span className="text-xs tabular-nums text-slate-400">
             Best <span className={tone(best?.portfolio_pct)}>{note(best)}</span>
             {" · "}Worst <span className={tone(worst?.portfolio_pct)}>{note(worst)}</span>
           </span>
         )}>
      <div className="h-28" aria-label="Daily returns against SPY and QQQ">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={daily} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="date" tickFormatter={dayLabel} stroke="#64748b" fontSize={11} tick={{ fill: "#94a3b8" }} minTickGap={24} />
            <YAxis tickFormatter={(v: number) => `${v.toFixed(1)}%`} stroke="#64748b" fontSize={11} width={46} domain={["auto", "auto"]} />
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={(v: number, name: string) => [fmtPct(v), name === "portfolio_pct" ? "Portfolio" : name === "qqq_pct" ? "QQQ" : "SPY"]}
              labelFormatter={(d: string) => dayLabel(d)}
            />
            <Bar dataKey="portfolio_pct" isAnimationActive={false}>
              {daily.map((d) => (
                <Cell key={d.date} fill={d.portfolio_pct >= 0 ? "#34d399" : "#fb7185"} fillOpacity={d.provisional ? 0.45 : 0.9} />
              ))}
            </Bar>
            <Line type="monotone" dataKey="spy_pct" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="qqq_pct" stroke="#38bdf8" strokeWidth={1.5} strokeDasharray="2 2" dot={false} isAnimationActive={false} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </Box>
  );
}

interface WaterfallRow {
  key: string;
  base: number;
  span: number;
  total: number;
  realized: number;
  open: number;
}

/** Cumulative steps from zero to the total: each slice starts where the
 * previous one ended (the standard transparent-base waterfall). */
function waterfallRows(slices: PnlSlice[]): WaterfallRow[] {
  let run = 0;
  const rows: WaterfallRow[] = slices.map((s) => {
    const from = run;
    run += s.total;
    return { key: s.key, base: Math.min(from, run), span: Math.abs(s.total), total: s.total, realized: s.realized, open: s.open };
  });
  rows.push({
    key: "Total", base: Math.min(0, run), span: Math.abs(run), total: run,
    realized: slices.reduce((a, s) => a + s.realized, 0),
    open: slices.reduce((a, s) => a + s.open, 0),
  });
  return rows;
}

function WaterfallTooltip({ active, payload }: { active?: boolean; payload?: { payload: WaterfallRow }[] }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div style={tooltipStyle} className="px-2 py-1 text-xs text-slate-200">
      <div className="font-semibold text-white">{row.key}</div>
      <div>Realized {fmtUsd(row.realized, { signed: true })}</div>
      <div>Open {fmtUsd(row.open, { signed: true })}</div>
      <div>Total {fmtUsd(row.total, { signed: true })}</div>
    </div>
  );
}

function Waterfall({ title, slices }: { title: string; slices: PnlSlice[] }) {
  const rows = waterfallRows(slices);
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
      <div style={{ height: Math.max(72, rows.length * 24) }} aria-label={`P&L ${title.toLowerCase()}`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
            <XAxis type="number" tickFormatter={(v: number) => fmtUsd(v, { whole: true })} stroke="#64748b" fontSize={11} />
            <YAxis type="category" dataKey="key" stroke="#64748b" fontSize={11} width={118}
                   tick={{ fill: "#cbd5e1" }} tickFormatter={(k: string) => (k.length > 18 ? `${k.slice(0, 17)}…` : k)} />
            <Tooltip content={<WaterfallTooltip />} cursor={{ fill: "#1e293b", fillOpacity: 0.4 }} />
            <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
            <Bar dataKey="span" stackId="w" isAnimationActive={false}>
              {rows.map((r) => (
                <Cell key={r.key} fill={r.key === "Total" ? "#94a3b8" : r.total >= 0 ? "#34d399" : "#fb7185"} fillOpacity={0.85} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Attribution({ data, trades, range }: { data: PortfolioPayload; trades: ClosedTrade[]; range: CurveRange }) {
  const byIdea = pnlByIdea(trades, data.composition);
  const bySector = pnlBySector(trades, data.positions);
  if (byIdea.length === 0 && bySector.length === 0) return null;
  return (
    <Box title="Where the return came from"
         right={<span className="text-xs text-slate-400">Realized over {range} · open P&L is the current book</span>}>
      <div className="grid gap-4 md:grid-cols-2">
        <Waterfall title="By idea" slices={byIdea} />
        <Waterfall title="By sector" slices={bySector} />
      </div>
    </Box>
  );
}

function SplitOverTime({ trades }: { trades: ClosedTrade[] }) {
  const points = splitOverTime(trades);
  const lastPt = points[points.length - 1];
  return (
    <Box title="Tested ideas vs discretionary, cumulative realized"
         right={(
           <span className="text-xs tabular-nums text-slate-400">
             Tested <span className={tone(lastPt?.tested)}>{fmtUsd(lastPt?.tested, { signed: true })}</span>
             {" · "}Discretionary <span className={tone(lastPt?.discretionary)}>{fmtUsd(lastPt?.discretionary, { signed: true })}</span>
           </span>
         )}>
      <div className="h-28" aria-label="Cumulative realized P&L, tested ideas against discretionary trades">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="t" tickFormatter={(t: string) => dayLabel(etDay(t))} stroke="#64748b" fontSize={11} tick={{ fill: "#94a3b8" }} minTickGap={32} />
            <YAxis tickFormatter={(v: number) => fmtUsd(v, { whole: true })} stroke="#64748b" fontSize={11} width={56} domain={["auto", "auto"]} />
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={(v: number, name: string) => [fmtUsd(v, { signed: true }), name === "tested" ? "Tested ideas" : "Discretionary"]}
              labelFormatter={(t: string) => ctDateTime(t)}
            />
            <Line type="monotone" dataKey="tested" stroke="#34d399" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="discretionary" stroke="#f59e0b" strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Box>
  );
}

function RealizedByWeek({ trades }: { trades: ClosedTrade[] }) {
  const weeks = realizedByWeek(trades);
  const total = weeks.reduce((a, w) => a + w.pnl, 0);
  return (
    <Box title="Realized P&L by week"
         right={<span className={`text-xs tabular-nums ${tone(total)}`}>{fmtUsd(total, { signed: true })} realized</span>}>
      <div className="h-24" aria-label="Realized P&L by week">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={weeks} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="week" tickFormatter={dayLabel} stroke="#64748b" fontSize={11} tick={{ fill: "#94a3b8" }} minTickGap={24} />
            <YAxis tickFormatter={(v: number) => fmtUsd(v, { whole: true })} stroke="#64748b" fontSize={11} width={56} domain={["auto", "auto"]} />
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={(v: number) => [fmtUsd(v, { signed: true }), "Realized"]}
              labelFormatter={(w: string) => `Week of ${dayLabel(w)}`}
            />
            <Bar dataKey="pnl" isAnimationActive={false}>
              {weeks.map((w) => (
                <Cell key={w.week} fill={w.pnl >= 0 ? "#34d399" : "#fb7185"} fillOpacity={0.9} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Box>
  );
}

type SortKey = "exited_at" | "symbol" | "idea" | "qty" | "held_days" | "return_pct" | "pnl";

function ClosedTrades({ trades, range }: { trades: ClosedTrade[]; range: CurveRange }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "exited_at", dir: -1 });
  const rows = useMemo(() => {
    const k = sort.key;
    return [...trades].sort((a, b) => {
      const av = a[k];
      const bv = b[k];
      const cmp = typeof av === "string" ? (av < bv ? -1 : av > bv ? 1 : 0) : av - (bv as number);
      return cmp * sort.dir;
    });
  }, [trades, sort]);
  const stats = tradeStats(trades);
  const total = trades.reduce((a, t) => a + t.pnl, 0);
  const pick = (key: SortKey) =>
    setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : key === "exited_at" || key === "pnl" ? -1 : 1 }));
  const head = (label: string, key: SortKey, className = "") => (
    <th key={key} className={`px-2 py-1 font-medium ${className}`}>
      <button type="button" onClick={() => pick(key)} aria-label={`Sort closed trades by ${label}`}
              className="hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
        {label}{sort.key === key ? (sort.dir === 1 ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
  return (
    <Box title={`Closed trades · ${range}`}
         right={trades.length > 0 ? (
           <span className="text-xs tabular-nums text-slate-400">
             {stats.trades} closed · <span className={tone(total)}>{fmtUsd(total, { signed: true })}</span>
             {" · "}avg win {fmtUsd(stats.avg_win)} / avg loss {fmtUsd(stats.avg_loss)}
             {" · "}profit factor {stats.profit_factor == null ? "—" : stats.profit_factor.toFixed(2)}
             {" · "}avg hold {stats.avg_held_days == null ? "—" : `${stats.avg_held_days.toFixed(1)}d`}
           </span>
         ) : undefined}>
      {trades.length === 0 ? (
        <p className="text-sm text-slate-400">No closed trades in this range yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs tabular-nums">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400">
                {head("Exit", "exited_at")}
                {head("Symbol", "symbol")}
                {head("Idea", "idea")}
                {head("Qty", "qty", "text-right")}
                {head("Held", "held_days", "text-right")}
                {head("Return", "return_pct", "text-right")}
                {head("P&L", "pnl", "text-right")}
              </tr>
            </thead>
            <tbody>
              {rows.map((t, i) => (
                <tr key={`${t.symbol}-${t.exited_at}-${i}`} className="border-b border-slate-800/50">
                  <td className="px-2 py-1 text-slate-400">{dayLabel(t.exited_at.slice(0, 10))}</td>
                  <td className="px-2 py-1">
                    <span className="font-semibold text-white">{t.symbol}</span>
                    {t.sector && <span className="ml-1.5 text-slate-500">{t.sector}</span>}
                  </td>
                  <td className="max-w-44 truncate px-2 py-1 text-slate-300" title={t.idea}>{t.idea}</td>
                  <td className="px-2 py-1 text-right text-slate-300">
                    {t.qty}{t.qty < 0 && <span className="ml-1 text-slate-500">short</span>}
                  </td>
                  <td className="px-2 py-1 text-right text-slate-300">{t.held_days}d</td>
                  <td className={`px-2 py-1 text-right ${tone(t.return_pct)}`}>{fmtPct(t.return_pct)}</td>
                  <td className={`px-2 py-1 text-right ${tone(t.pnl)}`}>{fmtUsd(t.pnl, { signed: true })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Box>
  );
}
