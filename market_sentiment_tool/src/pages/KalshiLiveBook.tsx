import { useEffect, useState } from "react";

import { sessionToken } from "@/components/RequireAdmin";
import { GET_JSON_TIMEOUT_MS, getJson } from "@/lib/getJson";
import { fmtUsd, tone } from "@/lib/paperPortfolio";
import { DashCard, Fig, PEEK, PeekRows, REFRESH_MS } from "@/pages/portfolio/shared";
import type { KalshiDemoPayload, KalshiLivePilot, KalshiLivePilotAdminOnly } from "@/lib/kalshiDemo";

export const REAL_MONEY_BADGE = "rounded border border-rose-500/40 bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-rose-300";
const money = (v: number | null | undefined) => fmtUsd(v);
const signed = (v: number | null | undefined) => fmtUsd(v, { signed: true });
const pct = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "—" : `${Math.round(v * 100)}%`;

const ET = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", month: "short", day: "numeric",
  hour: "numeric", minute: "2-digit", hour12: true,
});
const et = (iso: string | null) => (iso ? `${ET.format(new Date(iso))} ET` : "—");
const cents = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(0)}¢`);
// PREREG_AT: the deploy of PR #591 (issue #590) -- the live record starts here.
const LIVE_SINCE = "2026-11-24T14:21:37Z";

/** The live micro-pilot's scoreboard (issue #590): the oil & gas raw
 * rule on the LIVE Kalshi account. Real money — the badge and the
 * halt state are the point of the card. */
export function LivePilotCard({ pilot }: { pilot: KalshiLivePilot | KalshiLivePilotAdminOnly | null | undefined }) {
  if (!pilot) return null;
  if ("admin_only" in pilot) {
    return <p className="mb-3 text-xs text-slate-500">Live pilot: admin only</p>;
  }
  if (pilot.state === "unavailable") return null;
  const cents = (v: number | null | undefined) =>
    v == null || !Number.isFinite(v) ? "—" : `${v.toFixed(1)}¢`;
  const stat = (label: string, value: string, cls = "text-white") => (
    <div key={label}>
      <dt className="truncate text-[11px] text-slate-500">{label}</dt>
      <dd className={`text-sm font-semibold tabular-nums ${cls}`}>{value}</dd>
    </div>
  );
  const stateLine = pilot.halted
    ? `Halted — ${pilot.halt_reason ?? "halted"}`
    : pilot.state === "live" ? "Live" : "Not enabled";
  const gate = pilot.gates;
  return (
    <div className="mt-2 rounded-xl border border-slate-800 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-white">Live pilot — oil &amp; gas raw rule</span>
        <span className="rounded border border-rose-500/40 bg-rose-500/15 px-2 py-0.5 text-xs font-semibold text-rose-300">REAL MONEY</span>
        <span className={`text-xs font-medium ${pilot.halted ? "text-rose-300" : "text-slate-400"}`}>{stateLine}</span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stat("Live balance", money(pilot.balance))}
        {stat("P&L since start", signed(pilot.pnl_since_start), tone(pilot.pnl_since_start))}
        {stat("Fill rate", `${pilot.fills}/${pilot.decisions} · ${pct(pilot.fill_rate)}`)}
        {stat("Mean slippage vs paper", cents(pilot.mean_slippage_cents))}
        {stat("Live net / contract", signed(pilot.live_net_per_contract), tone(pilot.live_net_per_contract))}
        {stat("Live low95", cents(pilot.live_low95_cents))}
        {stat("Paper twin net / contract", signed(pilot.paper_net_per_contract), tone(pilot.paper_net_per_contract))}
        {stat("Paper twin low95", cents(pilot.paper_low95_cents))}
        {stat("Settled trades", String(pilot.settled))}
        {stat("Latency median", pilot.latency_median_s == null ? "—" : `${pilot.latency_median_s.toFixed(0)}s`)}
        {stat("Execution gate (50 fills)", `${gate.execution.state} · ${gate.execution.fills}/${gate.execution.bar}`)}
        {stat("Edge gate (150 settled)", `${gate.edge.state} · ${gate.edge.settled}/${gate.edge.bar}${gate.edge.stage3_unlocked ? " · stage 3 unlocked" : ""}`)}
      </dl>
    </div>
  );
}

export function OrdersTable({ orders }: { orders: KalshiLivePilot["orders"] }) {
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

export type KalshiRead = {
  /** The pilot, only for the signed-in admin; null for a visitor or before the first read. */
  pilot: KalshiLivePilot | null;
  /** The read landed and carries no account figures (a visitor, or admin-only). */
  adminOnly: boolean;
  loading: boolean;
  error: string | null;
};

/** The real-money Kalshi pilot's read (admin payload only), on the page's 30-second cycle. */
export function useKalshiPilot(): KalshiRead {
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
  const p = data?.live_pilot;
  const pilot = p && !("admin_only" in p) ? p : null;
  return { pilot, adminOnly: data !== null && pilot === null, loading: data === null && error === null, error };
}

/** The Kalshi account box for the left column: the figures as labelled rows. */
export function KalshiBox({ k }: { k: KalshiRead }) {
  const p = k.pilot;
  if (!p) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-xs text-slate-400">
        {k.loading ? "Reading the live account…"
          : k.adminOnly ? "Live pilot: sign in as admin to see the real-money account."
          : `Could not read the Kalshi live book: ${k.error}`}
      </div>
    );
  }
  const rows: [string, string, string?, string?][] = [
    ["Live balance", money(p.balance), undefined, "Cash in the live Kalshi account."],
    ["P&L since start", signed(p.pnl_since_start), tone(p.pnl_since_start), "Live profit or loss since the pilot began."],
    ["State", p.halted ? `Halted — ${p.halt_reason ?? "halted"}` : p.state === "live" ? "Running" : "Not enabled",
      p.halted ? "text-rose-300" : undefined, "Whether the pilot is trading, halted by a stop, or not enabled."],
    ["Fill rate", `${p.fills}/${p.decisions} · ${pct(p.fill_rate)}`, undefined, "Orders that filled, over orders the rule decided to place."],
    ["Settled trades", String(p.settled), undefined, "Positions that have resolved yes or no."],
    ["Daily stop", money(p.daily_stop_usd), undefined, "The day's loss at which the pilot halts itself."],
    ["Floor", money(p.floor_usd), undefined, "The balance below which the pilot stops trading."],
  ];
  return (
    <section aria-label="Kalshi account" className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-xs font-medium text-slate-400">Kalshi account</h2>
        <span className={REAL_MONEY_BADGE}>REAL MONEY</span>
      </div>
      <div className="mt-0.5 font-display text-2xl font-semibold tabular-nums tracking-tight text-white">{money(p.balance)}</div>
      {k.error && <p className="mt-1 text-[11px] text-rose-300">Refresh failed — showing the last report.</p>}
      <dl className="mt-2 divide-y divide-slate-800/70 text-xs">
        {rows.map(([label, value, cls, hint]) => (
          <div key={label} title={hint} className="flex items-baseline justify-between gap-2 py-1">
            <dt className="cursor-help text-slate-400 underline decoration-dotted decoration-slate-600 underline-offset-2">{label}</dt>
            <dd className={`text-right font-semibold tabular-nums ${cls ?? "text-slate-100"}`}>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Kalshi's two main cards, in the same frame as the paper books: Performance
 * (the pilot's P&L and progress) and Positions (its orders). No Trade card. */
export function KalshiMain({ k, open }: { k: KalshiRead; open?: "performance" | "positions" }) {
  const p = k.pilot;
  if (!p) return null;
  const orders = p.orders;
  const gate = p.gates;
  return (
    <div className="grid gap-2 lg:grid-cols-2">
      <DashCard title="Performance" value={signed(p.pnl_since_start)} valueClass={tone(p.pnl_since_start)}
                sub="P&L since start" meta={<span className={REAL_MONEY_BADGE}>REAL MONEY</span>}
                hint="The live pilot's scoreboard: P&L, fills and the two gates it must clear"
                defaultOpen={open === "performance"} detailTitle="Live pilot" detail={<LivePilotCard pilot={p} />}>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3">
          <Fig label="Live balance" value={money(p.balance)} />
          <Fig label="Fill rate" value={`${p.fills}/${p.decisions} · ${pct(p.fill_rate)}`} hint="Orders that filled, over orders decided" />
          <Fig label="Settled trades" value={String(p.settled)} />
          <Fig label="Live net / contract" value={signed(p.live_net_per_contract)} className={tone(p.live_net_per_contract)} />
          <Fig label="Execution gate" value={`${gate.execution.state} · ${gate.execution.fills}/${gate.execution.bar}`} hint="Needs 50 fills" />
          <Fig label="Edge gate" value={`${gate.edge.state} · ${gate.edge.settled}/${gate.edge.bar}`} hint="Needs 150 settled trades" />
        </dl>
      </DashCard>
      <DashCard title="Positions" value={orders.length} sub="orders" hint="Open and past live orders, newest first"
                defaultOpen={open === "positions"} detailTitle={`Live orders · ${orders.length}`}
                detail={orders.length ? <OrdersTable orders={orders} /> : undefined}>
        {orders.length ? (
          <>
            <PeekRows rows={orders.slice(0, PEEK).map((o, i) => ({
              key: String(o.id ?? `${o.ticker}-${i}`), label: o.ticker,
              aside: `${o.side.toUpperCase()} · ${o.status}`, value: signed(o.pnl), valueClass: tone(o.pnl),
            }))} />
            <p className="mt-1 text-xs text-slate-400">Show all {orders.length}</p>
          </>
        ) : (
          <p className="text-xs text-slate-400">
            Live since {et(LIVE_SINCE)}. No orders yet: the lane only buys when the oil &amp; gas rule clears its 10-point bar.
          </p>
        )}
      </DashCard>
    </div>
  );
}
