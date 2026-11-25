import { useEffect, useMemo, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { useApi } from "@/hooks/usePaperPortfolio";
import {
  aheadOfQqqPts, bestWorstDay, contractLabel, curveRange, curveSince, curveTradingDays, dailyReturns, drawdownSeries,
  fmtPct, fmtPts, fmtUsd, tone, volatilityPct,
  type ClosedPayload, type PortfolioPayload,
} from "@/lib/paperPortfolio";
import { bookRows, ByIdeaCard, CompositionCard, MoversCard, PositionsTable } from "./BookTab";
import PerformanceTab, { Legend } from "./PerformanceTab";
import TradeTab, { ManualActions } from "./TradeTab";
import { adminCall, DashCard, Fig, money, PEEK, PeekRows, pollWhileVisible, REFRESH_MS, Segments, signed, Spark, tooltipStyle } from "./shared";
import { legendSlices, slices, type Slice } from "./slices";

/** The main area (Kevin, 2026-11-25): Performance beside a Positions and By idea
 * stack, Trade along the bottom. Each card is the live summary; its open view holds
 * everything the old Book / Performance / Trade tabs held. */

export type OpenCard = "performance" | "positions" | "trade" | undefined;

export default function PaperMain({ data, book, liveIdeas, open }: {
  data: PortfolioPayload;
  book: string;
  liveIdeas: { id: number; title: string; size_pct: number | null }[];
  open: OpenCard;
}) {
  return (
    <div className="flex flex-1 flex-col gap-2">
      <div className="grid flex-1 gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <PerformanceCard data={data} book={book} open={open === "performance"} />
        <div className="flex min-w-0 flex-col gap-2">
          <PositionsCard data={data} open={open === "positions"} />
          <ByIdeaCard rows={bookRows(data).rows} equity={data.scoreboard.equity} liveIdeas={liveIdeas} book={book} />
        </div>
      </div>
      <div className="flex flex-wrap items-start gap-2">
        <TradeCard book={book} open={open === "trade"} />
        <ManualActions book={book} />
      </div>
    </div>
  );
}

const RANGES = ["Today", "Since start"] as const;
const CT_TIME = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hour: "2-digit", minute: "2-digit", hour12: false });

