import { useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, Cell, ComposedChart, Line, LineChart, ReferenceDot,
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
import {
  DashCard, dayLabel, Fig, FilterBox, MiniBars, PEEK, PeekRows, REFRESH_MS, Segments, Spark, tooltipStyle,
} from "./shared";

/** Tab 2: Performance as a dashboard (Kevin, 2026-11-13): a grid of cards,
 * each one number and a small chart, every card opening to the full chart
 * and table. The range selector drives the curve, the attribution and the
 * closed trades. QQQ joins wherever the snapshots carry a QQQ price. */

const signedUsd = (v: number | null | undefined) => fmtUsd(v, { signed: true, whole: true });
const seriesName = (name: string) => (name === "portfolio_pct" ? "Portfolio" : name === "qqq_pct" ? "QQQ" : "SPY");

export default function PerformanceTab({ data, book }: { data: PortfolioPayload; book: string }) {
  const [range, setRange] = useState<CurveRange>("All");
  const { data: closed } = useApi<ClosedPayload>(
    book ? `/api/portfolio/closed?book=${book}` : "/api/portfolio/closed", REFRESH_MS);
  const trades = useMemo(
    () => (closed && closed.state !== "not_connected" && Array.isArray(closed.trades) ? closed.trades : []),
    [closed]);
  const daily = useMemo(() => dailyReturns(data.curve, data.today), [data.curve, data.today]);
  const ranged = useMemo(() => tradesInRange(trades, range), [trades, range]);
  const rangeControl = <Segments<CurveRange> label="Chart range" options={CURVE_RANGES} value={range} onChange={setRange} />;
  return (
    <div>
      <div className="mb-2 flex justify-end">{rangeControl}</div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        <CurveCard data={data} range={range} rangeControl={rangeControl} />
        <RiskCard data={data} daily={daily} />
        <DailyCard daily={daily} />
        <AttributionCard data={data} trades={ranged} range={range} />
        <SplitCard trades={trades} />
        <WeeksCard trades={trades} />
        <ClosedCard trades={ranged} range={range} />
      </div>
    </div>
  );
}

function CurveCard({ data, range, rangeControl }: { data: PortfolioPayload; range: CurveRange; rangeControl: JSX.Element }) {
  const view = useMemo(() => curveRange(data.curve, range), [data.curve, range]);
  const chart = useMemo(() => {
    const dd = drawdownSeries(view);
    return view.map((p, i) => ({ ...p, dd_pct: dd[i]?.dd_pct ?? 0 }));
  }, [view]);
  const last = view[view.length - 1];
  // QQQ's last point can be null when its live print failed; use the last
  // point that has one (Claude's #514 review).
  const lastQqq = useMemo(() => {
    for (let i = view.length - 1; i >= 0; i--) if (view[i].qqq_pct != null) return view[i];
    return undefined;
  }, [view]);
  const vsSpy = last ? last.portfolio_pct - last.spy_pct : null;
  const vsQqq = lastQqq?.qqq_pct != null ? aheadOfQqqPts(lastQqq.portfolio_pct, lastQqq.qqq_pct) : null;
  const detail = view.length > 1 ? (
    <div>
      <dl className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Fig label={`Portfolio, ${range}`} value={fmtPct(last?.portfolio_pct)} className={tone(last?.portfolio_pct)} />
        <Fig label={`SPY, ${range}`} value={fmtPct(last?.spy_pct)} />
        <Fig label="vs SPY" value={fmtPts(vsSpy)} className={tone(vsSpy)} />
        <Fig label={`QQQ, ${range}`} value={fmtPct(lastQqq?.qqq_pct)} />
        <Fig label="vs QQQ" value={fmtPts(vsQqq)} className={tone(vsQqq)} />
      </dl>
      <div className="h-[46vh] min-h-64" aria-label={`Portfolio vs SPY and QQQ, ${range}`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chart} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="t" tickFormatter={(t: string) => dayLabel(etDay(t))} stroke="#64748b" fontSize={11} minTickGap={40} />
            <YAxis tickFormatter={(v: number) => `${v.toFixed(1)}%`} stroke="#64748b" fontSize={11} width={46} domain={["auto", "auto"]} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v: number, name: string) => [fmtPct(v), seriesName(name)]}
                     labelFormatter={(t: string) => ctDateTime(t)} />
            <Line type="monotone" dataKey="portfolio_pct" stroke="#34d399" strokeWidth={2.5} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="spy_pct" stroke="#94a3b8" strokeWidth={2} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="qqq_pct" stroke="#38bdf8" strokeWidth={2} strokeDasharray="2 2" dot={false} isAnimationActive={false} connectNulls={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 h-24" aria-label={`Drawdown, ${range}`}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chart} margin={{ top: 2, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="t" hide />
            <YAxis tickFormatter={(v: number) => `${v.toFixed(0)}%`} stroke="#64748b" fontSize={11} width={46} domain={["auto", 0]} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => [fmtPct(v), "Drawdown"]} labelFormatter={(t: string) => ctDateTime(t)} />
            <Area type="monotone" dataKey="dd_pct" stroke="#fb7185" strokeWidth={1.5} fill="#fb7185" fillOpacity={0.25} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <Legend items={[["#34d399", "Portfolio"], ["#94a3b8", "SPY"], ["#38bdf8", "QQQ"], ["#fb7185", "Drawdown"]]} />
    </div>
  ) : <p className="text-sm text-slate-400">Not enough snapshots in this range.</p>;
  return (
    <DashCard title={`Return, ${range}`} className="md:col-span-2"
              value={fmtPct(last?.portfolio_pct)} valueClass={tone(last?.portfolio_pct)}
              sub={<>SPY {fmtPct(last?.spy_pct)} · vs SPY <span className={tone(vsSpy)}>{fmtPts(vsSpy)}</span>
                {vsQqq != null && <> · QQQ {fmtPct(lastQqq?.qqq_pct)} · vs QQQ <span className={tone(vsQqq)}>{fmtPts(vsQqq)}</span></>}</>}
              detail={detail} detailTitle="Performance vs SPY & QQQ" detailActions={rangeControl}>
      <Spark data={chart} height={96} lines={[
        { key: "portfolio_pct", color: "#34d399", width: 2 },
        { key: "spy_pct", color: "#94a3b8", dashed: true },
        { key: "qqq_pct", color: "#38bdf8", dashed: true },
      ]} />
      <Spark data={chart} height={22} lines={[{ key: "dd_pct", color: "#fb7185" }]} />
    </DashCard>
  );
}

