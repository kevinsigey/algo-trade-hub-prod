import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ctDateTime } from "@/lib/format";
import { getJson } from "@/lib/getJson";
import { fmtUsd, tone } from "@/lib/paperPortfolio";
import { DashCard, PEEK, PeekRows, Spark } from "@/pages/portfolio/shared";
import type {
  KalshiCurvePoint,
  KalshiDemoLive,
  KalshiDemoPayload,
  KalshiOrder,
} from "@/lib/kalshiDemo";

/** The demo runner trades on a 5-minute cadence; the tab re-reads on this one. */
export const REFRESH_MS = 30_000;

const money = (v: number | null | undefined) => fmtUsd(v);
const signed = (v: number | null | undefined) => fmtUsd(v, { signed: true });
const price = (v: number | null | undefined) => fmtUsd(v);
const pct = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "—" : `${Math.round(v * 100)}%`;

function countdown(closeTime: string | null): string {
  if (!closeTime) return "—";
  const ms = new Date(closeTime).getTime() - Date.now();
  if (!Number.isFinite(ms)) return "—";
  if (ms <= 0) return "closed";
  const mins = Math.round(ms / 60_000);
  return mins < 1 ? "under a minute" : `in ${mins}m`;
}

/** Demo and shadow cumulative P&L on one time axis, each carried forward. */
function mergeCurves(demo: KalshiCurvePoint[], shadow: KalshiCurvePoint[]) {
  const d = new Map(demo.map((p) => [p.at, p.pnl]));
  const s = new Map(shadow.map((p) => [p.at, p.pnl]));
  const times = [...new Set([...d.keys(), ...s.keys()])].sort();
  let dv = 0;
  let sv = 0;
  return times.map((at) => {
    if (d.has(at)) dv = d.get(at) as number;
    if (s.has(at)) sv = s.get(at) as number;
    return { at, demo: dv, shadow: sv };
  });
}

type SortKey = "created_at" | "ticker" | "contracts" | "limit_price" | "fill_price" | "status" | "settlement_pnl";