function PerformanceCard({ data, book, open }: { data: PortfolioPayload; book: string; open: boolean }) {
  const s = data.scoreboard;
  const [range, setRange] = useState<(typeof RANGES)[number]>("Since start");
  const { data: closed } = useApi<ClosedPayload>(`/api/portfolio/closed?book=${book}`, REFRESH_MS);
  // The full-view charts always read the whole curve; the card's chart follows the toggle.
  const full = useMemo(() => {
    const view = curveRange(data.curve, "All");
    const dd = drawdownSeries(view);
    return view.map((p, i) => ({ ...p, dd_pct: dd[i]?.dd_pct ?? 0 }));
  }, [data.curve]);
  const intraday = useMemo(() => curveSince(data.curve, data.today?.prior_close_at), [data.curve, data.today?.prior_close_at]);
  const chart = range === "Today" ? intraday : full;
  const daily = useMemo(() => dailyReturns(data.curve, data.today), [data.curve, data.today]);
  const last = chart[chart.length - 1];
  const lastQqq = [...chart].reverse().find((p) => p.qqq_pct != null);
  const vsSpy = last ? last.portfolio_pct - last.spy_pct : null;
  const vsQqq = lastQqq?.qqq_pct != null ? aheadOfQqqPts(lastQqq.portfolio_pct, lastQqq.qqq_pct) : null;
  const young = curveTradingDays(data.curve) < 20;
  const { best, worst } = bestWorstDay(daily);
  const trades = Array.isArray(closed?.trades) ? closed.trades : [];
  const realized = trades.length ? trades.reduce((a, t) => a + t.pnl, 0) : null;
  // Today's headline is the day's own figure for the state it is in; else the move since the prior close.
  const t = data.today;
  const todayHead = t?.state === "premarket" ? t.premarket_pct ?? last?.portfolio_pct
    : t?.state === "regular" || t?.state === "closed_day" ? t.regular_pct ?? last?.portfolio_pct : last?.portfolio_pct;
  const head = range === "Today" ? (intraday.length < 2 ? null : todayHead) : last?.portfolio_pct;
  const marketLive = !!t && (t.state === "regular" || t.state === "premarket" || t.state === "after_hours") && t.is_today !== false;
  const lastAt = full[full.length - 1]?.t;
  const liveLabel = lastAt && (marketLive ? `live · as of ${CT_TIME.format(new Date(lastAt))} CT` : "as of close");
  return (
    <DashCard title="Performance"
              value={<>{fmtPct(head)}{liveLabel && (
                <span className="ml-2 inline-flex items-center gap-1.5 align-middle font-sans text-xs font-normal tracking-normal text-slate-400">
                  <span className={`h-2 w-2 rounded-full ${marketLive ? "bg-emerald-400" : "bg-slate-500"}`} aria-hidden="true" />{liveLabel}
                </span>)}</>}
              valueClass={tone(head)}
              sub={<>SPY {fmtPct(last?.spy_pct)}{lastQqq?.qqq_pct != null && <span title={vsQqq == null ? undefined : `${fmtPts(vsQqq)} vs QQQ`}> · QQQ {fmtPct(lastQqq.qqq_pct)}</span>}
                {" · "}<span className={tone(vsSpy)} title="Gap: book minus SPY, in percentage points">{fmtPts(vsSpy)} vs SPY</span></>}
              meta={<span className="relative z-10"><Segments<(typeof RANGES)[number]> label="Performance range" options={RANGES} value={range} onChange={setRange} /></span>}
              hint="Return curve vs SPY and QQQ. Open for risk, daily returns, attribution, tested vs discretionary, realized by week and closed trades."
              defaultOpen={open} detailTitle="Performance" detail={<PerformanceTab data={data} book={book} />}>
      <div className="relative min-h-[100px] flex-1 md:min-h-[150px]">
        <div className="absolute inset-0">
          {range === "Today" && intraday.length < 2 ? (
            <div className="flex h-full flex-col items-center justify-center text-slate-500">
              <span className="text-2xl">—</span>
              <span className="text-xs">live tracking starts after the open</span>
            </div>
          ) : (
            <Spark data={chart} height="100%" grid live={{ key: "portfolio_pct", pulse: marketLive }} lines={[
              { key: "portfolio_pct", color: "#34d399", width: 2 },
              { key: "spy_pct", color: "#94a3b8", dashed: true },
              { key: "qqq_pct", color: "#38bdf8", dashed: true },
            ]} />
          )}
        </div>
      </div>
      <div className="hidden md:block"><Legend items={[["#34d399", "Book"], ["#94a3b8", "SPY"], ["#38bdf8", "QQQ"]]} /></div>
      <dl className="mt-2 grid grid-cols-3 gap-x-3 gap-y-2 md:grid-cols-6">
        <Fig label="Max drawdown" value={fmtPct(s.max_drawdown_pct)} hint="Deepest fall from a running high, all time." />
        <Fig label="Volatility" value={fmtPct(volatilityPct(daily))} hint="Standard deviation of daily returns, annualized." />
        <Fig label="Sharpe" value={young || s.sharpe == null ? "—" : s.sharpe.toFixed(2)} hint={young ? "Not enough history yet: shown after 1 month (20 trading days)." : "Return per unit of risk, annualized."} />
        <Fig label="Best day" value={best ? fmtPct(best.portfolio_pct) : "—"} className={tone(best?.portfolio_pct)} hint="Best close-to-close day." />
        <Fig label="Worst day" value={worst ? fmtPct(worst.portfolio_pct) : "—"} className={tone(worst?.portfolio_pct)} hint="Worst close-to-close day." />
        <Fig label="Realized" value={signed(realized)} className={tone(realized)} hint="Profit or loss locked in by closed trades." />
      </dl>
    </DashCard>
  );
}