function Legend({ items }: { items: [string, string][] }) {
  return (
    <div className="mt-1 flex flex-wrap gap-4 text-[11px] text-slate-400">
      {items.map(([c, l]) => <span key={l} className="inline-flex items-center gap-1"><span className="h-0.5 w-3" style={{ background: c }} />{l}</span>)}
    </div>
  );
}

function RiskCard({ data, daily }: { data: PortfolioPayload; daily: DailyReturn[] }) {
  const s = data.scoreboard;
  const tradingDays = curveTradingDays(data.curve);
  const mdd = useMemo(() => maxDrawdown(data.curve), [data.curve]);
  const beta = betaToSpy(daily);
  const vol = volatilityPct(daily);
  const { best, worst } = bestWorstDay(daily);
  // Sharpe and beta on under a month of trading days are noise (the Sharpe
  // read -10.01 after 8 trading days, 2026-11-11).
  const young = tradingDays < 20;
  const stats: { label: string; value: string; className?: string; def: string }[] = [
    { label: "Volatility", value: fmtPct(vol), def: "Standard deviation of daily returns, annualized (×√252)." },
    { label: "Max drawdown", value: fmtPct(s.max_drawdown_pct),
      def: `Deepest fall from a running high, all time${mdd.at ? `; lowest on ${dayLabel(mdd.at.slice(0, 10))}` : ""}.` },
    { label: "Sharpe", value: young ? "after 1 mo" : s.sharpe == null ? "—" : s.sharpe.toFixed(2),
      def: "Mean daily return over its standard deviation, annualized. Shown from 20 trading days." },
    { label: "Beta to SPY", value: young ? "after 1 mo" : beta == null ? "—" : beta.toFixed(2),
      def: "How far the book moves per 1% SPY move, from daily returns. Shown from 20 trading days." },
    { label: "Closed-trade wins", value: s.win_rate == null ? "—" : `${s.win_rate.toFixed(0)}%`,
      def: "Share of closed trades that made money." },
    { label: "Best day", value: best ? fmtPct(best.portfolio_pct) : "—", className: tone(best?.portfolio_pct),
      def: best ? `${dayLabel(best.date)}, close to close.` : "No full day yet." },
    { label: "Worst day", value: worst ? fmtPct(worst.portfolio_pct) : "—", className: tone(worst?.portfolio_pct),
      def: worst ? `${dayLabel(worst.date)}, close to close.` : "No full day yet." },
    { label: "Trading days", value: String(tradingDays), def: "Days with a 4:00 PM ET snapshot on the curve." },
  ];
  const shown = stats.slice(0, 6);
  return (
    <DashCard title="Risk" hint="Volatility, drawdown, Sharpe, beta"
              detail={(
                <div>
                  <dl className="divide-y divide-slate-800">
                    {stats.map((st) => (
                      <div key={st.label} className="grid grid-cols-[9rem_7rem_1fr] items-baseline gap-3 py-2 text-sm">
                        <dt className="text-slate-300">{st.label}</dt>
                        <dd className={`font-semibold tabular-nums ${st.className ?? "text-white"}`}>{st.value}</dd>
                        <dd className="text-xs text-slate-400">{st.def}</dd>
                      </div>
                    ))}
                  </dl>
                  {daily.some((d) => d.provisional) && (
                    <p className="mt-3 text-xs text-slate-500">Today counts as provisional until the 4:00 PM ET snapshot; after-hours moves never enter these figures.</p>
                  )}
                </div>
              )} detailTitle="Risk and return stats">
      <dl className="grid grid-cols-3 gap-x-3 gap-y-2">
        {shown.map((st) => <Fig key={st.label} label={st.label} value={st.value} className={st.className} />)}
      </dl>
    </DashCard>
  );
}

