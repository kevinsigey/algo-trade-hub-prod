import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowRight, ArrowUp } from "lucide-react";

import { adminJson, ApiError } from "@/lib/workshop";
import { ctDateTime } from "@/lib/format";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  contractLabel,
  fmtPct,
  fmtUsd,
  orderDetailLabel,
  orderLabel,
  type ActivityOrder,
  type ActivityPayload,
  type ClosedPayload,
  type ManualAction,
} from "@/lib/paperPortfolio";
import { Box, money, pollWhileVisible, price, REFRESH_MS } from "./shared";

/** Tab 3: Trade (2026-11-12 redesign). Manual actions at the top, the
 * order ticket open on the page (Single and Combo tabs inside it), then
 * staged orders, recent orders and closed trades as full lists --
 * nothing opens in a pop-up. */

export default function TradeTab({ book }: { book: string }) {
  return (
    <div className="space-y-2">
      <ManualActions book={book} />
      <OrderForm book={book} />
      <StagedOrders book={book} />
      <OrdersBox book={book} />
      <ClosedTradesBox book={book} />
    </div>
  );
}

/** Sortable table headers for the Trade lists, the BookTab pattern
 * (Claude's #514 review): click to sort, click again to reverse; unknown
 * values stay last in both directions. */
type SortState<K extends string> = { key: K; desc: boolean };

function compareVals(x: number | string | null | undefined, y: number | string | null | undefined): number {
  if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
  return typeof x === "string" ? x.localeCompare(String(y)) : Number(x) - Number(y);
}

function sortRows<T, K extends string>(rows: T[], sort: SortState<K> | null,
                                       read: (row: T, key: K) => number | string | null | undefined): T[] {
  if (!sort) return rows;
  return [...rows].sort((a, b) => {
    const x = read(a, sort.key), y = read(b, sort.key);
    const base = compareVals(x, y);
    // compareVals places nulls last; flip only a real value comparison.
    return sort.desc && x != null && y != null ? -base : base;
  });
}

function SortHead<K extends string>({ label, sortKey, sort, onSort, align = "left" }: {
  label: string; sortKey: K; sort: SortState<K> | null;
  onSort: (key: K) => void; align?: "left" | "right";
}) {
  const active = sort?.key === sortKey;
  return (
    <th scope="col" aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
        className={`py-1 pr-3 font-medium ${align === "right" ? "text-right" : ""}`}>
      <button type="button" onClick={() => onSort(sortKey)}
              className="inline-flex items-center gap-0.5 rounded hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
        {label}
        {active && (sort.desc ? <ArrowDown className="h-3 w-3" aria-hidden="true" /> : <ArrowUp className="h-3 w-3" aria-hidden="true" />)}
      </button>
    </th>
  );
}

function nextSort<K extends string>(sort: SortState<K> | null, key: K): SortState<K> {
  return { key, desc: sort?.key === key ? !sort.desc : true };
}

/** Every closed trade on this book, newest exit first — the full list the
 * spec puts under the ticket (the Performance tab carries the same list
 * with its range stats; here it is the complete record). */
type ClosedSortKey = "exited_at" | "symbol" | "idea" | "qty" | "entry" | "exit" | "return" | "pnl";
const CLOSED_READERS: Record<ClosedSortKey, (t: ClosedPayload["trades"][number]) => number | string | null> = {
  exited_at: (t) => t.exited_at, symbol: (t) => t.symbol, idea: (t) => t.idea,
  qty: (t) => t.qty, entry: (t) => t.entry_price, exit: (t) => t.exit_price,
  return: (t) => t.return_pct, pnl: (t) => t.pnl,
};