/** Hover readout for a donut slice: its label, share and dollars. */
function SliceTip({ active, payload }: { active?: boolean; payload?: { payload: Slice }[] }) {
  const s = active ? payload?.[0]?.payload : undefined;
  if (!s) return null;
  return (
    <div style={tooltipStyle} className="rounded px-2 py-1 text-xs tabular-nums text-slate-200">
      <div className="font-semibold text-white">{s.label}{s.tag ? ` (${s.tag})` : ""}</div>
      {s.pct.toFixed(1)}% · {money(s.value)}
    </div>
  );
}

/** The book by thesis as a donut with its biggest slices beside it. */
function ThesisDonut({ all }: { all: Slice[] }) {
  const legend = legendSlices(all);
  const corePct = all.filter((s) => s.key.startsWith("core-")).reduce((a, s) => a + s.pct, 0);
  if (all.length === 0) return null;
  return (
    <div className="flex items-center gap-3">
      {/* z-10: the card's open control covers its body, and the hover needs the pointer. */}
      <div className="relative z-10 h-24 w-24 shrink-0" role="img"
           aria-label={`By thesis: ${legend.map((s) => `${s.label} ${s.pct.toFixed(0)}%`).join(", ")}`}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={all} dataKey="value" nameKey="label" innerRadius="60%" outerRadius="100%" stroke="#0f172a"
                 strokeWidth={1} isAnimationActive={false}>
              {all.map((s) => <Cell key={s.key} fill={s.color} />)}
            </Pie>
            <Tooltip content={<SliceTip />} wrapperStyle={{ zIndex: 30 }} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="min-w-0 flex-1">
      {corePct > 0 && (
        <p className="mb-0.5 text-[11px] text-slate-400">Core thesis <span className="font-semibold text-slate-200">{corePct.toFixed(0)}%</span> · split by sector and holding</p>
      )}
      <ul className="grid min-w-0 grid-cols-2 gap-x-3 gap-y-0.5 text-xs tabular-nums text-slate-300" aria-label="Thesis slices">
        {legend.map((s) => (
          <li key={s.key} className="flex items-baseline gap-1.5">
            <span className="h-2 w-2 shrink-0 self-center rounded-sm" style={{ background: s.color }} aria-hidden="true" />
            <span className="min-w-0 truncate" title={s.tag ? `${s.label} (${s.tag})` : s.label}>{s.label.replace(/^Core · /, "")}</span>
            <span className="ml-auto shrink-0 text-slate-500">{s.pct.toFixed(0)}%</span>
          </li>
        ))}
      </ul>
      </div>
    </div>
  );
}

