import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { sessionToken } from "@/components/RequireAdmin";
import { GET_JSON_TIMEOUT_MS, getJson } from "@/lib/getJson";
import { fmtUsd, tone } from "@/lib/paperPortfolio";
import { LivePilotCard, REFRESH_MS } from "@/pages/KalshiDemoBook";
import type { KalshiDemoPayload, KalshiLivePilot } from "@/lib/kalshiDemo";

const ET = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", month: "short", day: "numeric",
  hour: "numeric", minute: "2-digit", hour12: true,
});
const et = (iso: string | null) => (iso ? `${ET.format(new Date(iso))} ET` : "—");
const cents = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(0)}¢`);

function OrdersTable({ orders }: { orders: KalshiLivePilot["orders"] }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full min-w-[52rem] text-xs tabular-nums">
        <thead><tr className="text-left text-slate-500">
          {["Time", "Market", "Side", "Status"].map((h) => <th key={h} scope="col" className="pb-1 pr-2 font-medium">{h}</th>)}
          {["Contracts", "Paper price", "Fill", "Slippage"].map((h) => <th key={h} scope="col" className="pb-1 pr-2 text-right font-medium">{h}</th>)}
          <th scope="col" className="pb-1 pr-2 font-medium">Outcome</th>
          <th scope="col" className="pb-1 text-right font-medium">P&amp;L</th>
        </tr></thead>
        <tbody>
          {orders.map((o) => {
            const slip = o.fill_price != null && o.frozen_quote != null ? (o.fill_price - o.frozen_quote) * 100 : null;
            return (
              <tr key={String(o.id ?? o.ticker)} className="border-t border-slate-800/70">
                <td className="py-1 pr-2 text-slate-400">{et(o.created_at)}</td>
                <td className="py-1 pr-2 font-semibold text-white">{o.ticker}</td>
                <td className="py-1 pr-2 text-slate-200">{o.side.toUpperCase()}</td>
                <td className="py-1 pr-2 text-slate-200">
                  {o.status}{o.skip_reason ? <span className="text-slate-500"> · {o.skip_reason}</span> : null}
                </td>
                <td className="py-1 pr-2 text-right text-slate-200">{o.contracts_filled}/{o.contracts_requested ?? "—"}</td>
                <td className="py-1 pr-2 text-right text-slate-200">{cents(o.frozen_quote)}</td>
                <td className="py-1 pr-2 text-right text-slate-200">{cents(o.fill_price)}</td>
                <td className="py-1 pr-2 text-right text-slate-200">{slip == null ? "—" : `${slip.toFixed(1)}¢`}</td>
                <td className="py-1 pr-2 text-slate-200">{o.outcome == null ? "—" : o.outcome ? "yes" : "no"}</td>
                <td className={`py-1 text-right ${tone(o.pnl)}`}>{fmtUsd(o.pnl, { signed: true })}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** The real-money Kalshi pilot on its own Portfolio book (admin payload only). */
export default function KalshiLiveBook() {
  const [data, setData] = useState<KalshiDemoPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      sessionToken()
        .then((token) => getJson<KalshiDemoPayload>("/api/kalshi-demo", GET_JSON_TIMEOUT_MS,
          token ? { Authorization: `Bearer ${token}` } : undefined))
        .then((body) => { if (!cancelled) { setData(body); setError(null); } })
        .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "Unknown error"); });
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  if (data === null && error === null) {
    return (
      <div className="mt-8 flex items-center gap-2 text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Reading the live account…
      </div>
    );
  }
  if (data === null) return <p className="mt-8 text-rose-300">Could not read the Kalshi live book: {error}</p>;

  const pilot = data.live_pilot;
  if (!pilot || "admin_only" in pilot) {
    return <p className="mt-6 text-sm text-slate-400">Live pilot: sign in as admin to see the real-money account.</p>;
  }

  return (
    <div>
      {error ? <p className="mt-2 text-sm text-rose-300">Refresh failed: {error} — showing the last report.</p> : null}
      <p className="mt-3 text-sm text-slate-300">
        Balance <b className="text-white">{fmtUsd(pilot.balance)}</b>
        {" · "}P&amp;L since start <b className={tone(pilot.pnl_since_start)}>{fmtUsd(pilot.pnl_since_start, { signed: true })}</b>
        {" · "}<b className={pilot.halted ? "text-rose-300" : "text-white"}>{pilot.halted ? "Halted" : "Running"}</b>
      </p>
      <LivePilotCard pilot={pilot} />
      {pilot.orders.length ? <OrdersTable orders={pilot.orders} /> : (
        <p className="mt-3 text-sm text-slate-400">
          Live since {pilot.balance_at ? et(pilot.balance_at) : "the first pass"}. No orders yet: the lane only buys when the oil &amp; gas rule clears its 10-point bar.
        </p>
      )}
    </div>
  );
}
