import { Link, useSearchParams } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";

import { adminJson } from "@/lib/workshop";
import { ArrowRight, Loader2 } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import CompositionBox from "@/components/CompositionMap";
import StrategyHqStrip from "@/components/StrategyHqStrip";
import { ctDateTime } from "@/lib/format";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  fmtPct,
  fmtPts,
  fmtUsd,
  stateLabel,
  tone,
  type BookHeadline,
  type ManualAction,
  type BooksPayload,
  type ClosedPayload,
  type PortfolioPayload,
  type PositionRow,
} from "@/lib/paperPortfolio";

/** One IBKR-style box (Kevin, 2026-11-02): the whole portfolio on one screen
 * as dense boxes instead of divided sections -- more information, more
 * visuals, no scrolling through stacked sections to find a number. */
function Box({ title, right, children, className = "" }: {
  title: string; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-xl border border-slate-800 bg-slate-900/60 p-4 ${className}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h2>
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

function PositionsTable({ rows }: { rows: PositionRow[] }) {
  return (
    <div className="max-h-[27rem] overflow-auto">
      <table className="w-full min-w-[34rem] text-sm tabular-nums">
        <thead className="text-left text-slate-400">
          <tr>
            <th className="py-1.5 pr-4 font-medium">Holding</th>
            <th className="py-1.5 pr-4 text-right font-medium">Shares</th>
            <th className="py-1.5 pr-4 text-right font-medium">Value</th>
            <th className="py-1.5 pr-4 text-right font-medium">% of book</th>
            <th className="py-1.5 pr-4 text-right font-medium">P&amp;L</th>
            <th className="py-1.5 font-medium">From idea</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.symbol}-${r.idea ?? ""}`} className="border-t border-slate-800/80">
              <td className="py-1.5 pr-4 font-semibold text-white">
                {r.symbol}
                {r.side === "short" && <span className="ml-1.5 text-xs font-normal text-slate-400">short</span>}
              </td>
              <td className="py-1.5 pr-4 text-right text-slate-300">{r.qty ?? ""}</td>
              <td className="py-1.5 pr-4 text-right text-slate-200">{fmtUsd(r.market_value, { whole: true })}</td>
              <td className="py-1.5 pr-4 text-right text-slate-300">{r.pct_of_book == null ? "—" : `${r.pct_of_book.toFixed(0)}%`}</td>
              <td className={`py-1.5 pr-4 text-right ${tone(r.unrealized_pl)}`}>
                {r.unrealized_pl == null ? "" : fmtUsd(r.unrealized_pl, { signed: true })}
              </td>
              <td className="py-1.5 text-slate-300">{r.idea ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The books' short names for the switcher and links (the labels themselves
 * come from the books payload; these are only for the two known books). */
const BOOK_SHORT: Record<string, string> = { main: "Main book", big: "$1M book" };

/** Master view cards (Kevin, 2026-11-02): one headline card per book -- state,
 * equity, return, positions, live ideas -- and a click opens that book's own
 * page. A book that isn't connected says so plainly instead of showing zeros. */
function BookCards() {
  const { data } = useApi<BooksPayload>("/api/portfolio/books");
  const books = Array.isArray(data?.books) ? data.books : [];
  if (books.length === 0) return null;
  return (
    <div className="mt-4 grid gap-3 md:grid-cols-2">
      {books.map((b: BookHeadline) => (
        <Link key={b.book} to={`/portfolio?book=${b.book}`}
          className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 transition-colors hover:border-slate-600">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-base font-semibold text-white">{b.label}</span>
            <span className="text-xs text-slate-500">{b.detail}{b.account_number ? ` · ${b.account_number}` : ""}</span>
          </div>
          {b.state === "not_connected" ? (
            <p className="mt-3 text-sm text-slate-400">Paper account not connected — no numbers yet.</p>
          ) : (
            <>
              <div className="mt-3 flex flex-wrap items-baseline gap-x-5 gap-y-1">
                <span className="text-3xl font-semibold tabular-nums tracking-tight text-white">{fmtUsd(b.equity, { whole: true })}</span>
                <span className={`text-lg font-semibold tabular-nums ${tone(b.return_pct)}`}>{fmtPct(b.return_pct)}</span>
                <span className="text-sm text-slate-400">{b.positions} positions · {b.live_ideas} live {b.live_ideas === 1 ? "idea" : "ideas"}</span>
              </div>
              <p className={`mt-2 text-xs ${b.state === "live" ? "text-emerald-300" : "text-amber-300"}`}>{stateLabel(b.state, b.as_of)}</p>
            </>
          )}
        </Link>
      ))}
    </div>
  );
}

/** The way back and across on a single book's page: Master (both books) or the other book. */
function BookSwitcher({ book }: { book: string }) {
  const item = (to: string, label: string, active: boolean) => (
    <Link key={to} to={to} aria-current={active ? "page" : undefined}
      className={`rounded-lg border px-3 py-1.5 text-sm ${active ? "border-emerald-500/40 bg-emerald-500/10 font-semibold text-emerald-300" : "border-slate-700 text-slate-300 hover:bg-slate-900"}`}>
      {label}
    </Link>
  );
  return (
    <nav aria-label="Paper books" className="mt-4 flex flex-wrap items-center gap-2">
      {item("/portfolio", "Master — both books", false)}
      {item("/portfolio?book=main", BOOK_SHORT.main, book === "main")}
      {item("/portfolio?book=big", BOOK_SHORT.big, book === "big")}
    </nav>
  );
}

export default function Portfolio() {
  const [searchParams] = useSearchParams();
  const param = searchParams.get("book");
  const book = param === "main" || param === "big" ? param : null;
  const { data, error, loading } = useApi<PortfolioPayload>(book ? `/api/portfolio?book=${book}` : "/api/portfolio");
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
    <div className="mx-auto max-w-[92rem] px-4 py-6 md:px-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight text-white">Portfolio</h1>
        <p className="text-sm text-slate-400">
          {book ? `${BOOK_SHORT[book]} in full, on one screen. Are we beating SPY?` : "Two paper accounts, in full, on one screen. Are we beating SPY?"}
        </p>
      </div>

      <StrategyHqStrip />

      {book ? <BookSwitcher book={book} /> : <BookCards />}

      {data && data.state !== "not_connected" && (
        <div className="mt-4"><ManualActions book={book ?? "main"} /></div>
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

function Body({ data, liveIdeas, book }: {
  data: PortfolioPayload;
  liveIdeas: { id: number; title: string; size_pct: number | null }[];
  /** The book this page is scoped to; null on the master view (which shows the main book below the cards). */
  book: string | null;
}) {
  const s = data.scoreboard;
  const cashRow = data.positions.find((p) => p.symbol === "Cash");
  const investedPct = cashRow?.pct_of_book == null ? null : 100 - cashRow.pct_of_book;
  const unrealized = data.positions.reduce((sum, p) => sum + (p.unrealized_pl ?? 0), 0);
  const anyPl = data.positions.some((p) => p.unrealized_pl != null);
  const count = data.positions.filter((p) => p.symbol !== "Cash").length;
  const stats: { label: string; value: string; className?: string }[] = [
    { label: "Since start", value: fmtPct(s.return_pct), className: tone(s.return_pct) },
    { label: "SPY same period", value: fmtPct(s.spy_return_pct) },
    { label: "Ahead of SPY", value: fmtPts(s.ahead_pts), className: tone(s.ahead_pts) },
    { label: "Max drawdown", value: fmtPct(s.max_drawdown_pct) },
    { label: "Sharpe", value: s.sharpe == null ? "—" : s.sharpe.toFixed(2) },
    { label: "Win rate", value: s.win_rate == null ? "—" : `${s.win_rate.toFixed(0)}%` },
  ];

  return (
    <div className="mt-4 grid gap-3 xl:grid-cols-12">
      <Box title="Account" className="xl:col-span-3"
           right={data.account_number ? <span className="text-xs text-slate-500">{data.account_number}</span> : undefined}>
        <div className="text-3xl font-semibold tabular-nums tracking-tight text-white">{fmtUsd(s.equity, { whole: true })}</div>
        <div className="mt-2 divide-y divide-slate-800/70">
          <RailRow label="Cash" value={cashRow ? fmtUsd(cashRow.market_value, { whole: true }) : "—"} />
          <RailRow label="Invested" value={investedPct == null ? "—" : `${investedPct.toFixed(0)}%`} />
          <RailRow label="Unrealized P&L" value={anyPl ? fmtUsd(unrealized, { signed: true }) : "—"} className={tone(unrealized)} />
          <RailRow label="Positions" value={String(count)} />
        </div>
        <p className={`mt-3 text-xs ${data.state === "live" ? "text-emerald-300" : "text-amber-300"}`}>
          {stateLabel(data.state, data.as_of)}
        </p>
      </Box>

      <Box title="Performance — portfolio vs SPY" className="xl:col-span-6">
        {data.curve.length > 1 ? (
          <div className="h-44" aria-label="Portfolio vs SPY since start">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.curve} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="t" hide />
                <YAxis tickFormatter={(v: number) => `${v.toFixed(0)}%`} stroke="#64748b" fontSize={11} width={40} />
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
          <p className="text-sm text-slate-400">The curve starts after the second snapshot.</p>
        )}
        <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
          {stats.map((st) => (
            <div key={st.label} className="rounded-lg border border-slate-800 px-2.5 py-2">
              <div className="text-[11px] leading-tight text-slate-400">{st.label}</div>
              <div className={`mt-0.5 text-base font-semibold tabular-nums ${st.className ?? "text-white"}`}>{st.value}</div>
            </div>
          ))}
        </div>
      </Box>

      <CompositionBox positions={data.positions} composition={data.composition} className="xl:col-span-3" />

      <Box title={`Every position · ${count}`} className="xl:col-span-8"
           right={(
             <Link to={book ? `/portfolio/closed?book=${book}` : "/portfolio/closed"} className="inline-flex items-center gap-1 text-xs text-emerald-300 hover:text-emerald-200">
               Trades and Orders <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
             </Link>
           )}>
        <PositionsTable rows={data.positions} />
      </Box>

      <div className="flex flex-col gap-3 xl:col-span-4">
        {liveIdeas.length > 0 && (
          <Box title="Ideas trading on this account"
               right={<Link to="/workshop" className="text-xs text-emerald-300 hover:text-emerald-200">Workshop →</Link>}>
            <ul className="space-y-1">
              {liveIdeas.map((idea) => (
                <li key={idea.id} className="flex items-baseline justify-between gap-3 rounded-md border border-slate-800 px-2.5 py-1.5 text-xs">
                  <Link to={`/workshop/${idea.id}`} className="text-slate-200 hover:text-emerald-300">{idea.title}</Link>
                  <span className="tabular-nums text-slate-400">{idea.size_pct ?? "—"}%</span>
                </li>
              ))}
            </ul>
          </Box>
        )}
        <RecentTrades book={book} />
        {/* Staged orders and the hand order form read and place on the main
            book only (their endpoints carry no book), so the $1M page omits them. */}
        <StagedOrders book={book ?? "main"} />
      </div>

      <OrderForm book={book ?? "main"} />
    </div>
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
          .then((rows) => { if (!cancelled) setIdeas(rows); })
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
    <Box title="Place an order by hand" className="xl:col-span-12">
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
            <option value="opg">At the open</option>
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
