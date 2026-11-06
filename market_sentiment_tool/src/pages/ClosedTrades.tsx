import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";

import { Panel } from "@/components/Panel";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  fmtPct, fmtUsd, stateLabel, tone,
  type ActivityOrder, type ActivityPayload, type ClosedTrade,
} from "@/lib/paperPortfolio";

const day = (iso: string) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—");

const qtyText = (o: ActivityOrder) =>
  o.filled_qty && o.qty ? `${o.filled_qty}/${o.qty}` : o.qty != null ? `${o.qty}` : "—";
const priceText = (o: ActivityOrder) =>
  o.limit_price != null ? `limit ${fmtUsd(o.limit_price)}`
    : o.stop_price != null ? `stop ${fmtUsd(o.stop_price)}` : o.type ?? "—";
const statusTone = (s: string) =>
  s === "filled" ? "text-emerald-300" : s === "rejected" || s === "expired" || s === "canceled" ? "text-slate-500"
    : "text-amber-300";

function OrderTable({ rows, showStatus }: { rows: ActivityOrder[]; showStatus: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] text-sm tabular-nums">
        <thead className="text-left text-slate-400">
          <tr>
            <th className="py-2 pr-4 font-medium">Symbol</th>
            <th className="py-2 pr-4 font-medium">Side</th>
            <th className="py-2 pr-4 text-right font-medium">Qty</th>
            <th className="py-2 pr-4 font-medium">Order</th>
            {showStatus && <th className="py-2 pr-4 font-medium">Status</th>}
            <th className="py-2 pr-4 text-right font-medium">Filled at</th>
            <th className="py-2 pr-4 font-medium">Source</th>
            <th className="py-2 font-medium">When</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((o, i) => (
            <tr key={`${o.symbol}-${o.submitted_at}-${i}`} className="border-t border-slate-800/80">
              <td className="py-2 pr-4 font-semibold text-white">
                {o.symbol}
                {o.asset === "option" && <span className="ml-1.5 text-xs font-normal text-slate-400">option</span>}
              </td>
              <td className={`py-2 pr-4 ${o.side === "buy" ? "text-emerald-300" : "text-rose-300"}`}>{o.side}</td>
              <td className="py-2 pr-4 text-right text-slate-300">{qtyText(o)}</td>
              <td className="py-2 pr-4 text-slate-300">{priceText(o)} · {o.time_in_force ?? ""}</td>
              {showStatus && <td className={`py-2 pr-4 ${statusTone(o.status)}`}>{o.status.replace(/_/g, " ")}</td>}
              <td className="py-2 pr-4 text-right text-slate-300">{o.filled_avg_price != null ? fmtUsd(o.filled_avg_price) : "—"}</td>
              <td className="py-2 pr-4 text-slate-300">{o.source}</td>
              <td className="py-2 text-slate-400">{when(o.filled_at ?? o.submitted_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradesTable({ rows }: { rows: ClosedTrade[] }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full min-w-[40rem] text-sm tabular-nums">
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
          {rows.map((t, i) => (
            <tr key={`${t.symbol}-${t.exited_at}-${i}`} className="border-t border-slate-800/80">
              <td className="py-2 pr-4 font-semibold text-white">
                {t.symbol}
                {t.qty < 0 && <span className="ml-1.5 text-xs font-normal text-slate-400">short</span>}
              </td>
              <td className="py-2 pr-4 text-right text-slate-300">{Math.abs(t.qty)}</td>
              <td className="py-2 pr-4 text-right text-slate-300">
                {fmtUsd(t.entry_price)} <span className="block text-xs text-slate-500">{day(t.entered_at)}</span>
              </td>
              <td className="py-2 pr-4 text-right text-slate-300">
                {fmtUsd(t.exit_price)} <span className="block text-xs text-slate-500">{day(t.exited_at)}</span>
              </td>
              <td className={`py-2 pr-4 text-right ${tone(t.pnl)}`}>
                {fmtUsd(t.pnl, { signed: true })} <span className="block text-xs">{fmtPct(t.return_pct)}</span>
              </td>
              <td className="py-2 pr-4 text-right text-slate-300">{t.held_days}d</td>
              <td className="whitespace-nowrap py-2 text-slate-300">{t.idea}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A short line per order, newest first; the full table opens from the panel. */
function OrderLines({ rows }: { rows: ActivityOrder[] }) {
  return (
    <ul className="space-y-0.5 text-xs tabular-nums">
      {rows.map((o, i) => (
        <li key={`${o.symbol}-${o.submitted_at}-${i}`} className="flex items-baseline justify-between gap-2 border-t border-slate-800/70 pt-1">
          <span className="truncate text-slate-300">
            <span className={o.side === "buy" ? "text-emerald-300" : "text-rose-300"}>{o.side}</span>{" "}
            <span className="font-semibold text-white">{o.symbol}</span> {qtyText(o)}
            <span className="text-slate-500"> · {when(o.filled_at ?? o.submitted_at)}</span>
          </span>
          <span className={`shrink-0 ${statusTone(o.status)}`}>{o.status.replace(/_/g, " ")}</span>
        </li>
      ))}
    </ul>
  );
}

const SHOWN = 15;

export default function ClosedTrades() {
  const [searchParams] = useSearchParams();
  const param = searchParams.get("book");
  const book = param === "big" ? "big" : "main";
  const { data, error, loading } = useApi<ActivityPayload>(`/api/portfolio/activity?book=${book}`);
  const total = data?.trades.reduce((sum, t) => sum + t.pnl, 0) ?? null;

  return (
    <div className="mx-auto max-w-[100rem] px-4 py-5 md:px-6">
      <Link to={param ? `/portfolio?book=${book}` : "/"} className="inline-flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Portfolio
      </Link>
      <h1 className="mt-3 text-2xl font-bold tracking-tight text-white">Trades and Orders</h1>

      <nav aria-label="Paper books" className="mt-3 flex flex-wrap items-center gap-2">
        {([["main", "Main book"], ["big", "$1M book"]] as const).map(([name, label]) => (
          <Link key={name} to={`/portfolio/closed?book=${name}`} aria-current={book === name ? "page" : undefined}
            className={`rounded-lg border px-3 py-1.5 text-sm ${book === name ? "border-emerald-500/40 bg-emerald-500/10 font-semibold text-emerald-300" : "border-slate-700 text-slate-300 hover:bg-slate-900"}`}>
            {label}
          </Link>
        ))}
      </nav>

      {loading && (
        <div className="mt-8 flex items-center gap-2 text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Reading the account…
        </div>
      )}
      {error && <p className="mt-8 text-rose-300">Could not read the account: {error}</p>}

      {data && (
        <>
          <p className="mt-1 text-xs text-slate-400">{stateLabel(data.state, data.as_of)}</p>

          {/* One screen (Kevin, 2026-11-06): each list shows its latest rows and opens in full. */}
          <div className="mt-4 grid gap-2 lg:grid-cols-3">
            <Panel title={`Open orders · ${data.open.length}`}
                   full={data.open.length > SHOWN ? <OrderTable rows={data.open} showStatus /> : undefined}>
              {data.open.length === 0
                ? <p className="text-sm text-slate-400">No working orders right now.</p>
                : <OrderLines rows={data.open.slice(0, SHOWN)} />}
            </Panel>
            <Panel title={`Recent orders · ${data.recent.length}`}
                   full={data.recent.length ? <OrderTable rows={data.recent} showStatus /> : undefined}>
              {data.recent.length === 0
                ? <p className="text-sm text-slate-400">No orders yet.</p>
                : <OrderLines rows={data.recent.slice(0, SHOWN)} />}
            </Panel>
            <Panel title={`Closed trades · ${data.trades.length}`}
                   meta={data.trades.length ? <span className={`text-xs tabular-nums ${tone(total)}`}>{fmtUsd(total, { signed: true })}</span> : undefined}
                   full={data.trades.length ? <TradesTable rows={data.trades} /> : undefined}>
              {data.trades.length === 0 ? (
                <p className="text-sm text-slate-400">No closed trades yet.</p>
              ) : (
                <ul className="space-y-0.5 text-xs tabular-nums">
                  {[...data.trades].reverse().slice(0, SHOWN).map((t, i) => (
                    <li key={`${t.symbol}-${t.exited_at}-${i}`} className="flex items-baseline justify-between gap-2 border-t border-slate-800/70 pt-1">
                      <span className="truncate text-slate-300">
                        <span className="font-semibold text-white">{t.symbol}</span>
                        {t.qty < 0 && <span className="ml-1 text-slate-400">short</span>}
                        <span className="text-slate-500"> · {day(t.exited_at)} · {t.held_days}d</span>
                      </span>
                      <span className={`shrink-0 ${tone(t.pnl)}`}>{fmtUsd(t.pnl, { signed: true })} <span className="text-slate-500">{fmtPct(t.return_pct)}</span></span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
