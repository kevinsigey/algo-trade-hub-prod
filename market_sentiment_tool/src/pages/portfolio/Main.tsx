import { useEffect, useMemo, useState } from "react";

import { useApi } from "@/hooks/usePaperPortfolio";
import {
  aheadOfQqqPts, bestWorstDay, contractLabel, curveRange, curveTradingDays, dailyReturns, drawdownSeries,
  fmtPct, fmtPts, fmtUsd, tone, volatilityPct,
  type ClosedPayload, type PortfolioPayload,
} from "@/lib/paperPortfolio";
import { bookRows, ByIdeaCard, CompositionCard, MoversCard, PositionsTable, SegmentBar, useSegments } from "./BookTab";
import PerformanceTab, { Legend } from "./PerformanceTab";
import TradeTab, { ManualActions } from "./TradeTab";
import { adminCall, DashCard, Fig, money, PEEK, PeekRows, pollWhileVisible, REFRESH_MS, signed, Spark } from "./shared";

/** The main area (Kevin, 2026-11-25): Performance and Positions side by side,
 * Trade along the bottom. Each card is the live summary; its open view holds
 * everything the old Book / Performance / Trade tabs held. */

export type OpenCard = "performance" | "positions" | "trade" | undefined;

export default function PaperMain({ data, book, liveIdeas, open }: {
  data: PortfolioPayload;
  book: string;
  liveIdeas: { id: number; title: string; size_pct: number | null }[];
  open: OpenCard;
}) {
  return (
    <div className="grid gap-2">
      <div className="grid gap-2 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <PerformanceCard data={data} book={book} open={open === "performance"} />
        <PositionsCard data={data} book={book} liveIdeas={liveIdeas} open={open === "positions"} />
      </div>
      <div className="flex flex-wrap items-start gap-2">
        <TradeCard book={book} open={open === "trade"} />
        <ManualActions book={book} />
      </div>
    </div>
  );
}

function PerformanceCard({ data, book, open }: { data: PortfolioPayload; book: string; open: boolean }) {
  const s = data.scoreboard;
  const { data: closed } = useApi<ClosedPayload>(`/api/portfolio/closed?book=${book}`, REFRESH_MS);
  const chart = useMemo(() => {
    const view = curveRange(data.curve, "All");
    const dd = drawdownSeries(view);
    return view.map((p, i) => ({ ...p, dd_pct: dd[i]?.dd_pct ?? 0 }));
  }, [data.curve]);
  const daily = useMemo(() => dailyReturns(data.curve, data.today), [data.curve, data.today]);
  const last = chart[chart.length - 1];
  const lastQqq = [...chart].reverse().find((p) => p.qqq_pct != null);
  const vsSpy = last ? last.portfolio_pct - last.spy_pct : null;
  const vsQqq = lastQqq?.qqq_pct != null ? aheadOfQqqPts(lastQqq.portfolio_pct, lastQqq.qqq_pct) : null;
  const young = curveTradingDays(data.curve) < 20;
  const { best, worst } = bestWorstDay(daily);
  const trades = Array.isArray(closed?.trades) ? closed.trades : [];
  const realized = trades.length ? trades.reduce((a, t) => a + t.pnl, 0) : null;
  return (
    <DashCard title="Performance" value={fmtPct(last?.portfolio_pct)} valueClass={tone(last?.portfolio_pct)}
              sub={<>SPY {fmtPct(last?.spy_pct)} · vs SPY <span className={tone(vsSpy)}>{fmtPts(vsSpy)}</span>
                {vsQqq != null && <> · QQQ {fmtPct(lastQqq?.qqq_pct)} · vs QQQ <span className={tone(vsQqq)}>{fmtPts(vsQqq)}</span></>}</>}
              meta="since start" hint="Return curve vs SPY and QQQ. Open for risk, daily returns, attribution, tested vs discretionary, realized by week and closed trades."
              defaultOpen={open} detailTitle="Performance" detail={<PerformanceTab data={data} book={book} />}>
      <Spark data={chart} height={150} lines={[
        { key: "portfolio_pct", color: "#34d399", width: 2 },
        { key: "spy_pct", color: "#94a3b8", dashed: true },
        { key: "qqq_pct", color: "#38bdf8", dashed: true },
      ]} />
      <Legend items={[["#34d399", "Book"], ["#94a3b8", "SPY"], ["#38bdf8", "QQQ"]]} />
      <dl className="mt-2 grid grid-cols-3 gap-x-3 gap-y-2 sm:grid-cols-6">
        <Fig label="Max drawdown" value={fmtPct(s.max_drawdown_pct)} hint="Deepest fall from a running high, all time." />
        <Fig label="Volatility" value={fmtPct(volatilityPct(daily))} hint="Standard deviation of daily returns, annualized." />
        <Fig label="Sharpe" value={young ? "after 1 mo" : s.sharpe == null ? "—" : s.sharpe.toFixed(2)} hint="Return per unit of risk, annualized. Shown from 20 trading days." />
        <Fig label="Best day" value={best ? fmtPct(best.portfolio_pct) : "—"} className={tone(best?.portfolio_pct)} hint="Best close-to-close day." />
        <Fig label="Worst day" value={worst ? fmtPct(worst.portfolio_pct) : "—"} className={tone(worst?.portfolio_pct)} hint="Worst close-to-close day." />
        <Fig label="Realized" value={signed(realized)} className={tone(realized)} hint="Profit or loss locked in by closed trades." />
      </dl>
    </DashCard>
  );
}

function PositionsCard({ data, book, liveIdeas, open }: {
  data: PortfolioPayload; book: string; open: boolean;
  liveIdeas: { id: number; title: string; size_pct: number | null }[];
}) {
  const { rows, aggRows, cashRow } = bookRows(data);
  const sectors = useSegments(data, aggRows, cashRow, "sector");
  // The card and its table read one line per ticker; By idea reads the idea slices.
  const unrealized = aggRows.length && aggRows.every((r) => r.unrealized_pl != null)
    ? aggRows.reduce((a, r) => a + (r.unrealized_pl ?? 0), 0) : null;
  const top = useMemo(() => [...aggRows].sort((a, b) => Math.abs(b.market_value) - Math.abs(a.market_value)).slice(0, PEEK), [aggRows]);
  const invested = cashRow?.pct_of_book == null ? null : 100 - cashRow.pct_of_book;
  return (
    <DashCard title="Positions" value={aggRows.length} sub={invested == null ? undefined : `${invested.toFixed(0)}% invested`}
              meta={<>Open <span className={tone(unrealized)}>{signed(unrealized)}</span></>}
              hint="Open for the full positions table, today's movers, composition and by-idea."
              defaultOpen={open} detailTitle={`Positions · ${aggRows.length}`}
              detail={(
                <div className="space-y-2">
                  <div className="grid gap-2 md:grid-cols-2">
                    <CompositionCard data={data} aggRows={aggRows} cashRow={cashRow} />
                    <MoversCard rows={aggRows} />
                    <ByIdeaCard rows={rows} equity={data.scoreboard.equity} liveIdeas={liveIdeas} book={book} />
                  </div>
                  <PositionsTable rows={aggRows} cashRow={cashRow} />
                </div>
              )}>
      <SegmentBar segments={sectors} />
      <div className="mt-2">
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