function DailyCard({ daily }: { daily: DailyReturn[] }) {
  const { best, worst } = bestWorstDay(daily);
  const last = daily[daily.length - 1];
  const note = (d: DailyReturn | null) => (d ? `${dayLabel(d.date)} ${fmtPct(d.portfolio_pct)}` : "—");
  return (
    <DashCard title="Daily returns" value={fmtPct(last?.portfolio_pct)} valueClass={tone(last?.portfolio_pct)}
              sub={<>Best <span className={tone(best?.portfolio_pct)}>{note(best)}</span> · Worst <span className={tone(worst?.portfolio_pct)}>{note(worst)}</span></>}
              detail={<DailyDetail daily={daily} />}>
      <MiniBars data={daily} valueKey="portfolio_pct" height={56} dim={(d) => Boolean(d.provisional)} />
    </DashCard>
  );
}

function DailyDetail({ daily }: { daily: DailyReturn[] }) {
  const { best, worst } = bestWorstDay(daily);
  if (daily.length === 0) return <p className="text-sm text-slate-400">No full trading day yet.</p>;
  return (
    <div>
      <div className="h-[40vh] min-h-56" aria-label="Daily returns against SPY and QQQ">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={daily} margin={{ top: 16, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="date" tickFormatter={dayLabel} stroke="#64748b" fontSize={11} minTickGap={24} />
            <YAxis tickFormatter={(v: number) => `${v.toFixed(1)}%`} stroke="#64748b" fontSize={11} width={46} domain={["auto", "auto"]} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v: number, name: string) => [fmtPct(v), seriesName(name)]} labelFormatter={(d: string) => dayLabel(d)} />
            <Bar dataKey="portfolio_pct" isAnimationActive={false}>
              {daily.map((d) => <Cell key={d.date} fill={d.portfolio_pct >= 0 ? "#34d399" : "#fb7185"} fillOpacity={d.provisional ? 0.45 : 0.9} />)}
            </Bar>
            <Line type="linear" dataKey="spy_pct" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            <Line type="linear" dataKey="qqq_pct" stroke="#38bdf8" strokeWidth={1.5} strokeDasharray="2 2" dot={false} isAnimationActive={false} connectNulls={false} />
            {best && <ReferenceDot x={best.date} y={best.portfolio_pct} r={4} fill="#34d399" stroke="#fff"
                                   label={{ value: `Best ${fmtPct(best.portfolio_pct)}`, position: "top", fill: "#a7f3d0", fontSize: 11 }} />}
            {worst && worst !== best && <ReferenceDot x={worst.date} y={worst.portfolio_pct} r={4} fill="#fb7185" stroke="#fff"
                                   label={{ value: `Worst ${fmtPct(worst.portfolio_pct)}`, position: "bottom", fill: "#fecdd3", fontSize: 11 }} />}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <Legend items={[["#34d399", "Portfolio"], ["#94a3b8", "SPY"], ["#38bdf8", "QQQ"]]} />
      <table className="mt-3 w-full text-left text-xs tabular-nums">
        <thead className="text-slate-400"><tr>
          <th className="py-1 pr-3 font-medium">Day</th><th className="py-1 pr-3 text-right font-medium">Portfolio</th>
          <th className="py-1 pr-3 text-right font-medium">SPY</th><th className="py-1 text-right font-medium">QQQ</th>
        </tr></thead>
        <tbody>
          {[...daily].reverse().map((d) => (
            <tr key={d.date} className="border-t border-slate-800/70">
              <td className="py-1 pr-3 text-slate-300">{dayLabel(d.date)}{d.provisional ? " (provisional)" : ""}</td>
              <td className={`py-1 pr-3 text-right ${tone(d.portfolio_pct)}`}>{fmtPct(d.portfolio_pct)}</td>
              <td className="py-1 pr-3 text-right text-slate-300">{fmtPct(d.spy_pct)}</td>
              <td className="py-1 text-right text-slate-300">{fmtPct(d.qqq_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface WaterfallRow { key: string; base: number; span: number; total: number; realized: number; open: number }

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
      <h3 className="mb-1 text-xs font-semibold text-slate-300">{title}</h3>
      <div style={{ height: Math.max(72, rows.length * 26) }} aria-label={`P&L ${title.toLowerCase()}`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
            <XAxis type="number" tickFormatter={(v: number) => fmtUsd(v, { whole: true })} stroke="#64748b" fontSize={11} />
            <YAxis type="category" dataKey="key" stroke="#64748b" fontSize={11} width={130}
                   tick={{ fill: "#cbd5e1" }} tickFormatter={(k: string) => (k.length > 20 ? `${k.slice(0, 19)}…` : k)} />
            <Tooltip content={<WaterfallTooltip />} cursor={{ fill: "#1e293b", fillOpacity: 0.4 }} />
            <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
            <Bar dataKey="span" stackId="w" isAnimationActive={false}>
              {rows.map((r) => <Cell key={r.key} fill={r.key === "Total" ? "#94a3b8" : r.total >= 0 ? "#34d399" : "#fb7185"} fillOpacity={0.85} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table className="mt-2 w-full text-left text-xs tabular-nums">
        <thead className="text-slate-400"><tr>
          <th className="py-1 pr-3 font-medium">{title.replace("By ", "").replace(/^./, (c) => c.toUpperCase())}</th>
          <th className="py-1 pr-3 text-right font-medium">Realized</th><th className="py-1 pr-3 text-right font-medium">Open</th>
          <th className="py-1 text-right font-medium">Total</th>
        </tr></thead>
        <tbody>
          {slices.map((s) => (
            <tr key={s.key} className="border-t border-slate-800/70">
              <td className="max-w-[14rem] truncate py-1 pr-3 text-slate-200" title={s.key}>{s.key}</td>
              <td className={`py-1 pr-3 text-right ${tone(s.realized)}`}>{signedUsd(s.realized)}</td>
              <td className={`py-1 pr-3 text-right ${tone(s.open)}`}>{signedUsd(s.open)}</td>
              <td className={`py-1 text-right font-medium ${tone(s.total)}`}>{signedUsd(s.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AttributionCard({ data, trades, range }: { data: PortfolioPayload; trades: ClosedTrade[]; range: CurveRange }) {
  const byIdea = pnlByIdea(trades, data.composition);
  const bySector = pnlBySector(trades, data.positions);
  const total = byIdea.length ? byIdea.reduce((a, s) => a + s.total, 0) : null;
  return (
    <DashCard title="Where the return came from" value={signedUsd(total)} valueClass={tone(total)}
              sub={`Realized ${range} + open`} hint="Realized P&L over the range plus the current book's open P&L"
              detail={byIdea.length || bySector.length ? (
                <div>
                  <p className="mb-3 text-xs text-slate-400">Realized over {range}; open P&L is the current book.</p>
                  <div className="grid gap-6 md:grid-cols-2">
                    <Waterfall title="By idea" slices={byIdea} />
                    <Waterfall title="By sector" slices={bySector} />
                  </div>
                </div>
              ) : <p className="text-sm text-slate-400">Nothing realized or open yet.</p>}>
      <PeekRows empty="No P&L yet" rows={byIdea.slice(0, 4).map((s) => ({
        key: s.key, label: s.key, value: signedUsd(s.total), valueClass: tone(s.total),
      }))} />
    </DashCard>
  );
}

function SplitCard({ trades }: { trades: ClosedTrade[] }) {
  const points = useMemo(() => splitOverTime(trades), [trades]);
  const last = points[points.length - 1];
  return (
    <DashCard title="Tested vs discretionary" value={signedUsd(last?.tested)} valueClass={tone(last?.tested)}
              sub={<>Discretionary <span className={tone(last?.discretionary)}>{signedUsd(last?.discretionary)}</span></>}
              hint="Cumulative realized P&L: trades from tested ideas against discretionary trades"
              detail={points.length ? (
                <div>
                  <div className="h-[46vh] min-h-56" aria-label="Cumulative realized P&L, tested ideas against discretionary trades">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                        <XAxis dataKey="t" tickFormatter={(t: string) => dayLabel(etDay(t))} stroke="#64748b" fontSize={11} minTickGap={32} />
                        <YAxis tickFormatter={(v: number) => fmtUsd(v, { whole: true })} stroke="#64748b" fontSize={11} width={60} domain={["auto", "auto"]} />
                        <Tooltip contentStyle={tooltipStyle} formatter={(v: number, name: string) => [fmtUsd(v, { signed: true }), name === "tested" ? "Tested ideas" : "Discretionary"]}
                                 labelFormatter={(t: string) => ctDateTime(t)} />
                        <Line type="monotone" dataKey="tested" stroke="#34d399" strokeWidth={2} dot={false} isAnimationActive={false} />
                        <Line type="monotone" dataKey="discretionary" stroke="#f59e0b" strokeWidth={2} dot={false} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  <Legend items={[["#34d399", `Tested ideas ${signedUsd(last?.tested)}`], ["#f59e0b", `Discretionary ${signedUsd(last?.discretionary)}`]]} />
                </div>
              ) : <p className="text-sm text-slate-400">No closed trades yet.</p>}
              detailTitle="Tested ideas vs discretionary, cumulative realized">
      <Spark data={points} height={56} lines={[{ key: "tested", color: "#34d399", width: 2 }, { key: "discretionary", color: "#f59e0b" }]} />
    </DashCard>
  );
}

function WeeksCard({ trades }: { trades: ClosedTrade[] }) {
  const weeks = useMemo(() => realizedByWeek(trades), [trades]);
  const total = weeks.length ? weeks.reduce((a, w) => a + w.pnl, 0) : null;
  const best = weeks.reduce<(typeof weeks)[number] | null>((b, w) => (!b || w.pnl > b.pnl ? w : b), null);
  return (
    <DashCard title="Realized by week" value={signedUsd(total)} valueClass={tone(total)}
              sub={weeks.length ? `${weeks.length} weeks · best ${dayLabel(best!.week)} ${signedUsd(best!.pnl)}` : "No closed trades"}
              detail={weeks.length ? (
                <div>
                  <div className="h-[36vh] min-h-48" aria-label="Realized P&L by week">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={weeks} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                        <XAxis dataKey="week" tickFormatter={dayLabel} stroke="#64748b" fontSize={11} minTickGap={24} />
                        <YAxis tickFormatter={(v: number) => fmtUsd(v, { whole: true })} stroke="#64748b" fontSize={11} width={60} domain={["auto", "auto"]} />
                        <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => [fmtUsd(v, { signed: true }), "Realized"]} labelFormatter={(w: string) => `Week of ${dayLabel(w)}`} />
                        <Bar dataKey="pnl" isAnimationActive={false}>
                          {weeks.map((w) => <Cell key={w.week} fill={w.pnl >= 0 ? "#34d399" : "#fb7185"} fillOpacity={0.9} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <table className="mt-3 w-full text-left text-xs tabular-nums">
                    <thead className="text-slate-400"><tr>
                      <th className="py-1 pr-3 font-medium">Week of</th><th className="py-1 pr-3 text-right font-medium">Trades</th>
                      <th className="py-1 text-right font-medium">Realized</th>
                    </tr></thead>
                    <tbody>
                      {[...weeks].reverse().map((w) => (
                        <tr key={w.week} className="border-t border-slate-800/70">
                          <td className="py-1 pr-3 text-slate-300">{dayLabel(w.week)}</td>
                          <td className="py-1 pr-3 text-right text-slate-300">{w.trades}</td>
                          <td className={`py-1 text-right ${tone(w.pnl)}`}>{fmtUsd(w.pnl, { signed: true })}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="text-sm text-slate-400">No closed trades yet.</p>}
              detailTitle="Realized P&L by week">
      <MiniBars data={weeks} valueKey="pnl" height={56} />
    </DashCard>
  );
}

function ClosedCard({ trades, range }: { trades: ClosedTrade[]; range: CurveRange }) {
  const stats = tradeStats(trades);
  const total = trades.length ? trades.reduce((a, t) => a + t.pnl, 0) : null;
  const newest = useMemo(() => [...trades].sort((a, b) => (a.exited_at < b.exited_at ? 1 : -1)), [trades]);
  return (
    <DashCard title={`Closed trades, ${range}`} value={trades.length}
              meta={<span className={tone(total)}>{signedUsd(total)}</span>}
              sub={`Wins ${stats.win_rate == null ? "—" : `${stats.win_rate.toFixed(0)}%`} · PF ${stats.profit_factor == null ? "—" : stats.profit_factor.toFixed(2)}`}
              detail={<ClosedTable trades={trades} />} detailTitle={`Closed trades · ${range}`}>
      <PeekRows empty="No closed trades in this range" rows={newest.slice(0, PEEK).map((t, i) => ({
        key: `${t.symbol}-${t.exited_at}-${i}`, label: t.symbol, aside: dayLabel(t.exited_at.slice(0, 10)),
        value: signedUsd(t.pnl), valueClass: tone(t.pnl),
      }))} />
    </DashCard>
  );
}

type SortKey = "exited_at" | "symbol" | "idea" | "qty" | "held_days" | "return_pct" | "pnl";

/** The full closed-trade list, in the open view: stats, a filter and every column sortable. */
function ClosedTable({ trades }: { trades: ClosedTrade[] }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "exited_at", dir: -1 });
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const k = sort.key;
    const needle = q.trim().toLowerCase();
    return trades
      .filter((t) => !needle || `${t.symbol} ${t.idea} ${t.sector ?? ""}`.toLowerCase().includes(needle))
      .sort((a, b) => {
        const av = a[k];
        const bv = b[k];
        const cmp = typeof av === "string" ? (av < bv ? -1 : av > bv ? 1 : 0) : av - (bv as number);
        return cmp * sort.dir;
      });
  }, [trades, sort, q]);
  const stats = tradeStats(trades);
  const total = trades.reduce((a, t) => a + t.pnl, 0);
  const pick = (key: SortKey) =>
    setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : key === "exited_at" || key === "pnl" ? -1 : 1 }));
  const head = (label: string, key: SortKey, className = "") => (
    <th key={key} className={`px-2 py-1 font-medium ${className}`} aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={() => pick(key)} aria-label={`Sort closed trades by ${label}`}
              className="hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
        {label}{sort.key === key ? (sort.dir === 1 ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
  if (trades.length === 0) return <p className="text-sm text-slate-400">No closed trades in this range yet.</p>;
  return (
    <div>
      <dl className="mb-3 grid grid-cols-3 gap-3 sm:grid-cols-6">
        <Fig label="Closed" value={stats.trades} />
        <Fig label="Net P&L" value={fmtUsd(total, { signed: true })} className={tone(total)} />
        <Fig label="Avg win" value={fmtUsd(stats.avg_win)} />
        <Fig label="Avg loss" value={fmtUsd(stats.avg_loss)} />
        <Fig label="Profit factor" value={stats.profit_factor == null ? "—" : stats.profit_factor.toFixed(2)} hint="Gross wins over gross losses" />
        <Fig label="Avg hold" value={stats.avg_held_days == null ? "—" : `${stats.avg_held_days.toFixed(1)}d`} />
      </dl>
      <div className="mb-2"><FilterBox value={q} onChange={setQ} label="Filter closed trades" /></div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-left text-xs tabular-nums">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400">
              {head("Exit", "exited_at")}{head("Symbol", "symbol")}{head("Idea", "idea")}
              {head("Qty", "qty", "text-right")}{head("Held", "held_days", "text-right")}
              {head("Return", "return_pct", "text-right")}{head("P&L", "pnl", "text-right")}
            </tr>
          </thead>
          <tbody>
            {rows.map((t, i) => (
              <tr key={`${t.symbol}-${t.exited_at}-${i}`} className="border-b border-slate-800/50">
                <td className="px-2 py-1 text-slate-400">{dayLabel(t.exited_at.slice(0, 10))}</td>
                <td className="px-2 py-1"><span className="font-semibold text-white">{t.symbol}</span>{t.sector && <span className="ml-1.5 text-slate-500">{t.sector}</span>}</td>
                <td className="max-w-44 truncate px-2 py-1 text-slate-300" title={t.idea}>{t.idea}</td>
                <td className="px-2 py-1 text-right text-slate-300">{t.qty}{t.qty < 0 && <span className="ml-1 text-slate-500">short</span>}</td>
                <td className="px-2 py-1 text-right text-slate-300">{t.held_days}d</td>
                <td className={`px-2 py-1 text-right ${tone(t.return_pct)}`}>{fmtPct(t.return_pct)}</td>
                <td className={`px-2 py-1 text-right ${tone(t.pnl)}`}>{fmtUsd(t.pnl, { signed: true })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
