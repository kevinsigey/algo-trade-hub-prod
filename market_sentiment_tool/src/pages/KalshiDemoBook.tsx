import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Panel } from "@/components/Panel";
import { ctDateTime } from "@/lib/format";
import { getJson } from "@/lib/getJson";
import { fmtUsd, tone } from "@/lib/paperPortfolio";
import type {
  KalshiCurvePoint,
  KalshiDemoPayload,
  KalshiOrder,
} from "@/lib/kalshiDemo";

/** The demo runner trades on a 5-minute cadence; the tab re-reads on this one. */
export const REFRESH_MS = 30_000;

const money = (v: number | null | undefined) => fmtUsd(v, { whole: true });
const signed = (v: number | null | undefined) => fmtUsd(v, { signed: true, whole: true });
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
  if (rows.length === 0) return <p className="text-sm text-slate-400">No demo orders yet. The runner places the first one when the gas rule next fires a gated buy.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs tabular-nums">
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

  return (
    <div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="rounded border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-300">DEMO</span>
        <p className="text-sm text-slate-400">{data.note}</p>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
          <div className="text-xs text-slate-400">Demo balance</div>
          <div className="mt-0.5 text-2xl font-semibold tabular-nums tracking-tight text-white">{money(data.balance)}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
          <div className="text-xs text-slate-400">P&L today</div>
          <div className={`mt-0.5 text-2xl font-semibold tabular-nums tracking-tight ${tone(data.pnl_today)}`}>{signed(data.pnl_today)}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
          <div className="text-xs text-slate-400">P&L since the $500 start</div>
          <div className={`mt-0.5 text-2xl font-semibold tabular-nums tracking-tight ${tone(data.pnl_since_start)}`}>{signed(data.pnl_since_start)}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
          <div className="text-xs text-slate-400">Open positions</div>
          <div className="mt-0.5 text-2xl font-semibold tabular-nums tracking-tight text-white">{data.positions.length}</div>
        </div>
      </div>

      <div className="mt-4">
        <Panel title="Positions">
          {data.positions.length === 0 ? (
            <p className="text-sm text-slate-400">No open positions. Demo orders live inside one 15-minute window and settle at its close.</p>
          ) : (
            <table className="w-full text-xs tabular-nums">
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
                {data.positions.map((p) => (
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
          )}
        </Panel>
      </div>

      <div className="mt-4">
        <Panel title="Performance — demo vs shadow, same decisions">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs tabular-nums">
            <span className="text-slate-400">Fill rate <span className="text-slate-100">{pct(perf.fill_rate)}</span></span>
            <span className="text-slate-400">Avg slippage vs frozen quote <span className="text-slate-100">{perf.avg_slippage_cents == null ? "—" : `${perf.avg_slippage_cents.toFixed(1)}¢`}</span></span>
            <span className="text-slate-400">Win rate <span className="text-slate-100">{pct(perf.win_rate)}</span></span>
            <span className="text-slate-400">P&L per contract <span className={tone(perf.pnl_per_contract)}>{signed(perf.pnl_per_contract)}</span></span>
            <span className="text-slate-400">Decisions not traded <span className="text-slate-100">{notTraded.caps + notTraded.no_depth + notTraded.missed}</span>
              <span className="text-slate-500"> (caps {notTraded.caps} · no depth {notTraded.no_depth} · missed {notTraded.missed})</span></span>
          </div>
          {curve.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">No settled demo trades yet — the two lines start with the first settlement.</p>
          ) : (
            <div className="mt-3 h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={curve} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="at" tick={false} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} width={56}
                         tickFormatter={(v: number) => fmtUsd(v, { whole: true })} />
                  <Tooltip
                    formatter={(v: number, name: string) => [fmtUsd(v), name === "demo" ? "Demo" : "Shadow"]}
                    labelFormatter={(at: string) => ctDateTime(at)}
                    contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", fontSize: 12 }}
                  />
                  <Line type="monotone" dataKey="demo" stroke="#34d399" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="shadow" stroke="#94a3b8" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
              <div className="mt-1 flex gap-4 text-[11px] text-slate-400">
                <span><span className="text-emerald-400">—</span> Demo (actual fills)</span>
                <span><span className="text-slate-400">—</span> Shadow (frozen quote, same size)</span>
              </div>
            </div>
          )}
        </Panel>
      </div>

      <div className="mt-4">
        <Panel title="Orders">
          <OrdersTable orders={data.orders} />
        </Panel>
      </div>
    </div>
  );
}
