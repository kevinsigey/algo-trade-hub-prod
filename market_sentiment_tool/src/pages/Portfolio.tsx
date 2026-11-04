import { Link, useSearchParams } from "react-router-dom";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { adminJson } from "@/lib/workshop";
import { ArrowDown, ArrowRight, ArrowUp, Loader2, TriangleAlert } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import CompositionBox from "@/components/CompositionMap";
import { ctDateTime } from "@/lib/format";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  breakerLabel,
  concentration,
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
  type PortfolioPayload,
  type PositionRow,
} from "@/lib/paperPortfolio";

function Box({ title, right, children, className = "" }: {
  title: string; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-xl border border-slate-800 bg-slate-900/60 p-4 ${className}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
        {right}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function RailRow({ label, value, className = "text-slate-100" }: { label: string; value: string; className?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className={`tabular-nums font-medium ${className}`}>{value}</span>
    </div>
  );
}

const money = (v: number | null | undefined) => fmtUsd(v, { whole: true });
const signed = (v: number | null | undefined) => fmtUsd(v, { signed: true, whole: true });
const price = (v: number | null | undefined) => fmtUsd(v);

type SortKey = "symbol" | "last" | "change" | "avg" | "cost" | "value" | "weight" | "day" | "unrealized";

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
      const order = typeof x === "string" ? x.localeCompare(String(y)) : Math.abs(x) - Math.abs(Number(y));
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

function AccountRail({ data, liveIdeas }: {
  data: PortfolioPayload;
  liveIdeas: { id: number; title: string; size_pct: number | null }[];
}) {
  const s = data.scoreboard;
  const a = data.account;
  const cashRow = data.positions.find((p) => p.symbol === "Cash");
  const investedPct = cashRow?.pct_of_book == null ? null : 100 - cashRow.pct_of_book;
  const rows = data.positions.filter((p) => p.symbol !== "Cash");
  const unrealized = rows.some((p) => p.unrealized_pl != null) ? rows.reduce((sum, p) => sum + (p.unrealized_pl ?? 0), 0) : null;
  return (
    <aside className="self-start rounded-xl border border-slate-800 bg-slate-900/60 p-4 xl:sticky xl:top-4">
      <div className="text-sm text-slate-400">Net liquidation value</div>
      <div className="mt-0.5 text-3xl font-semibold tabular-nums tracking-tight text-white">{money(s.equity)}</div>
      <div className={`mt-1 text-sm font-medium tabular-nums ${tone(a?.day_pl)}`}>
        {a?.day_pl == null ? "Day P&L unknown" : `${signed(a.day_pl)} (${fmtPct(a.day_pl_pct)}) today`}
      </div>
      <p className={`mt-2 text-xs ${data.state === "live" ? "text-emerald-300" : "text-amber-300"}`}>
        {stateLabel(data.state, data.as_of)}
      </p>
      <div className="mt-3 border-t border-slate-800 pt-2">
        <RailRow label="Cash" value={money(a?.cash ?? cashRow?.market_value)} />
        <RailRow label="Buying power" value={money(a?.buying_power)} />
        <RailRow label="Invested" value={investedPct == null ? "—" : `${investedPct.toFixed(0)}%`} />
        <RailRow label="Long value" value={money(a?.long_value)} />
        <RailRow label="Short value" value={money(a?.short_value)} />
      </div>
      <div className="mt-2 border-t border-slate-800 pt-2">
        <RailRow label="Unrealized P&L" value={signed(unrealized)} className={tone(unrealized)} />
        <RailRow label="Realized P&L" value={signed(a?.realized_pl)} className={tone(a?.realized_pl)} />
        <RailRow label="Maintenance margin" value={money(a?.maintenance_margin)} />
        <RailRow label="Positions" value={String(rows.length)} />
        {data.breaker && (
          <RailRow label="Circuit breaker" value={breakerLabel(data.breaker)}
                   className={data.breaker.tripped ? "text-rose-400" : "text-slate-100"} />
        )}
      </div>
      <div className="mt-2 border-t border-slate-800 pt-2">
        <RailRow label="Since start" value={fmtPct(s.return_pct)} className={tone(s.return_pct)} />
        <RailRow label="SPY same period" value={fmtPct(s.spy_return_pct)} />
        <RailRow label="Ahead of SPY" value={fmtPts(s.ahead_pts)} className={tone(s.ahead_pts)} />
      </div>
      {liveIdeas.length > 0 && (
        <div className="mt-2 border-t border-slate-800 pt-2">
          <div className="flex items-baseline justify-between py-1 text-sm">
            <span className="text-slate-400">Ideas trading here</span>
            <Link to="/workshop" className="text-xs text-emerald-300 hover:text-emerald-200">Workshop</Link>
          </div>
          <ul>
            {liveIdeas.map((idea) => (
              <li key={idea.id} className="flex items-baseline justify-between gap-3 py-0.5 text-xs">
                <Link to={`/workshop/${idea.id}`} className="truncate text-slate-200 hover:text-emerald-300" title={idea.title}>{idea.title}</Link>
                <span className="shrink-0 tabular-nums text-slate-400">{idea.size_pct ?? "—"}%</span>
              </li>
            ))}
          </ul>
        </div>
      )}
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
    { label: "Sharpe", value: s.sharpe == null ? "—" : s.sharpe.toFixed(2) },
    { label: "Win rate", value: s.win_rate == null ? "—" : `${s.win_rate.toFixed(0)}%` },
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
        <div className="h-56" aria-label={`Portfolio vs SPY, ${range}`}>
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
      <dl className="mt-3 grid grid-cols-3 gap-x-4 gap-y-2 border-t border-slate-800 pt-3 sm:grid-cols-6">
        {stats.map((st) => (
          <div key={st.label}>
            <dt className="text-xs text-slate-400">{st.label}</dt>
            <dd className={`mt-0.5 text-base font-semibold tabular-nums ${st.className ?? "text-white"}`}>{st.value}</dd>
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
  return (
    <div className="mt-4 grid gap-3 xl:grid-cols-[19rem_minmax(0,1fr)]">
      <AccountRail data={data} liveIdeas={liveIdeas} />
      <div className="grid min-w-0 content-start gap-3 2xl:grid-cols-3">
        {data.breaker?.tripped && (
          <p role="alert" className="flex items-start gap-2 rounded-lg border border-rose-500/50 px-3 py-2 text-sm text-rose-200 2xl:col-span-3">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            Circuit breaker tripped: {data.breaker.reasons.join("; ")}. New opening orders are refused; closing and protective orders still pass.
          </p>
        )}
        {heavy.map((h) => (
          <p key={h.sector} className="flex items-start gap-2 rounded-lg border border-amber-500/40 px-3 py-2 text-sm text-amber-200 2xl:col-span-3">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            {h.sector} is {h.pct.toFixed(0)}% of what&apos;s invested. These positions tend to move together.
          </p>
        ))}
        <div className="min-w-0 2xl:col-span-2"><Performance data={data} /></div>
        <CompositionBox positions={data.positions} composition={data.composition} />
        <Box title={`Positions · ${rows.length}`} className="2xl:col-span-3">
          <PositionsTable rows={rows} />
        </Box>
        <div className="min-w-0 2xl:col-span-2"><OrdersBox book={book} /></div>
        <div className="flex min-w-0 flex-col gap-3">
          <RecentTrades book={book} />
          <StagedOrders book={book} />
        </div>
        <OrderForm book={book} />
      </div>
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  filled: "text-emerald-400", expired: "text-rose-400", rejected: "text-rose-400", canceled: "text-slate-400",
};

/** What the broker did with recent orders: an order the hub sent can still expire unfilled. */
function OrdersBox({ book }: { book: string }) {
  const { data } = useApi<ActivityPayload>(`/api/portfolio/activity?book=${book}`);
  const recent: ActivityOrder[] = Array.isArray(data?.recent) ? data.recent.slice(0, 14) : [];
  return (
    <Box title="Recent orders"
         right={(
           <Link to={`/portfolio/closed?book=${book}`} className="inline-flex items-center gap-1 text-xs text-emerald-300 hover:text-emerald-200">
             All orders and trades <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
           </Link>
         )}>
      {recent.length === 0 ? (
        <p className="text-sm text-slate-400">No orders yet.</p>
      ) : (
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
              {recent.map((o, i) => (
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
  const recent = [...data.trades].slice(-6).reverse();
  return (
    <Box title="Recent closed trades"
         right={<span className={`text-xs tabular-nums ${tone(total)}`}>{data.trades.length} closed · {fmtUsd(total, { signed: true })}</span>}>
      {recent.length === 0 ? (
        <p className="text-xs text-slate-400">No closed trades yet.</p>
      ) : (
        <ul className="space-y-1">
          {recent.map((t, i) => (
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
  return (
    <Box title="Staged orders">
      {orders.length === 0 ? (
        <p className="text-xs text-slate-500">Nothing resting right now.</p>
      ) : (
        <div className="max-h-56 overflow-auto">
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
      )}
    </Box>
  );
}

const inputCls = "rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-white";
const labelCls = "flex flex-col gap-1 text-xs text-slate-400";

function OrderForm({ book }: { book: string }) {
  const [signedIn, setSignedIn] = useState(false);
  const [ideas, setIdeas] = useState<{ id: number; title: string }[]>([]);
  const [symbol, setSymbol] = useState("");
  const [qty, setQty] = useState("1");
  const [side, setSide] = useState("buy");
  const [orderType, setOrderType] = useState("market");
  const [limitPrice, setLimitPrice] = useState("");
  const [tif, setTif] = useState("day");
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

  async function place() {
    setBusy(true);
    setNote(null);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        symbol: symbol.trim().toUpperCase(), qty: Number(qty), side, order_type: orderType, time_in_force: tif,
      };
      if (orderType === "limit") body.limit_price = Number(limitPrice);
      if (ideaId) body.idea_id = Number(ideaId);
      body.book = book;
      const placed = await adminJson<{ client_order_id: string }>("/api/portfolio/orders", {
        method: "POST", body: JSON.stringify(body),
      });
      setNote(`Order sent: ${side} ${qty} ${body.symbol as string} (${placed.client_order_id})`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Order failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box title="Place an order by hand" className="2xl:col-span-3">
      <p className="text-xs text-slate-400">
        Paper account, market or limit. Tag it with an idea and it lands in that idea&apos;s order log.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className={labelCls}>Symbol
          <input aria-label="Symbol" className={inputCls} value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="XLE" />
        </label>
        <label className={labelCls}>Shares
          <input aria-label="Shares" className={`${inputCls} w-24`} type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} />
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
          <select aria-label="Time in force" className={inputCls} value={tif} onChange={(e) => setTif(e.target.value)}>
            <option value="day">Day</option>
            <option value="opg">At the open (expires if it misses)</option>
            <option value="cls">At the close</option>
          </select>
        </label>
        <label className={labelCls}>Idea (optional)
          <select aria-label="Idea" className={inputCls} value={ideaId} onChange={(e) => setIdeaId(e.target.value)}>
            <option value="">No idea</option>
            {ideas.map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}
          </select>
        </label>
        <button type="button" disabled={busy || !symbol.trim()} onClick={place}
          className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-40">
          {busy ? "Sending…" : "Place order"}
        </button>
      </div>
      {note && <p className="mt-3 text-sm text-emerald-300">{note}</p>}
      {error && <p className="mt-3 text-sm text-rose-300">{error}</p>}
    </Box>
  );
}