function OrdersTable({ orders }: { orders: KalshiOrder[] }) {
  const [sort, setSort] = useState<{ key: SortKey; asc: boolean }>({ key: "created_at", asc: false });
  const rows = useMemo(() => {
    const out = [...orders];
    out.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av).localeCompare(String(bv));
      return sort.asc ? cmp : -cmp;
    });
    return out;
  }, [orders, sort]);
  const head = (label: string, key: SortKey, right = false) => (
    <th scope="col" className={`pb-1 pr-2 font-medium ${right ? "text-right" : ""}`}>
      <button type="button" className="hover:text-slate-200"
        onClick={() => setSort((s) => ({ key, asc: s.key === key ? !s.asc : true }))}>
        {label}{sort.key === key ? (sort.asc ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
  if (rows.length === 0) return <p className="text-sm text-slate-400">No demo orders yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[48rem] text-xs tabular-nums">
        <thead><tr className="text-left text-slate-500">
          {head("Placed", "created_at")}
          {head("Market", "ticker")}
          <th scope="col" className="pb-1 pr-2 font-medium">Side</th>
          {head("Contracts", "contracts", true)}
          {head("Limit", "limit_price", true)}
          {head("Fill", "fill_price", true)}
          {head("Status", "status")}
          <th scope="col" className="pb-1 pr-2 font-medium">Window close</th>
          {head("P&L", "settlement_pnl", true)}
        </tr></thead>
        <tbody>
          {rows.map((o) => (
            <tr key={o.id} className="border-t border-slate-800/70">
              <td className="py-1 pr-2 text-slate-400">{ctDateTime(o.created_at)}</td>
              <td className="py-1 pr-2 font-semibold text-white">{o.ticker}</td>
              <td className="py-1 pr-2 text-slate-200">{o.side.toUpperCase()}</td>
              <td className="py-1 pr-2 text-right text-slate-200">{o.contracts_filled}/{o.contracts}</td>
              <td className="py-1 pr-2 text-right text-slate-200">{price(o.limit_price)}</td>
              <td className="py-1 pr-2 text-right text-slate-200">{price(o.fill_price)}</td>
              <td className="py-1 pr-2 text-slate-200">
                {o.status}{o.skip_reason ? <span className="text-slate-500"> · {o.skip_reason}</span> : null}
              </td>
              <td className="py-1 pr-2 text-slate-400">{ctDateTime(o.window_close)}</td>
              <td className={`py-1 text-right ${tone(o.settlement_pnl)}`}>{signed(o.settlement_pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function KalshiDemoBook() {
  const [data, setData] = useState<KalshiDemoPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      getJson<KalshiDemoPayload>("/api/kalshi-demo")
        .then((body) => {
          if (!cancelled) {
            setData(body);
            setError(null);
          }
        })
        .catch((err) => {
          if (!cancelled) setError(err instanceof Error ? err.message : "Unknown error");
        });
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (data === null && error === null) {
    return (
      <div className="mt-8 flex items-center gap-2 text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Reading the demo account…
      </div>
    );
  }
  if (error && data === null) {
    return <p className="mt-8 text-rose-300">Could not read the Kalshi demo book: {error}</p>;
  }
  if (data === null) return null;

  if (data.state === "not_connected") {
    return (
      <div className="mt-6 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center gap-2">
          <span className="text-xl font-semibold text-white">Kalshi demo account not connected</span>
          <span className="rounded border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">DEMO</span>
        </div>
        <p className="mt-1 max-w-prose text-sm text-slate-400">{data.note}</p>
      </div>
    );
  }

  const perf = data.performance;
  const curve = mergeCurves(perf.demo_curve, perf.shadow_curve);
  const notTraded = perf.decisions_not_traded;
  const notTradedTotal = notTraded.caps + notTraded.no_depth + notTraded.missed;
  const settledPnl = data.orders.some((o) => o.settlement_pnl != null)
    ? data.orders.reduce((a, o) => a + (o.settlement_pnl ?? 0), 0) : null;
  const newest = [...data.orders].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const stat = (label: string, value: string, cls = "text-white") => (
    <div key={label}><dt className="truncate text-[11px] text-slate-500">{label}</dt><dd className={`text-sm font-semibold tabular-nums ${cls}`}>{value}</dd></div>
  );
  const kpi = (label: string, value: string, cls = "text-white") => (
    <DashCard title={label} value={value} valueClass={cls} />
  );

  return (
    <div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="rounded border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-300">DEMO</span>
        <p className="text-xs text-slate-400">{data.note}</p>
      </div>

      {error ? (
        <p className="mt-2 text-sm text-rose-300">
          Refresh failed: {error} — showing the last report, as of {ctDateTime(data.as_of)}.
        </p>
      ) : null}

      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        {kpi("Demo balance", money(data.balance))}
        {kpi("P&L today", signed(data.pnl_today), tone(data.pnl_today))}
        {kpi(`P&L since the ${fmtUsd(data.starting_balance, { whole: true })} start`, signed(data.pnl_since_start), tone(data.pnl_since_start))}
        {kpi("Open positions", data.positions_unavailable ? "—" : String(data.positions.length))}
      </div>

      <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        <DashCard title="Demo vs shadow" className="md:col-span-2"
                  value={signed(curve.length ? curve[curve.length - 1].demo : null)}
                  valueClass={tone(curve.length ? curve[curve.length - 1].demo : null)}
                  sub={<>Shadow {signed(curve.length ? curve[curve.length - 1].shadow : null)} · fill rate {pct(perf.fill_rate)} · win rate {pct(perf.win_rate)}</>}
                  hint="Same decisions: demo is actual fills, shadow is the frozen quote at the same size"
                  detailTitle="Performance — demo vs shadow, same decisions"
                  detail={(
                    <div>
                      <dl className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
                        {stat("Fill rate", pct(perf.fill_rate))}
                        {stat("Avg slippage vs frozen quote", perf.avg_slippage_cents == null ? "—" : `${perf.avg_slippage_cents.toFixed(1)}¢`)}
                        {stat("Win rate", pct(perf.win_rate))}
                        {stat("P&L per contract", signed(perf.pnl_per_contract), tone(perf.pnl_per_contract))}
                        {stat("Decisions not traded", `${notTradedTotal} (caps ${notTraded.caps} · no depth ${notTraded.no_depth} · missed ${notTraded.missed})`)}
                      </dl>
                      {curve.length === 0 ? (
                        <p className="text-sm text-slate-400">No settled demo trades yet — the two lines start with the first settlement.</p>
                      ) : (
                        <div className="h-[46vh] min-h-56">
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={curve} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                              <XAxis dataKey="at" tick={false} axisLine={false} tickLine={false} />
                              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} width={56}
                                     tickFormatter={(v: number) => fmtUsd(v, { whole: true })} />
                              <Tooltip formatter={(v: number, name: string) => [fmtUsd(v), name === "demo" ? "Demo" : "Shadow"]}
                                       labelFormatter={(at: string) => ctDateTime(at)}
                                       contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", fontSize: 12 }} />
                              <Line type="monotone" dataKey="demo" stroke="#34d399" strokeWidth={2} dot={false} isAnimationActive={false} />
                              <Line type="monotone" dataKey="shadow" stroke="#94a3b8" strokeWidth={2} dot={false} isAnimationActive={false} />
                            </LineChart>
                          </ResponsiveContainer>
                          <div className="mt-1 flex gap-4 text-[11px] text-slate-400">
                            <span><span className="text-emerald-400">—</span> Demo (actual fills)</span>
                            <span><span className="text-slate-400">—</span> Shadow (frozen quote, same size)</span>
                          </div>
                        </div>
                      )}
                    </div>
                  )}>
          <Spark data={curve} height={64} lines={[{ key: "demo", color: "#34d399", width: 2 }, { key: "shadow", color: "#94a3b8", dashed: true }]} />
          <dl className="mt-2 grid grid-cols-3 gap-3">
            {stat("Slippage", perf.avg_slippage_cents == null ? "—" : `${perf.avg_slippage_cents.toFixed(1)}¢`)}
            {stat("Per contract", signed(perf.pnl_per_contract), tone(perf.pnl_per_contract))}
            {stat("Not traded", String(notTradedTotal))}
          </dl>
        </DashCard>

        <DashCard title="Positions" value={data.positions_unavailable ? "—" : data.positions.length}
                  detail={data.positions.length ? <PositionsTable positions={data.positions} /> : undefined}>
          {data.positions_unavailable ? (
            <p className="text-xs text-slate-400" title="The account read failed, so this is not proof the book is flat">Positions unavailable</p>
          ) : (
            <PeekRows empty="No open positions" rows={data.positions.slice(0, PEEK).map((p) => ({
              key: p.ticker, label: p.ticker, aside: `${p.side.toUpperCase()} ${p.contracts}`,
              value: signed(p.open_pnl), valueClass: tone(p.open_pnl),
            }))} />
          )}
        </DashCard>

        <DashCard title="Orders" value={data.orders.length} meta={<span className={tone(settledPnl)}>{signed(settledPnl)}</span>}
                  detail={data.orders.length ? <OrdersTable orders={data.orders} /> : undefined}>
          <PeekRows empty="No demo orders yet" rows={newest.slice(0, PEEK).map((o) => ({
            key: String(o.id), label: o.ticker, aside: o.status,
            value: signed(o.settlement_pnl), valueClass: tone(o.settlement_pnl),
          }))} />
        </DashCard>
      </div>
    </div>
  );
}

function PositionsTable({ positions }: { positions: KalshiDemoLive["positions"] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] text-xs tabular-nums">
        <thead><tr className="text-left text-slate-500">
          <th scope="col" className="pb-1 pr-2 font-medium">Market</th>
          <th scope="col" className="pb-1 pr-2 text-right font-medium">Strike</th>
          <th scope="col" className="pb-1 pr-2 font-medium">Side</th>
          <th scope="col" className="pb-1 pr-2 text-right font-medium">Contracts</th>
          <th scope="col" className="pb-1 pr-2 text-right font-medium">Avg price</th>
          <th scope="col" className="pb-1 pr-2 text-right font-medium">Yes bid / ask</th>
          <th scope="col" className="pb-1 pr-2 text-right font-medium">Open P&L</th>
          <th scope="col" className="pb-1 font-medium">Closes</th>
        </tr></thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.ticker} className="border-t border-slate-800/70">
              <td className="py-1 pr-2 font-semibold text-white">{p.ticker}</td>
              <td className="py-1 pr-2 text-right text-slate-200">{p.strike == null ? "—" : p.strike}</td>
              <td className="py-1 pr-2 text-slate-200">{p.side.toUpperCase()}</td>
              <td className="py-1 pr-2 text-right text-slate-200">{p.contracts}</td>
              <td className="py-1 pr-2 text-right text-slate-200">{price(p.avg_price)}</td>
              <td className="py-1 pr-2 text-right text-slate-200">{price(p.yes_bid)} / {price(p.yes_ask)}</td>
              <td className={`py-1 pr-2 text-right ${tone(p.open_pnl)}`}>{signed(p.open_pnl)}</td>
              <td className="py-1 text-slate-400">{p.close_time ? ctDateTime(p.close_time) : "—"} · {countdown(p.close_time)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