/** Every slice of the donut, with its tag and dollars (the card's legend folds the tail into Other). */
function ThesisBreakdown({ all }: { all: Slice[] }) {
  return (
    <DashCard title="By thesis" value={all.length} sub="slices of the book">
      <ul className="divide-y divide-slate-800/70 text-xs tabular-nums">
        {all.map((s) => (
          <li key={s.key} className="flex items-baseline gap-2 py-1">
            <span className="h-2 w-2 shrink-0 self-center rounded-sm" style={{ background: s.color }} aria-hidden="true" />
            <span className="min-w-0 truncate font-medium text-slate-200">{s.label}</span>
            {s.tag && <span className="shrink-0 text-slate-500">{s.tag}</span>}
            <span className="ml-auto shrink-0 text-slate-500">{money(s.value)}</span>
            <span className="w-12 shrink-0 text-right text-slate-200">{s.pct.toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </DashCard>
  );
}

function PositionsCard({ data, open }: { data: PortfolioPayload; open: boolean }) {
  const { rows, aggRows, cashRow } = bookRows(data);
  // The card and its table read one line per ticker; the donut reads the idea slices.
  const unrealized = aggRows.length && aggRows.every((r) => r.unrealized_pl != null)
    ? aggRows.reduce((a, r) => a + (r.unrealized_pl ?? 0), 0) : null;
  const top = useMemo(() => [...aggRows].sort((a, b) => Math.abs(b.market_value) - Math.abs(a.market_value)).slice(0, PEEK), [aggRows]);
  const all = useMemo(() => slices(cashRow ? [...rows, cashRow] : rows), [rows, cashRow]);
  const invested = cashRow?.pct_of_book == null ? null : 100 - cashRow.pct_of_book;
  return (
    <DashCard title="Positions" value={aggRows.length} sub={invested == null ? undefined : `${invested.toFixed(0)}% invested`}
              meta={<>Open <span className={tone(unrealized)}>{signed(unrealized)}</span></>}
              hint="Open for the full positions table, today's movers, composition and the by-thesis breakdown."
              defaultOpen={open} detailTitle={`Positions · ${aggRows.length}`}
              detail={(
                <div className="space-y-2">
                  <div className="grid gap-2 md:grid-cols-2">
                    <ThesisBreakdown all={all} />
                    <CompositionCard data={data} aggRows={aggRows} cashRow={cashRow} />
                    <MoversCard rows={aggRows} />
                  </div>
                  <PositionsTable rows={aggRows} cashRow={cashRow} />
                </div>
              )}>
      <ThesisDonut all={all} />
      {/* On a phone the list peeks at 3 rows; "Show all" has every one. */}
      <div className="mt-2 max-md:[&_li:nth-child(n+4)]:hidden">
        <PeekRows empty="No open positions. Cash only." rows={top.map((r) => ({
          key: `${r.symbol}-${r.idea ?? ""}`, label: contractLabel(r.symbol) ?? r.symbol,
          aside: `${money(r.market_value)} · ${r.pct_of_book == null ? "—" : `${r.pct_of_book.toFixed(1)}%`}`,
          value: signed(r.unrealized_pl), valueClass: tone(r.unrealized_pl),
        }))} />
      </div>
      {aggRows.length > 0 && <p className="mt-1 text-xs text-slate-400">Show all {aggRows.length}</p>}
    </DashCard>
  );
}

/** The staged-order count, signed in only: a visitor makes no admin call and sees no figure. */
function useStagedCount(book: string): number | null {
  const [n, setN] = useState<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      adminCall<{ email: string }>("/api/admin/me")
        .then(() => adminCall<{ orders: unknown[] }>(`/api/portfolio/open-orders?book=${book}`))
        .then((b) => { if (!cancelled && Array.isArray(b.orders)) setN(b.orders.length); })
        .catch(() => undefined);
    };
    load();
    const stop = pollWhileVisible(load);
    return () => { cancelled = true; stop(); };
  }, [book]);
  return n;
}

function TradeCard({ book, open }: { book: string; open: boolean }) {
  const staged = useStagedCount(book);
  const { data: closed } = useApi<ClosedPayload>(`/api/portfolio/closed?book=${book}`, REFRESH_MS);
  const trades = Array.isArray(closed?.trades) ? closed.trades : null;
  const total = trades?.length ? trades.reduce((a, t) => a + t.pnl, 0) : null;
  return (
    <DashCard title="Trade" className="min-w-[16rem] flex-1" hint="Open for the order ticket, hand-offs, staged and recent orders, and closed trades"
              defaultOpen={open} detailTitle="Trade" detail={<TradeTab book={book} />}>
      <dl className="flex flex-wrap gap-x-8 gap-y-1">
        {staged != null && <Fig label="Staged" value={staged} hint="Resting on the broker now: staged entries, protective stops, app orders" />}
        <Fig label="Closed trades" value={trades ? trades.length : "—"} hint="Trades the book has closed" />
        <Fig label="Realized" value={fmtUsd(total, { signed: true, whole: true })} className={tone(total)} hint="Profit or loss from those closed trades" />
      </dl>
    </DashCard>
  );
}
