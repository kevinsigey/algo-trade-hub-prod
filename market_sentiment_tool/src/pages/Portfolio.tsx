import { Link, useSearchParams } from "react-router-dom";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { adminJson } from "@/lib/workshop";
import { ArrowDown, ArrowRight, ArrowUp, Loader2, TriangleAlert } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import CompositionBox from "@/components/CompositionMap";
import { Panel } from "@/components/Panel";
import { ctDateTime } from "@/lib/format";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  breakerLabel,
  concentration,
  dayMovers,
  ideaScorecard,
  contractLabel,
  CURVE_RANGES,
  curveRange,
  fmtPct,
  fmtPts,
  fmtUsd,
  stateLabel,
  tone,
  withOptionsUnderStock,
  type ActivityOrder,
  type ActivityPayload,
  type BookHeadline,
  type BooksPayload,
  type ClosedPayload,
  type CurveRange,
  type ManualAction,
  type PortfolioCheckState,
  type PortfolioPayload,
  type PositionRow,
} from "@/lib/paperPortfolio";

function Box({ title, right, children, className = "", full }: {
  title: string; right?: ReactNode; children: ReactNode; className?: string; full?: ReactNode;
}) {
  return <Panel title={title} meta={right} full={full} className={className}>{children}</Panel>;
}

function RailRow({ label, value, className = "text-slate-100" }: { label: string; value: string; className?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5 text-xs">
      <span className="text-slate-400">{label}</span>
      <span className={`tabular-nums font-medium ${className}`}>{value}</span>
    </div>
  );
}

const money = (v: number | null | undefined) => fmtUsd(v, { whole: true });
const signed = (v: number | null | undefined) => fmtUsd(v, { signed: true, whole: true });
const price = (v: number | null | undefined) => fmtUsd(v);

type SortKey = "symbol" | "last" | "change" | "avg" | "cost" | "value" | "weight" | "day" | "unrealized";

// Directional columns sort by signed value (+x on top, 0 in the middle, -x at the
// bottom); size columns (prices, cost, value, weight) sort by magnitude, so a large
// short sits with the large longs it offsets.
const SIGNED_SORT: ReadonlySet<SortKey> = new Set(["change", "day", "unrealized"]);

const COLUMNS: { key: SortKey; label: string; read: (r: PositionRow) => number | string | null | undefined }[] = [
  { key: "last", label: "Last", read: (r) => r.last_price },
  { key: "change", label: "Chg %", read: (r) => r.change_pct },
  { key: "avg", label: "Avg price", read: (r) => r.avg_price },
  { key: "cost", label: "Cost basis", read: (r) => r.cost_basis },
  { key: "value", label: "Market value", read: (r) => r.market_value },
  { key: "weight", label: "% book", read: (r) => r.pct_of_book },
  { key: "day", label: "Day P&L", read: (r) => r.day_pl },
  { key: "unrealized", label: "Unrealized", read: (r) => r.unrealized_pl },
];