function ClosedTradesBox({ book }: { book: string }) {
  const { data, loading } = useApi<ClosedPayload>(`/api/portfolio/closed?book=${book}`, REFRESH_MS);
  const [sort, setSort] = useState<SortState<ClosedSortKey> | null>({ key: "exited_at", desc: true });
  const trades = useMemo(
    () => sortRows(Array.isArray(data?.trades) ? data.trades : [], sort, (t, k) => CLOSED_READERS[k](t)),
    [data, sort]);
  const total = trades.reduce((a, t) => a + t.pnl, 0);
  const head = (key: ClosedSortKey, label: string, align: "left" | "right" = "left") => (
    <SortHead label={label} sortKey={key} sort={sort} align={align}
              onSort={(k) => setSort((s) => nextSort(s, k))} />
  );
  return (
    <Box title={`Closed trades · ${trades.length}`}
         right={trades.length > 0
           ? <span className="text-xs tabular-nums text-slate-400">Total {fmtUsd(total, { signed: true })}</span>
           : undefined}>
      {loading && trades.length === 0 ? (
        <p className="text-sm text-slate-400">Reading closed trades…</p>
      ) : trades.length === 0 ? (
        <p className="text-sm text-slate-400">No closed trades yet.</p>
      ) : (
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[42rem] text-left text-xs tabular-nums">
            <thead className="text-slate-400">
              <tr>
                {head("exited_at", "Exit")}
                {head("symbol", "Symbol")}
                {head("idea", "Idea")}
                {head("qty", "Qty", "right")}
                {head("entry", "Entry", "right")}
                {head("exit", "Exit price", "right")}
                {head("return", "Return", "right")}
                {head("pnl", "P&L", "right")}
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={`${t.symbol}-${t.exited_at}-${i}`} className="border-t border-slate-800/80 text-slate-200">
                  <td className="whitespace-nowrap py-1.5 pr-3 text-slate-400">{ctDateTime(t.exited_at)}</td>
                  <td className="py-1.5 pr-3 font-semibold text-white">{t.symbol}</td>
                  <td className="max-w-[14rem] truncate py-1.5 pr-3 text-slate-400">{t.idea ?? "—"}</td>
                  <td className="py-1.5 pr-3 text-right">{t.qty}</td>
                  <td className="py-1.5 pr-3 text-right">{money(t.entry_price)}</td>
                  <td className="py-1.5 pr-3 text-right">{money(t.exit_price)}</td>
                  <td className="py-1.5 pr-3 text-right">{fmtPct(t.return_pct)}</td>
                  <td className={`py-1.5 text-right font-medium ${t.pnl >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                    {fmtUsd(t.pnl, { signed: true })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Box>
  );
}

/** Needs your hand: the auto-trader's hand-offs for this book (Kevin, 2026-11-02) --
 * option legs it would not price or size alone. Signed-in only, like the order form:
 * a visitor's read 401s and the box simply never appears. Done/Dismiss are Kevin's
 * clicks; the runner never resolves its own hand-offs. */
function ManualActions({ book }: { book: string }) {
  const [actions, setActions] = useState<ManualAction[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let stop: (() => void) | undefined;
    const load = () => {
      adminJson<{ actions: ManualAction[] }>(`/api/portfolio/manual-actions?book=${book}`)
        .then((body) => {
          if (!cancelled) {
            setActions(Array.isArray(body.actions) ? body.actions : []);
            setFailed(false);
          }
        })
        .catch((err) => {
          // A failed read shows as one rather than as an empty queue.
          if (!cancelled && !(err instanceof ApiError && (err.status === 401 || err.status === 403))) {
            setFailed(true);
          }
        });
    };
    // Signed-in only, gated on /api/admin/me like the order form: a
    // visitor must not poll the admin endpoint into a 401 every 30 s
    // (Claude's #514 review).
    adminJson<{ email: string }>("/api/admin/me")
      .then(() => {
        if (cancelled) return;
        load();
        stop = pollWhileVisible(load);
      })
      .catch(() => undefined);
    return () => { cancelled = true; stop?.(); };
  }, [book]);

  if (actions === null) {
    return failed ? (
      <Box title="Needs your hand" className="border-amber-500/40">
        <p className="text-xs text-slate-400">Couldn&apos;t read the hand-off list — it retries on the refresh cycle.</p>
      </Box>
    ) : null;
  }
  if (actions.length === 0) return null;

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
type StagedSortKey = "symbol" | "side" | "type" | "qty" | "price" | "tif" | "status";
const STAGED_READERS: Record<StagedSortKey, (o: OpenOrder) => number | string | null> = {
  symbol: (o) => o.symbol, side: (o) => o.side, type: (o) => o.type, qty: (o) => o.qty,
  price: (o) => o.stop_price ?? o.limit_price, tif: (o) => o.time_in_force, status: (o) => o.status,
};

function StagedOrders({ book }: { book: string }) {
  const [orders, setOrders] = useState<OpenOrder[] | null>(null);
  const [sort, setSort] = useState<SortState<StagedSortKey> | null>(null);
  const sortedOrders = useMemo(
    () => (orders === null ? null : sortRows(orders, sort, (o, k) => STAGED_READERS[k](o))),
    [orders, sort]);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      adminJson<{ email: string }>("/api/admin/me")
        .then(() => adminJson<{ orders: OpenOrder[] }>(`/api/portfolio/open-orders?book=${book}`))
        .then((body) => { if (!cancelled) setOrders(Array.isArray(body.orders) ? body.orders : []); })
        .catch(() => undefined); // a failed refresh keeps the last read
    };
    load();
    const stop = pollWhileVisible(load);
    return () => { cancelled = true; stop(); };
  }, [book]);

  if (orders === null || sortedOrders === null) return null;
  const price = (o: OpenOrder) => o.stop_price ?? o.limit_price;
  const head = (key: StagedSortKey, label: string) => (
    <SortHead label={label} sortKey={key} sort={sort}
              onSort={(k) => setSort((s) => nextSort(s, k))} />
  );
  const table = (
        <div>
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-[11px] uppercase tracking-wide text-slate-500">
                {head("symbol", "Symbol")}{head("side", "Side")}
                {head("type", "Type")}{head("qty", "Qty")}
                {head("price", "Price")}{head("tif", "TIF")}
                {head("status", "Status")}
              </tr>
            </thead>
            <tbody>
              {sortedOrders.map((o) => (
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
    <Box title={`Staged orders · ${orders.length}`}>
      {orders.length === 0 ? (
        <p className="text-xs text-slate-500">Nothing resting right now.</p>
      ) : table}
    </Box>
  );
}

const STATUS_TONE: Record<string, string> = {
  filled: "text-emerald-400", expired: "text-rose-400", rejected: "text-rose-400", canceled: "text-slate-400",
};
type RecentSortKey = "sent" | "order" | "filled" | "avg" | "status" | "from";
const RECENT_READERS: Record<RecentSortKey, (o: ActivityOrder) => number | string | null> = {
  sent: (o) => o.submitted_at, order: (o) => o.symbol, filled: (o) => o.filled_qty,
  avg: (o) => o.filled_avg_price, status: (o) => o.status, from: (o) => o.source,
};

/** What the broker did with recent orders: an order the hub sent can still expire unfilled. */
function OrdersBox({ book }: { book: string }) {
  const { data, loading } = useApi<ActivityPayload>(`/api/portfolio/activity?book=${book}`, REFRESH_MS);
  // On a broker-read failure the endpoint answers 200 with state "stale"
  // and an empty list; that must not blank orders already on screen.
  const [lastGood, setLastGood] = useState<ActivityOrder[]>([]);
  const [sort, setSort] = useState<SortState<RecentSortKey> | null>(null);
  useEffect(() => {
    if (data && data.state !== "stale" && Array.isArray(data.recent)) setLastGood(data.recent);
  }, [data]);
  const staleNow = data?.state === "stale";
  const raw: ActivityOrder[] = staleNow ? lastGood : (Array.isArray(data?.recent) ? data.recent : []);
  const all = useMemo(() => sortRows(raw, sort, (o, k) => RECENT_READERS[k](o)), [raw, sort]);
  const head = (key: RecentSortKey, label: string, align: "left" | "right" = "left") => (
    <SortHead label={label} sortKey={key} sort={sort} align={align}
              onSort={(k) => setSort((s) => nextSort(s, k))} />
  );
  const table = (list: ActivityOrder[]) => (
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[38rem] text-left text-xs tabular-nums">
            <thead className="text-slate-400">
              <tr>
                {head("sent", "Sent")}
                {head("order", "Order")}
                {head("filled", "Filled", "right")}
                {head("avg", "Avg price", "right")}
                {head("status", "Status")}
                {head("from", "From")}
              </tr>
            </thead>
            <tbody>
              {list.map((o, i) => (
                <tr key={`${o.symbol}-${o.submitted_at}-${i}`} className="border-t border-slate-800/80 text-slate-200">
                  <td className="whitespace-nowrap py-1.5 pr-3 text-slate-400">{o.submitted_at ? ctDateTime(o.submitted_at) : "—"}</td>
                  <td className="whitespace-nowrap py-1.5 pr-3">{o.legs && o.legs.length > 0
                    ? <span className="font-semibold text-white">{orderDetailLabel(o)}</span>
                    : <>{o.side} <span className="font-semibold text-white">{orderLabel(o)}</span></>} <span className="text-slate-400">{o.type} · {o.time_in_force}</span></td>
                  <td className="py-1.5 pr-3 text-right">{o.filled_qty ?? "—"}/{o.qty ?? "—"}</td>
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
    <Box title="Recent orders"
         right={(
           <span className="inline-flex items-center gap-2">
             {staleNow && all.length > 0 && <span className="text-xs text-amber-300">stale — broker read failed</span>}
             <Link to={`/portfolio/closed?book=${book}`} aria-label="All orders and trades" className="inline-flex items-center gap-1 text-xs text-emerald-300 hover:text-emerald-200">
               All <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
             </Link>
           </span>
         )}>
      {loading && all.length === 0 ? (
        <p className="text-sm text-slate-400">Reading orders…</p>
      ) : all.length === 0 ? (
        <p className="text-sm text-slate-400">{staleNow ? "Orders unavailable — the broker read failed." : "No orders yet."}</p>
      ) : table(all)}
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
    <Box title="Place an order by hand">
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
    </Box>
  );
}
