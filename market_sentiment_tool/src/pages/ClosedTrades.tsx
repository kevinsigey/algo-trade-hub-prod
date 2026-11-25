import { DashCard, PEEK, PeekRows, REFRESH_MS } from "@/pages/portfolio/shared";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  fmtUsd, stateLabel, tone,
  type ActivityOrder, type ActivityPayload, type ResultsSplit,
} from "@/lib/paperPortfolio";

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

/** Tested ideas vs discretionary trades (2026-11-11): the split the Nov 10
 * review asked the Portfolio results to carry, with the discretionary side's
 * stated reasons attached. Aggregate first; the reasons are the detail. */
function ResultsSplitPanel({ split }: { split: ResultsSplit }) {
  const side = (label: string, s: ResultsSplit["tested"]) => (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-1 text-lg font-semibold tabular-nums ${tone(s.pnl)}`}>{fmtUsd(s.pnl, { signed: true })}</p>
      <p className="text-xs tabular-nums text-slate-400">{s.trades} closed · {s.wins} won</p>
    </div>
  );
  return (
    <DashCard title="Results by kind" className="md:col-span-2" hint="Tested ideas vs discretionary trades, with the discretionary reasons">
      <div className="grid gap-4 sm:grid-cols-2">
        {side("Tested ideas", split.tested)}
        <div>
          {side("Discretionary", split.discretionary)}
          {split.discretionary.reasons.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-xs tabular-nums">
              {split.discretionary.reasons.map((r) => (
                <li key={r.reason} className="flex items-baseline justify-between gap-2 border-t border-slate-800/70 pt-1">
                  <span className="truncate text-slate-300">{r.reason} <span className="text-slate-500">· {r.trades}</span></span>
                  <span className={`shrink-0 ${tone(r.pnl)}`}>{fmtUsd(r.pnl, { signed: true })}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </DashCard>
  );
}

/** What the old Trades and Orders page held beyond the Trade tab's own cards
 * (2026-11-25 fold into Portfolio): the working orders read from the activity
 * feed, and the tested-vs-discretionary results with their reasons. Its recent
 * orders and closed trades lists live on as the Trade tab's richer cards. */
export default function WorkingOrdersAndResults({ book }: { book: string }) {
  const { data, error, loading } = useApi<ActivityPayload>(`/api/portfolio/activity?book=${book}`, REFRESH_MS);
  const open = Array.isArray(data?.open) ? data.open : [];
  return (
    <>
      <DashCard title="Open orders" value={data ? open.length : "—"}
                meta={data ? stateLabel(data.state, data.as_of) : undefined}
                hint="Working orders on the broker, read from the activity feed"
                detail={open.length ? <OrderTable rows={open} showStatus /> : undefined} detailTitle={`Open orders · ${open.length}`}>
        {loading && !data ? <p className="text-xs text-slate-500">Reading…</p>
          : error && !data ? <p className="text-xs text-slate-400">Couldn&apos;t read open orders: {error}</p>
          : <PeekRows empty="No working orders right now." rows={open.slice(0, PEEK).map((o, i) => ({
            key: `${o.symbol}-${o.submitted_at}-${i}`,
            label: <><span className={o.side === "buy" ? "text-emerald-300" : "text-rose-300"}>{o.side}</span> {o.symbol} {qtyText(o)}</>,
            aside: when(o.submitted_at), value: o.status.replace(/_/g, " "), valueClass: statusTone(o.status),
          }))} />}
      </DashCard>
      {data?.results_split && data.trades.length > 0 && <ResultsSplitPanel split={data.results_split} />}
    </>
  );
}