function PositionsTable({ rows }: { rows: PositionRow[] }) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "value", desc: true });
  const ordered = useMemo(() => {
    const read = sort.key === "symbol" ? (r: PositionRow) => r.symbol : COLUMNS.find((c) => c.key === sort.key)!.read;
    const sorted = [...rows].sort((a, b) => {
      const x = read(a), y = read(b);
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1; // unknowns always last
      const order = typeof x === "string" ? x.localeCompare(String(y))
        : SIGNED_SORT.has(sort.key) ? x - Number(y) : Math.abs(x) - Math.abs(Number(y));
      return sort.desc ? -order : order;
    });
    return withOptionsUnderStock(sorted);
  }, [rows, sort]);
  const total = (read: (r: PositionRow) => number | null | undefined) => {
    const known = rows.map(read).filter((v): v is number => v != null);
    return known.length ? known.reduce((a, b) => a + b, 0) : null;
  };
  const head = (key: SortKey, label: string, align = "text-right") => (
    <th key={key} scope="col" aria-sort={sort.key === key ? (sort.desc ? "descending" : "ascending") : "none"}
        className={`whitespace-nowrap px-2 py-1.5 font-medium ${align}`}>
      <button type="button" onClick={() => setSort({ key, desc: sort.key === key ? !sort.desc : key !== "symbol" })}
              className="inline-flex items-center gap-0.5 rounded hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
        {label}
        {sort.key === key && (sort.desc ? <ArrowDown className="h-3 w-3" aria-hidden="true" /> : <ArrowUp className="h-3 w-3" aria-hidden="true" />)}
      </button>
    </th>
  );
  if (rows.length === 0) return <p className="text-sm text-slate-400">No open positions. Cash only.</p>;
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[56rem] text-[13px] tabular-nums">
        <thead className="text-left text-xs text-slate-400">
          <tr>
            {head("symbol", "Instrument", "sticky left-0 bg-slate-900 text-left")}
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Position</th>
            {COLUMNS.map((c) => head(c.key, c.label))}
            <th scope="col" className="px-2 py-1.5 font-medium">Idea</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((r) => {
            const option = contractLabel(r.symbol);
            return (
              <tr key={`${r.symbol}-${r.idea ?? ""}`} className="border-t border-slate-800/80 hover:bg-slate-800/40">
                <td className={`sticky left-0 whitespace-nowrap bg-slate-900 px-2 py-1.5 font-semibold text-white ${option ? "pl-6 font-normal text-slate-200" : ""}`}>
                  {option ?? r.symbol}
                  {r.side === "short" && <span className="ml-1.5 text-xs font-normal text-amber-300">short</span>}
                </td>
                <td className="px-2 py-1.5 text-right text-slate-300">{r.qty ?? "—"}</td>
                <td className="px-2 py-1.5 text-right text-slate-200">{price(r.last_price)}</td>
                <td className={`px-2 py-1.5 text-right ${tone(r.change_pct)}`}>{fmtPct(r.change_pct)}</td>
                <td className="px-2 py-1.5 text-right text-slate-300">{price(r.avg_price)}</td>
                <td className="px-2 py-1.5 text-right text-slate-300">{money(r.cost_basis)}</td>
                <td className="px-2 py-1.5 text-right font-medium text-white">{money(r.market_value)}</td>
                <td className="px-2 py-1.5 text-right text-slate-300">{r.pct_of_book == null ? "—" : `${r.pct_of_book.toFixed(1)}%`}</td>
                <td className={`px-2 py-1.5 text-right ${tone(r.day_pl)}`}>{signed(r.day_pl)}</td>
                <td className={`px-2 py-1.5 text-right ${tone(r.unrealized_pl)}`}>{signed(r.unrealized_pl)}</td>
                <td className="max-w-[16rem] truncate px-2 py-1.5 text-slate-300" title={r.idea ?? undefined}>{r.idea ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot className="border-t border-slate-700 font-semibold text-white">
          <tr>
            <td className="sticky left-0 bg-slate-900 px-2 py-1.5">Total</td>
            <td colSpan={4} />
            <td className="px-2 py-1.5 text-right">{money(total((r) => r.cost_basis))}</td>
            <td className="px-2 py-1.5 text-right">{money(total((r) => r.market_value))}</td>
            <td className="px-2 py-1.5 text-right">{`${(total((r) => r.pct_of_book) ?? 0).toFixed(1)}%`}</td>
            <td className={`px-2 py-1.5 text-right ${tone(total((r) => r.day_pl))}`}>{signed(total((r) => r.day_pl))}</td>
            <td className={`px-2 py-1.5 text-right ${tone(total((r) => r.unrealized_pl))}`}>{signed(total((r) => r.unrealized_pl))}</td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/** Each paper book with its headline, as the page's tabs: no separate "both books" view to pass through. */
/** The largest holdings at a glance; the full sortable table opens from the panel. */
function PositionsSummary({ rows, n = 5 }: { rows: PositionRow[]; n?: number }) {
  if (rows.length === 0) return <p className="text-sm text-slate-400">No open positions. Cash only.</p>;
  const top = [...rows].sort((a, b) => Math.abs(b.market_value) - Math.abs(a.market_value)).slice(0, n);
  return (
    <>
      <table className="w-full text-xs tabular-nums">
        <thead><tr className="text-left text-slate-500">
          <th scope="col" className="pb-1 pr-2 font-medium">Symbol</th>
          <th scope="col" className="pb-1 pr-2 text-right font-medium">Value</th>
          <th scope="col" className="pb-1 pr-2 text-right font-medium">Book</th>
          <th scope="col" className="pb-1 pr-2 text-right font-medium">Today</th>
          <th scope="col" className="pb-1 text-right font-medium">Open P&amp;L</th>
        </tr></thead>
        <tbody>
          {top.map((r) => (
            <tr key={`${r.symbol}-${r.idea ?? ""}`} className="border-t border-slate-800/70">
              <td className="py-1 pr-2 font-semibold text-white">{contractLabel(r.symbol) ?? r.symbol}</td>
              <td className="py-1 pr-2 text-right text-slate-200">{money(r.market_value)}</td>
              <td className="py-1 pr-2 text-right text-slate-400">{r.pct_of_book == null ? "—" : `${r.pct_of_book.toFixed(1)}%`}</td>
              <td className={`py-1 pr-2 text-right ${tone(r.day_pl)}`}>{signed(r.day_pl)}</td>
              <td className={`py-1 text-right ${tone(r.unrealized_pl)}`}>{signed(r.unrealized_pl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > n && <p className="mt-1 text-[11px] text-slate-500">{rows.length - n} more in the full table</p>}
    </>
  );
}

function BookTabs({ book }: { book: string }) {
  const { data } = useApi<BooksPayload>("/api/portfolio/books");
  const books: BookHeadline[] = Array.isArray(data?.books) ? data.books : [];
  const shown = books.length ? books : [{ book: "main", label: "Main book" }, { book: "big", label: "$1M book" }] as BookHeadline[];
  return (
    <nav aria-label="Paper books" className="flex flex-wrap gap-2">
      {shown.map((b) => {
        const active = b.book === book;
        return (
          <Link key={b.book} to={`/portfolio?book=${b.book}`} aria-current={active ? "page" : undefined}
                className={`rounded-lg border px-3 py-1.5 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${active ? "border-emerald-500/50 bg-emerald-500/10" : "border-slate-700 hover:bg-slate-800/60"}`}>
            <span className={active ? "font-semibold text-white" : "text-slate-200"}>{b.label}</span>
            {b.state === "not_connected" ? (
              <span className="ml-2 text-xs text-slate-400">not connected</span>
            ) : b.equity != null && (
              <span className="ml-2 tabular-nums text-slate-300">
                {money(b.equity)} <span className={tone(b.return_pct)}>{fmtPct(b.return_pct)}</span>
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

export default function Portfolio() {
  const [searchParams] = useSearchParams();
  const book = searchParams.get("book") === "big" ? "big" : "main";
  const { data, error, loading } = useApi<PortfolioPayload>(`/api/portfolio?book=${book}`);
  type IdeaRow = { id: number; title: string; size_pct: number | null; live_at: string | null; killed_at: string | null; auto_orders: boolean; books?: { big?: { live_at: string | null; size_pct: number | null; auto_orders: boolean; killed_at: string | null } } };
  const [ideaRows, setIdeaRows] = useState<IdeaRow[]>([]);
  useEffect(() => {
    let cancelled = false;
    // Admin only: a signed-out visitor gets a 401 and simply sees no list.
    adminJson<IdeaRow[]>("/api/workshop/ideas")
      .then((rows) => { if (!cancelled) setIdeaRows(Array.isArray(rows) ? rows : []); })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  // The ideas trading on the book in view: main reads the idea rows, the $1M book
  // reads its own activations -- different ideas at different sizes per book.
  const liveIdeas = ideaRows.flatMap((r) => {
    if (book === "big") {
      const a = r.books?.big;
      return a && a.live_at && !a.killed_at && a.auto_orders
        ? [{ id: r.id, title: r.title, size_pct: a.size_pct }] : [];
    }
    return r.live_at && !r.killed_at && r.auto_orders
      ? [{ id: r.id, title: r.title, size_pct: r.size_pct }] : [];
  });

  return (
    <div className="mx-auto max-w-[100rem] px-4 py-5 md:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-white">Portfolio</h1>
        <BookTabs book={book} />
      </div>

      {data && data.state !== "not_connected" && (
        <div className="mt-4 empty:hidden"><ManualActions book={book} /></div>
      )}

      {loading && (
        <div className="mt-8 flex items-center gap-2 text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Reading the account…
        </div>
      )}
      {error && <p className="mt-8 text-rose-300">Could not read the portfolio: {error}</p>}

      {data && data.state === "not_connected" && (
        <div className="mt-6 rounded-xl border border-slate-800 p-6">
          <div className="text-xl font-semibold text-white">Paper account not connected</div>
          <p className="mt-1 max-w-prose text-sm text-slate-400">
            The paper trading account is not linked yet. Numbers appear here from its first snapshot, never before.
          </p>
        </div>
      )}

      {data && data.state !== "not_connected" && data.scoreboard && (
        <Body data={data} liveIdeas={liveIdeas} book={book} />
      )}
    </div>
  );
}

function AccountRail({ data }: { data: PortfolioPayload }) {
  const s = data.scoreboard;
  const a = data.account;
  const cashRow = data.positions.find((p) => p.symbol === "Cash");
  const investedPct = cashRow?.pct_of_book == null ? null : 100 - cashRow.pct_of_book;
  const rows = data.positions.filter((p) => p.symbol !== "Cash");
  const unrealized = rows.some((p) => p.unrealized_pl != null) ? rows.reduce((sum, p) => sum + (p.unrealized_pl ?? 0), 0) : null;
  return (
    <aside aria-label="Account" className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="text-xs text-slate-400">Net liquidation value</div>
      <div className="mt-0.5 text-2xl font-semibold tabular-nums tracking-tight text-white">{money(s.equity)}</div>
      <div className={`mt-1 text-sm font-medium tabular-nums ${tone(a?.day_pl)}`}>
        {a?.day_pl == null ? "Day P&L unknown" : `${signed(a.day_pl)} (${fmtPct(a.day_pl_pct)}) today`}
      </div>
      <p className={`mt-1 text-[11px] ${data.state === "live" ? "text-emerald-300" : "text-amber-300"}`}>
        {stateLabel(data.state, data.as_of)}
      </p>
      <div className="mt-2 border-t border-slate-800 pt-1.5">
        <RailRow label="Cash" value={money(a?.cash ?? cashRow?.market_value)} />
        <RailRow label="Buying power" value={money(a?.buying_power)} />
        <RailRow label="Invested" value={investedPct == null ? "—" : `${investedPct.toFixed(0)}%`} />
        <RailRow label="Long value" value={money(a?.long_value)} />
        <RailRow label="Short value" value={money(a?.short_value)} />
      </div>
      <div className="mt-1.5 border-t border-slate-800 pt-1.5">
        <RailRow label="Unrealized P&L" value={signed(unrealized)} className={tone(unrealized)} />
        <RailRow label="Realized P&L" value={signed(a?.realized_pl)} className={tone(a?.realized_pl)} />
        <RailRow label="Maintenance margin" value={money(a?.maintenance_margin)} />
        <RailRow label="Positions" value={String(rows.length)} />
        {data.breaker && (
          <RailRow label="Circuit breaker" value={breakerLabel(data.breaker)}
                   className={data.breaker.tripped ? "text-rose-400" : "text-slate-100"} />
        )}
      </div>
      <div className="mt-1.5 border-t border-slate-800 pt-1.5">
        <RailRow label="Since start" value={fmtPct(s.return_pct)} className={tone(s.return_pct)} />
        <RailRow label="SPY same period" value={fmtPct(s.spy_return_pct)} />
        <RailRow label="Ahead of SPY" value={fmtPts(s.ahead_pts)} className={tone(s.ahead_pts)} />
      </div>
    </aside>
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
    // A Sharpe ratio on under a month of days is noise (it read -8.11 on day 5, 2026-11-09).
    { label: "Sharpe", value: data.curve.length < 21 ? "after 1 month" : s.sharpe == null ? "—" : s.sharpe.toFixed(2) },
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

function Body({ data, liveIdeas, book }: {
  data: PortfolioPayload;
  liveIdeas: { id: number; title: string; size_pct: number | null }[];
  book: string;
}) {
  const rows = data.positions.filter((p) => p.symbol !== "Cash");
  const heavy = concentration(rows);
  // One screen at 1440x900 (Kevin, 2026-11-06): every panel is a summary that opens in full, in a tight grid.
  return (
    <div className="mt-3 space-y-2">
      {data.breaker?.tripped && (
        <p role="alert" className="flex items-start gap-2 rounded-lg border border-rose-500/50 px-3 py-1.5 text-sm text-rose-200">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          Circuit breaker tripped: {data.breaker.reasons.join("; ")}. New opening orders are refused; closing and protective orders still pass.
        </p>
      )}
      {heavy.map((h) => (
        <p key={h.sector} className="flex items-start gap-2 rounded-lg border border-amber-500/40 px-3 py-1.5 text-xs text-amber-200">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {h.sector} is {h.pct.toFixed(0)}% of what&apos;s invested. These positions tend to move together.
        </p>
      ))}
      <div className="grid gap-2 xl:grid-cols-12">
        <div className="flex min-w-0 flex-col gap-2 xl:col-span-3">
          <AccountRail data={data} />
          <MoversBox rows={rows} />
          <OrderForm book={book} />
        </div>
        <div className="grid min-w-0 content-start gap-2 lg:grid-cols-2 xl:col-span-9">
          <Performance data={data} />
          <CompositionBox positions={data.positions} composition={data.composition} />
          <Box title={`Positions · ${rows.length}`} full={<PositionsTable rows={rows} />}>
            <PositionsSummary rows={rows} />
          </Box>
          {/* Targets belong to the book in view: a payload still from the other book shows holdings only. */}
          <IdeasBox rows={rows} equity={data.scoreboard.equity ?? 0} liveIdeas={(data.book ?? "main") === book ? liveIdeas : []} />
          <PortfolioCheckBox book={book} />
          <OrdersBox book={book} />
          <div className="flex min-w-0 flex-col gap-2">
            <RecentTrades book={book} />
            <StagedOrders book={book} />
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * The book by idea (Kevin, 2026-11-05): what each idea holds, today's move, its open P&L and how
 * far it sits from its set size. Set sizes come from the admin idea list, so a signed-out visit
 * shows the holdings without the target column.
 */
function IdeasBox({ rows, equity, liveIdeas }: {
  rows: PositionRow[]; equity: number; liveIdeas: { id: number; title: string; size_pct: number | null }[];
}) {
  const cards = useMemo(() => ideaScorecard(rows, equity, liveIdeas), [rows, equity, liveIdeas]);
  const scale = Math.max(10, ...cards.map((c) => Math.max(c.pct, c.target_pct ?? 0)));
  const known = cards.some((c) => c.target_pct != null);
  const table = (list: typeof cards) => (
      <div className="overflow-x-auto">
        <table className="w-full text-xs tabular-nums">
          <thead>
            <tr className="text-left text-xs text-slate-500">
              <th className="pb-1 pr-3 font-medium">Idea</th>
              <th className="pb-1 pr-3 font-medium">Size</th>
              <th className="pb-1 pr-3 text-right font-medium">Value</th>
              <th className="pb-1 pr-3 text-right font-medium">Today</th>
              <th className="pb-1 text-right font-medium">Open P&amp;L</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/70">
            {list.map((c) => {
              const manual = c.id == null && c.idea.endsWith("(manual)");
              const off = c.target_pct != null ? c.pct - c.target_pct : null;
              return (
                <tr key={c.idea} className={manual ? "text-slate-400" : "text-slate-200"}>
                  <td className="max-w-[22rem] py-1 pr-3">
                    {c.id != null ? (
                      <Link to={`/workshop/${c.id}`} className="line-clamp-1 hover:text-white hover:underline underline-offset-2">{c.idea}</Link>
                    ) : <span className="line-clamp-1">{c.idea}</span>}
                    <div className="text-[11px] text-slate-500">
                      {c.positions === 0 ? "nothing held yet" : `${c.positions} position${c.positions === 1 ? "" : "s"}`}
                    </div>
                  </td>
                  <td className="w-44 py-1 pr-3">
                    <div className="relative h-1.5 rounded-full bg-slate-800" role="img"
                         aria-label={`${c.pct.toFixed(1)}% of the book${c.target_pct != null ? `, set size ${c.target_pct}%` : ""}`}>
                      <div className={`absolute inset-y-0 left-0 rounded-full ${manual ? "bg-slate-500" : "bg-emerald-400/80"}`}
                           style={{ width: `${Math.min(100, (c.pct / scale) * 100)}%` }} />
                      {c.target_pct != null && (
                        <div className="absolute -top-1 h-3.5 w-px bg-slate-200" style={{ left: `${Math.min(100, (c.target_pct / scale) * 100)}%` }} />
                      )}
                    </div>
                    <div className="mt-1 text-[11px] text-slate-400">
                      {c.pct.toFixed(1)}%
                      {off != null && Math.abs(off) >= 1 && (
                        <span className="text-amber-300"> · {off > 0 ? `${off.toFixed(1)} pts over` : `${(-off).toFixed(1)} pts under`}</span>
                      )}
                    </div>
                  </td>
                  <td className="py-1 pr-3 text-right">{fmtUsd(c.value, { whole: true })}</td>
                  <td className={`py-1 pr-3 text-right ${tone(c.day_pl)}`}>{c.positions && c.day_pl != null ? fmtUsd(c.day_pl, { signed: true, whole: true }) : "—"}</td>
                  <td className={`py-1 text-right ${tone(c.unrealized)}`}>
                    {c.positions && c.unrealized != null ? fmtUsd(c.unrealized, { signed: true, whole: true }) : "—"}
                    {c.return_pct != null && <div className="text-[11px]">{fmtPct(c.return_pct)}</div>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  return (
    <Box title={`By idea · ${cards.filter((c) => c.id != null || !c.idea.endsWith("(manual)")).length} ideas`}
         full={table(cards)}
         right={<span className="text-xs text-slate-500">{known ? "bar: held · tick: set size" : "bar: % of book"}</span>}>
      {table(cards.slice(0, 4))}
      {cards.length > 4 && <p className="mt-1 text-[11px] text-slate-500">{cards.length - 4} more ideas in the full view</p>}
    </Box>
  );
}

/** Today's biggest dollar moves, so a bad day reads as "which names", not just a total. */
function MoversBox({ rows }: { rows: PositionRow[] }) {
  const { up, down, known } = useMemo(() => dayMovers(rows), [rows]);
  const line = (r: PositionRow) => (
    <li key={r.symbol} className="flex items-baseline justify-between gap-2 py-1">
      <span className="font-medium text-slate-200">{r.symbol}</span>
      <span className="text-xs text-slate-500">{fmtPct(r.change_pct)}</span>
      <span className={`ml-auto tabular-nums ${tone(r.day_pl)}`}>{fmtUsd(r.day_pl, { signed: true, whole: true })}</span>
    </li>
  );
  return (
    <Box title="Today's movers">
      {!known && rows.length > 0 ? (
        <p className="text-sm text-slate-400">Today's P&amp;L isn't available right now.</p>
      ) : up.length + down.length === 0 ? (
        <p className="text-sm text-slate-400">No moves yet today.</p>
      ) : (
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div><div className="text-xs text-slate-500">Gaining</div><ul>{up.map(line)}</ul>{!up.length && <p className="py-1 text-slate-500">None</p>}</div>
          <div><div className="text-xs text-slate-500">Losing</div><ul>{down.map(line)}</ul>{!down.length && <p className="py-1 text-slate-500">None</p>}</div>
        </div>
      )}
    </Box>
  );
}

const STATUS_TONE: Record<string, string> = {
  filled: "text-emerald-400", expired: "text-rose-400", rejected: "text-rose-400", canceled: "text-slate-400",
};

/** What the broker did with recent orders: an order the hub sent can still expire unfilled. */
function OrdersBox({ book }: { book: string }) {
  const { data } = useApi<ActivityPayload>(`/api/portfolio/activity?book=${book}`);
  const all: ActivityOrder[] = Array.isArray(data?.recent) ? data.recent : [];
  const recent = all.slice(0, 4);
  const table = (list: ActivityOrder[]) => (
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[38rem] text-left text-xs tabular-nums">
            <thead className="text-slate-400">
              <tr>
                <th scope="col" className="py-1 pr-3 font-medium">Sent</th>
                <th scope="col" className="py-1 pr-3 font-medium">Order</th>
                <th scope="col" className="py-1 pr-3 text-right font-medium">Filled</th>
                <th scope="col" className="py-1 pr-3 text-right font-medium">Avg price</th>
                <th scope="col" className="py-1 pr-3 font-medium">Status</th>
                <th scope="col" className="py-1 font-medium">From</th>
              </tr>
            </thead>
            <tbody>
              {list.map((o, i) => (
                <tr key={`${o.symbol}-${o.submitted_at}-${i}`} className="border-t border-slate-800/80 text-slate-200">
                  <td className="whitespace-nowrap py-1.5 pr-3 text-slate-400">{o.submitted_at ? ctDateTime(o.submitted_at) : "—"}</td>
                  <td className="whitespace-nowrap py-1.5 pr-3">{o.side} <span className="font-semibold text-white">{contractLabel(o.symbol) ?? o.symbol}</span> <span className="text-slate-400">{o.type} · {o.time_in_force}</span></td>
                  <td className="py-1.5 pr-3 text-right">{o.filled_qty ?? 0}/{o.qty ?? "—"}</td>
                  <td className="py-1.5 pr-3 text-right">{price(o.filled_avg_price)}</td>
                  <td className={`py-1.5 pr-3 ${STATUS_TONE[o.status] ?? "text-amber-300"}`}>{o.status}</td>
                  <td className="max-w-[12rem] truncate py-1.5 text-slate-400" title={o.source}>{o.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
  );
  return (
    <Box title="Recent orders" full={all.length ? table(all) : undefined}
         right={(
           <Link to={`/portfolio/closed?book=${book}`} aria-label="All orders and trades" className="inline-flex items-center gap-1 text-xs text-emerald-300 hover:text-emerald-200">
             All <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
           </Link>
         )}>
      {recent.length === 0 ? (
        <p className="text-sm text-slate-400">No orders yet.</p>
      ) : (
        <ul className="space-y-0.5 text-xs tabular-nums">
          {recent.map((o, i) => (
            <li key={`${o.symbol}-${o.submitted_at}-${i}`} className="flex items-baseline justify-between gap-2 border-t border-slate-800/70 pt-1">
              <span className="truncate text-slate-300">
                <span className="text-slate-500">{o.submitted_at ? ctDateTime(o.submitted_at) : "—"}</span>{" "}
                {o.side} <span className="font-semibold text-white">{contractLabel(o.symbol) ?? o.symbol}</span> {o.filled_qty ?? 0}/{o.qty ?? "—"}
              </span>
              <span className={`shrink-0 ${STATUS_TONE[o.status] ?? "text-amber-300"}`}>{o.status}</span>
            </li>
          ))}
        </ul>
      )}
    </Box>
  );
}

/** The last few closed trades, as a box (the full record stays one click
 * away on Trades and Orders). */
function RecentTrades({ book }: { book: string | null }) {
  const { data } = useApi<ClosedPayload>(book ? `/api/portfolio/closed?book=${book}` : "/api/portfolio/closed");
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

type OpenOrder = {
  alpaca_order_id: string | null; client_order_id: string | null; symbol: string | null;
  side: string | null; type: string | null; time_in_force: string | null;
  qty: number | null; filled_qty: number | null; limit_price: number | null;
  stop_price: number | null; status: string | null; submitted_at: string | null;
};

/**
 * Staged orders: everything resting on the paper account right now -- the staged
 * opening-auction entries, the protective stops, anything placed in the Alpaca app --
 * read from the broker, not from the hub's own records. Signed-in only, like the
 * order form: /api/admin/me gates it, and a failed read simply shows nothing.
 */
/** Needs your hand: the auto-trader's hand-offs for this book (Kevin, 2026-11-02) --
 * option legs it would not price or size alone. Signed-in only, like the order form:
 * a visitor's read 401s and the box simply never appears. Done/Dismiss are Kevin's
 * clicks; the runner never resolves its own hand-offs. */
function ManualActions({ book }: { book: string }) {
  const [actions, setActions] = useState<ManualAction[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    adminJson<{ actions: ManualAction[] }>(`/api/portfolio/manual-actions?book=${book}`)
      .then((body) => { if (!cancelled) setActions(Array.isArray(body.actions) ? body.actions : []); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [book]);

  if (actions === null || actions.length === 0) return null;

  async function resolve(id: number, state: "done" | "dismissed") {
    try {
      await adminJson(`/api/portfolio/manual-actions/${id}/resolve`, {
        method: "POST", body: JSON.stringify({ state }),
      });
      setActions((prev) => (prev ?? []).filter((a) => a.id !== id));
    } catch { /* the row stays; Kevin can retry */ }
  }

  return (
    <Box title="Needs your hand" className="border-amber-500/40">
      <p className="text-xs text-slate-400">
        The auto-trader stopped on these instead of guessing. Each one names the contract and the reason.
      </p>
      <ul className="mt-3 space-y-3">
        {actions.map((a) => (
          <li key={a.id} className="rounded-lg border border-slate-800 p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-sm font-medium text-white">
                {a.idea_title ?? (a.idea_id ? `Idea ${a.idea_id}` : "Auto-trader")}
                {a.symbol ? <span className="ml-2 text-xs text-slate-400">{a.symbol}</span> : null}
              </span>
              <span className="text-[11px] text-slate-500">{a.created_at.slice(0, 10)}</span>
            </div>
            <p className="mt-1 text-xs text-slate-300">{a.detail}</p>
            <div className="mt-2 flex gap-2">
              <button type="button" onClick={() => resolve(a.id, "done")}
                className="rounded-md border border-emerald-500/40 px-2.5 py-1 text-xs font-medium text-emerald-300 hover:bg-emerald-500/10">
                Done
              </button>
              <button type="button" onClick={() => resolve(a.id, "dismissed")}
                className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-900">
                Dismiss
              </button>
            </div>
          </li>
        ))}
      </ul>
    </Box>
  );
}

const CHECK_STATUS_TONE: Record<string, string> = {
  ok: "text-slate-100", over: "text-rose-300", under: "text-amber-300",
};
const CHECK_BAR_FILL: Record<string, string> = {
  ok: "bg-slate-400", over: "bg-rose-400", under: "bg-amber-400",
};
const CHECK_CLUSTER_GLYPH: Record<string, string> = {
  rates: "◐", ai_complex: "●", gold: "■",
};
// Gold's hard flag, from the check's own seed config (tradehub/portfolio/
// portfolio_check.py): over 12% of invested warns. The card payload carries no
// per-cluster cap, so the gold chip tints on this documented number.
const GOLD_FLAG_PCT = 12;
const CHECK_OUTCOME_TONE: Record<string, string> = {
  pass: "text-emerald-300", warn: "text-amber-300", block: "text-rose-300", unavailable: "text-slate-400",
};

/**
 * The portfolio check, as a card (Kevin, 2026-11-09; compact visual pass, same day):
 * one horizontal weight bar per sleeve, plus a bar for each member that carries a cap
 * or is off status -- the bar filled to its weight with floor / target / cap ticks on
 * the same track, so an over-cap name reads instantly: its fill crosses the cap tick.
 * The three factor clusters ride as chips under the bars, cash is the last bar, and the
 * latest check outcome sits in the card header. The full member table, the correlation
 * readout and every recent check outcome stay behind the panel's open view.
 * One engine with the preflight gate and the activation gate
 * (tradehub.portfolio.portfolio_check) and the same stored targets and series, so the
 * card can never disagree with the gates. Weights are % of invested (cash: % of
 * equity). Signed-in only: signed out, it renders nothing.
 */
function PortfolioCheckBox({ book }: { book: string }) {
  const [state, setState] = useState<PortfolioCheckState | null>(null);

  useEffect(() => {
    let cancelled = false;
    adminJson<PortfolioCheckState>(`/api/portfolio/portfolio-check?book=${book}`)
      .then((body) => {
        // Shape-guarded like ManualActions: anything that isn't the card's own
        // payload (a signed-out stub, another endpoint's body) renders nothing.
        if (!cancelled && body && Array.isArray(body.sleeves) && Array.isArray(body.recent_checks)) {
          setState(body);
        }
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [book]);

  if (state === null) return null;

  const pct = (v: number, dp = 1) => `${v.toFixed(dp)}%`;
  type CheckBar = {
    key: string; label: string; nested?: boolean; weight: number;
    floor: number | null; target: number | null; cap: number | null;
    status: string; note?: string; neutral?: boolean;
  };
  const bars: CheckBar[] = [];
  for (const s of state.sleeves) {
    bars.push({
      key: s.id, label: s.label, weight: s.weight_pct, floor: null, target: null,
      cap: s.exit_only ? null : s.sleeve_max_pct, status: s.status,
      note: s.exit_only ? "exit-only" : undefined,
    });
    for (const m of s.members) {
      // A member earns its own bar when a cap binds it or it is off status; the rest
      // live in the open view's member table.
      if (m.max_pct == null && m.status === "ok") continue;
      bars.push({
        key: `${s.id}-${m.symbol}`, label: m.symbol, nested: true, weight: m.weight_pct,
        floor: m.min_pct, target: m.target_pct, cap: m.max_pct, status: m.status,
      });
    }
  }
  if (state.cash_pct != null) {
    bars.push({
      key: "cash", label: "Cash", weight: state.cash_pct, floor: null, target: null,
      cap: null, status: "ok", neutral: true,
    });
  }
  // One shared scale so bar lengths compare across rows; the floor keeps a small
  // book's bars from stretching to full width over a few percent.
  const scale = Math.max(20, ...bars.flatMap((b) => [b.weight, b.cap ?? 0, b.target ?? 0]));
  const at = (v: number) => `${Math.min(100, (v / scale) * 100)}%`;
  const tick = (v: number | null, cls: string, name: string) =>
    v == null ? null : (
      <span key={name} title={`${name} ${v}%`} aria-hidden="true"
        className={`absolute -top-[2px] h-[14px] w-[2px] ${cls}`} style={{ left: at(v) }} />
    );

  const last = state.recent_checks[0];
  const right = last ? (
    <span className="text-[11px] text-slate-400">
      last check{" "}
      <span className={`font-semibold uppercase ${CHECK_OUTCOME_TONE[last.outcome ?? "unavailable"]}`}>
        {last.outcome ?? "unavailable"}
      </span>
      {last.symbol ? <span> · {last.symbol}</span> : null}
    </span>
  ) : undefined;

  const full = (
    <div>
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="text-[11px] uppercase tracking-wide text-slate-500">
            <th className="py-1 pr-3">Name</th><th className="py-1 pr-3">Weight</th>
            <th className="py-1 pr-3">Target</th><th className="py-1 pr-3">Floor</th>
            <th className="py-1 pr-3">Cap</th><th className="py-1 pr-3">Corr to book</th>
            <th className="py-1">Status</th>
          </tr>
        </thead>
        <tbody>
          {state.sleeves.flatMap((s) => [
            <tr key={s.id} className="border-t border-slate-800 font-medium text-slate-200">
              <td className="py-1 pr-3">{s.label}</td>
              <td className="py-1 pr-3 tabular-nums">{pct(s.weight_pct, 2)}</td>
              <td className="py-1 pr-3">—</td><td className="py-1 pr-3">—</td>
              <td className="py-1 pr-3">{s.exit_only ? "exit-only" : s.sleeve_max_pct != null ? pct(s.sleeve_max_pct, 0) : "—"}</td>
              <td className="py-1 pr-3 tabular-nums">{s.correlation_to_book != null ? s.correlation_to_book.toFixed(2) : "—"}</td>
              <td className={`py-1 ${CHECK_STATUS_TONE[s.status]}`}>{s.status}</td>
            </tr>,
            ...s.members.map((m) => (
              <tr key={`${s.id}-${m.symbol}`} className="text-slate-400">
                <td className="py-1 pr-3 pl-4">{m.symbol}</td>
                <td className="py-1 pr-3 tabular-nums">{pct(m.weight_pct, 2)}</td>
                <td className="py-1 pr-3">{m.target_pct != null ? pct(m.target_pct) : "—"}</td>
                <td className="py-1 pr-3">{m.min_pct != null ? pct(m.min_pct) : "—"}</td>
                <td className="py-1 pr-3">{m.max_pct != null ? pct(m.max_pct) : "—"}</td>
                <td className="py-1 pr-3">—</td>
                <td className={`py-1 ${CHECK_STATUS_TONE[m.status]}`}>{m.status}</td>
              </tr>
            )),
          ])}
          {state.unassigned.map((u) => (
            <tr key={u.symbol} className="text-slate-400">
              <td className="py-1 pr-3 pl-4">{u.symbol} (unassigned)</td>
              <td className="py-1 pr-3 tabular-nums">{pct(u.weight_pct, 2)}</td>
              <td className="py-1 pr-3">—</td><td className="py-1 pr-3">—</td>
              <td className="py-1 pr-3">5%</td><td className="py-1 pr-3">—</td>
              <td className="py-1 text-slate-100">ok</td>
            </tr>
          ))}
        </tbody>
      </table>
      {state.recent_checks.length > 0 && (
        <ul className="mt-3 space-y-1.5 border-t border-slate-800 pt-2">
          {state.recent_checks.map((e, i) => (
            <li key={i} className="text-xs text-slate-300">
              <span className={`font-semibold uppercase ${CHECK_OUTCOME_TONE[e.outcome ?? "unavailable"]}`}>
                {e.outcome ?? "unavailable"}
              </span>{" "}
              {e.symbol ? <span className="text-slate-400">{e.symbol} · </span> : null}
              {e.detail}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[11px] text-slate-500">
        Targets updated {state.targets_updated_at ? ctDateTime(state.targets_updated_at) : "never (seed values)"};
        return series refreshed {state.series_refreshed_at ? ctDateTime(state.series_refreshed_at) : "not yet"}.
      </p>
    </div>
  );

  return (
    <Box title="Portfolio check" className="lg:col-span-2" full={full} right={right}>
      <div className="space-y-1">
        {bars.map((b) => (
          <div key={b.key} className="flex items-center gap-2 text-xs">
            <span className={`w-40 shrink-0 truncate ${b.nested ? "pl-4 text-slate-400" : "text-slate-300"}`}>
              {b.label}
              {b.note ? <span className="text-slate-500"> · {b.note}</span> : null}
            </span>
            <div className="relative h-2.5 min-w-0 flex-1 rounded bg-slate-800">
              <div className={`h-full rounded ${b.neutral ? "bg-slate-500" : CHECK_BAR_FILL[b.status]}`}
                style={{ width: at(b.weight) }} />
              {tick(b.floor, "bg-slate-500", "floor")}
              {tick(b.target, "bg-sky-300", "target")}
              {tick(b.cap, "bg-white", "cap")}
            </div>
            <span className={`w-14 shrink-0 text-right tabular-nums font-medium ${CHECK_STATUS_TONE[b.status]}`}>
              {pct(b.weight)}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-1.5 text-[11px] text-slate-500">
        Bars: % of invested (cash: % of equity). Ticks on a bar:{" "}
        <span className="text-slate-400">floor</span> · <span className="text-sky-300">target</span> ·{" "}
        <span className="text-slate-100">cap</span> — a fill past the white tick is over its cap.
      </p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {Object.entries(state.clusters).map(([id, c]) => {
          // The payload carries no per-cluster cap; the one state-level flag the
          // engine documents is gold's hard flag at 12% of invested (the check's own
          // seed config -- the same 12% the GLD bar shows as its cap tick).
          const flagged = id === "gold" && c.pct > GOLD_FLAG_PCT;
          return (
            <span key={id}
              className={`inline-flex items-baseline gap-1.5 rounded-full border px-2 py-0.5 text-[11px] ${
                flagged ? "border-amber-500/60 bg-amber-400/10 text-amber-200" : "border-slate-700 text-slate-300"
              }`}>
              <span aria-hidden="true">{CHECK_CLUSTER_GLYPH[id] ?? "●"}</span>
              {c.label}
              <span className="font-semibold tabular-nums">{pct(c.pct)}</span>
              {c.with_flagged_pct != null && c.with_flagged_pct !== c.pct
                ? <span className={flagged ? "text-amber-200/70" : "text-slate-500"}>{pct(c.with_flagged_pct)} incl. GLD</span>
                : null}
            </span>
          );
        })}
      </div>
    </Box>
  );
}

function StagedOrders({ book }: { book: string }) {
  const [orders, setOrders] = useState<OpenOrder[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    adminJson<{ email: string }>("/api/admin/me")
      .then(() => adminJson<{ orders: OpenOrder[] }>(`/api/portfolio/open-orders?book=${book}`))
      .then((body) => { if (!cancelled) setOrders(Array.isArray(body.orders) ? body.orders : []); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [book]);

  if (orders === null) return null;
  const price = (o: OpenOrder) => o.stop_price ?? o.limit_price;
  const table = (
        <div>
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-[11px] uppercase tracking-wide text-slate-500">
                <th className="py-1 pr-3">Symbol</th><th className="py-1 pr-3">Side</th>
                <th className="py-1 pr-3">Type</th><th className="py-1 pr-3">Qty</th>
                <th className="py-1 pr-3">Price</th><th className="py-1 pr-3">TIF</th>
                <th className="py-1">Status</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.alpaca_order_id ?? o.client_order_id ?? `${o.symbol}-${o.submitted_at}`} className="border-t border-slate-800 text-slate-200">
                  <td className="py-1.5 pr-3 font-medium text-white">{o.symbol}</td>
                  <td className="py-1.5 pr-3">{o.side}</td>
                  <td className="py-1.5 pr-3">{o.type}</td>
                  <td className="py-1.5 pr-3 tabular-nums">{o.filled_qty ? `${o.filled_qty}/` : ""}{o.qty}</td>
                  <td className="py-1.5 pr-3 tabular-nums">{price(o) != null ? `$${price(o)!.toFixed(2)}` : "—"}</td>
                  <td className="py-1.5 pr-3">{o.time_in_force}</td>
                  <td className="py-1.5">{o.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
  );
  return (
    <Box title={`Staged orders · ${orders.length}`} full={orders.length > 3 ? table : undefined}>
      {orders.length === 0 ? (
        <p className="text-xs text-slate-500">Nothing resting right now.</p>
      ) : (
        <ul className="space-y-0.5 text-xs tabular-nums text-slate-300">
          {orders.slice(0, 3).map((o) => (
            <li key={o.alpaca_order_id ?? o.client_order_id ?? `${o.symbol}-${o.submitted_at}`} className="flex justify-between gap-2">
              <span><span className="font-semibold text-white">{o.symbol}</span> {o.side} {o.type} {o.qty}</span>
              <span className="text-slate-500">{price(o) != null ? `$${price(o)!.toFixed(2)} · ` : ""}{o.time_in_force}</span>
            </li>
          ))}
        </ul>
      )}
    </Box>
  );
}

const inputCls = "rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-white";
const labelCls = "flex flex-col gap-1 text-xs text-slate-400";

type ComboLegState = { symbol: string; side: string; qty: string; intent: string };

const OCC_INPUT = /^[A-Z]{1,6}\d{6}[CP]\d{8}$/;

function cleanOcc(raw: string): string {
  return raw.trim().toUpperCase().replace(/\s+/g, "");
}

function intentFor(side: string, intent: string): string {
  return `${side}_to_${intent}`;
}

const kindBtnCls = (active: boolean) =>
  `rounded-md px-3 py-1.5 text-sm font-semibold ${active
    ? "bg-slate-700 text-white"
    : "border border-slate-700 bg-slate-900 text-slate-400"}`;

function OrderForm({ book }: { book: string }) {
  const [signedIn, setSignedIn] = useState(false);
  const [ideas, setIdeas] = useState<{ id: number; title: string }[]>([]);
  const [symbol, setSymbol] = useState("");
  const [qty, setQty] = useState("1");
  const [side, setSide] = useState("buy");
  const [orderType, setOrderType] = useState("market");
  const [limitPrice, setLimitPrice] = useState("");
  const [tif, setTif] = useState("day");
  const [intent, setIntent] = useState("open");
  const [kind, setKind] = useState("single");
  const [comboLegs, setComboLegs] = useState<ComboLegState[]>([
    { symbol: "", side: "buy", qty: "1", intent: "open" },
    { symbol: "", side: "sell", qty: "1", intent: "open" },
  ]);
  const [netLimit, setNetLimit] = useState("");
  const [ideaId, setIdeaId] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Signed-in only: /api/admin/me 401s for a visitor, and the form simply never appears.
    adminJson<{ email: string }>("/api/admin/me")
      .then(() => {
        if (cancelled) return;
        setSignedIn(true);
        adminJson<{ id: number; title: string }[]>("/api/workshop/ideas")
          .then((rows) => { if (!cancelled) setIdeas(Array.isArray(rows) ? rows : []); })
          .catch(() => undefined);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!signedIn) return null;

  const cleaned = cleanOcc(symbol);
  const isOcc = OCC_INPUT.test(cleaned);
  const contractText = isOcc ? contractLabel(cleaned) : null;
  const comboReady = comboLegs.every((l) => OCC_INPUT.test(cleanOcc(l.symbol))) && netLimit.trim() !== "";
  const canPlace = kind === "combo" ? comboReady : Boolean(symbol.trim());

  function setLeg(i: number, patch: Partial<ComboLegState>) {
    setComboLegs((legs) => legs.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  }

  async function place() {
    setBusy(true);
    setNote(null);
    setError(null);
    try {
      let body: Record<string, unknown>;
      let summary: string;
      if (kind === "combo") {
        body = {
          legs: comboLegs.map((l) => ({
            symbol: cleanOcc(l.symbol), side: l.side, qty: Number(l.qty),
            position_intent: intentFor(l.side, l.intent),
          })),
          order_type: "limit", limit_price: Number(netLimit), time_in_force: "day",
        };
        summary = `combo of ${comboLegs.length} legs`;
      } else if (isOcc) {
        // An option is a day order with an explicit open/close intent; the API
        // refuses opg/cls on options rather than downgrading them, so the form
        // never offers them for a contract.
        body = {
          symbol: cleaned, qty: Number(qty), side, order_type: orderType, time_in_force: "day",
          position_intent: intentFor(side, intent),
        };
        if (orderType === "limit") body.limit_price = Number(limitPrice);
        summary = `${side} ${qty} ${cleaned}`;
      } else {
        body = {
          symbol: symbol.trim().toUpperCase(), qty: Number(qty), side, order_type: orderType, time_in_force: tif,
        };
        if (orderType === "limit") body.limit_price = Number(limitPrice);
        summary = `${side} ${qty} ${body.symbol as string}`;
      }
      if (ideaId) body.idea_id = Number(ideaId);
      body.book = book;
      const placed = await adminJson<{ client_order_id: string }>("/api/portfolio/orders", {
        method: "POST", body: JSON.stringify(body),
      });
      setNote(`Order sent: ${summary} (${placed.client_order_id})`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Order failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box title="Place an order by hand" full={(
      <>
      <p className="text-xs text-slate-400">
        Paper account, market or limit. Tag it with an idea and it lands in that idea&apos;s order log.
        Options trade too: paste an OCC contract (e.g. SPY261113P00570000) for a single leg, or build a
        combo. Every short leg must be covered -- the same defined-risk rule the machine API enforces.
      </p>
      <div className="mt-3 flex gap-2" role="group" aria-label="Order kind">
        <button type="button" onClick={() => setKind("single")} className={kindBtnCls(kind === "single")}>Single</button>
        <button type="button" onClick={() => setKind("combo")} className={kindBtnCls(kind === "combo")}>Combo (spread)</button>
      </div>
      {kind === "single" ? (
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className={labelCls}>Symbol
          <input aria-label="Symbol" className={inputCls} value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="XLE" />
        </label>
        <label className={labelCls}>{isOcc ? "Contracts" : "Shares"}
          <input aria-label={isOcc ? "Contracts" : "Shares"} className={`${inputCls} w-24`} type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} />
        </label>
        <label className={labelCls}>Side
          <select aria-label="Side" className={inputCls} value={side} onChange={(e) => setSide(e.target.value)}>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </label>
        <label className={labelCls}>Type
          <select aria-label="Type" className={inputCls} value={orderType} onChange={(e) => setOrderType(e.target.value)}>
            <option value="market">Market</option>
            <option value="limit">Limit</option>
          </select>
        </label>
        {orderType === "limit" && (
          <label className={labelCls}>Limit price
            <input aria-label="Limit price" className={`${inputCls} w-28`} type="number" min={0} step="0.01" value={limitPrice} onChange={(e) => setLimitPrice(e.target.value)} />
          </label>
        )}
        <label className={labelCls}>Time in force
          <select aria-label="Time in force" className={inputCls} value={isOcc ? "day" : tif} onChange={(e) => setTif(e.target.value)}>
            <option value="day">Day</option>
            {!isOcc && <option value="opg">At the open (expires if it misses)</option>}
            {!isOcc && <option value="cls">At the close</option>}
          </select>
        </label>
        {isOcc && (
          <label className={labelCls}>Intent
            <select aria-label="Intent" className={inputCls} value={intent} onChange={(e) => setIntent(e.target.value)}>
              <option value="open">Open a position</option>
              <option value="close">Close a position</option>
            </select>
          </label>
        )}
        <label className={labelCls}>Idea (optional)
          <select aria-label="Idea" className={inputCls} value={ideaId} onChange={(e) => setIdeaId(e.target.value)}>
            <option value="">No idea</option>
            {ideas.map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}
          </select>
        </label>
        <button type="button" disabled={busy || !canPlace} onClick={place}
          className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-40">
          {busy ? "Sending…" : "Place order"}
        </button>
      </div>
      ) : (
      <div className="mt-3 flex flex-col gap-2">
        {comboLegs.map((leg, i) => (
          <div key={i} className="flex flex-wrap items-end gap-3">
            <label className={labelCls}>Leg {i + 1} contract
              <input aria-label={`Leg ${i + 1} symbol`} className={inputCls} value={leg.symbol}
                onChange={(e) => setLeg(i, { symbol: e.target.value })} placeholder="SPY261113P00570000" />
            </label>
            <label className={labelCls}>Side
              <select aria-label={`Leg ${i + 1} side`} className={inputCls} value={leg.side}
                onChange={(e) => setLeg(i, { side: e.target.value })}>
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
              </select>
            </label>
            <label className={labelCls}>Contracts
              <input aria-label={`Leg ${i + 1} qty`} className={`${inputCls} w-24`} type="number" min={1} value={leg.qty}
                onChange={(e) => setLeg(i, { qty: e.target.value })} />
            </label>
            <label className={labelCls}>Intent
              <select aria-label={`Leg ${i + 1} intent`} className={inputCls} value={leg.intent}
                onChange={(e) => setLeg(i, { intent: e.target.value })}>
                <option value="open">Open</option>
                <option value="close">Close</option>
              </select>
            </label>
            {comboLegs.length > 2 && (
              <button type="button" onClick={() => setComboLegs(comboLegs.filter((_, j) => j !== i))}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300">
                Remove leg
              </button>
            )}
          </div>
        ))}
        <div className="flex flex-wrap items-end gap-3">
          {comboLegs.length < 4 && (
            <button type="button"
              onClick={() => setComboLegs([...comboLegs, { symbol: "", side: "buy", qty: "1", intent: "open" }])}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300">
              Add leg
            </button>
          )}
          <label className={labelCls}>Net limit price (debit + / credit −)
            <input aria-label="Net limit price" className={`${inputCls} w-28`} type="number" step="0.01" value={netLimit}
              onChange={(e) => setNetLimit(e.target.value)} />
          </label>
          <label className={labelCls}>Idea (optional)
            <select aria-label="Idea" className={inputCls} value={ideaId} onChange={(e) => setIdeaId(e.target.value)}>
              <option value="">No idea</option>
              {ideas.map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}
            </select>
          </label>
          <button type="button" disabled={busy || !canPlace} onClick={place}
            className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-40">
            {busy ? "Sending…" : "Place order"}
          </button>
        </div>
        <p className="text-xs text-slate-400">
          One order, one net price for the whole package, day only. Quantities are absolute:
          buy 6 / sell 3 places a 3-lot at ratios 2/1.
        </p>
      </div>
      )}
      {contractText && kind === "single" && <p className="mt-2 text-xs text-slate-300">{contractText}</p>}
      {note && <p className="mt-3 text-sm text-emerald-300">{note}</p>}
      {error && <p className="mt-3 text-sm text-rose-300">{error}</p>}
      </>
    )}>
      <p className="text-xs text-slate-400">Paper account, market or limit, tagged to an idea if you like. Open it to place one.</p>
    </Box>
  );
}
