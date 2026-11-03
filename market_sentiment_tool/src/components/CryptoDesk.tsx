import { useEffect, useMemo, useState } from "react";

import { getJson } from "@/lib/getJson";

// The crypto desk (step 2 of Kevin's crypto program, 2026-11-03):
// protocols and networks read like companies -- price, market cap, FDV,
// 24h fees and revenue, annualized P/F and P/S, the fee trend against
// its own run-rate, TVL. Live data (DefiLlama + CoinGecko via the hub,
// cached server-side), polled every minute. Not a signal: a desk you
// read the sector off.

export interface DeskRow {
  key: string; name: string; kind: string; symbol: string | null;
  price: number | null; change_24h: number | null;
  mcap: number | null; fdv: number | null;
  fees_24h: number | null; revenue_24h: number | null;
  pf: number | null; ps: number | null;
  fee_trend_7d: number | null; fee_trend_30d: number | null;
  tvl: number | null;
}

export interface DeskPayload {
  as_of: string;
  sources: Record<string, string>;
  rows: DeskRow[];
}

const REFRESH_MS = 60 * 1000;

export function bigUsd(v: number | null | undefined): string {
  if (v == null) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}

export function priceText(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 100) return `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  if (v >= 1) return `$${v.toFixed(2)}`;
  return `$${v.toFixed(4)}`;
}

function Trend({ v }: { v: number | null }) {
  if (v == null) return <span className="text-muted-foreground">—</span>;
  const up = v >= 0;
  return (
    <span className={up ? "text-emerald-500" : "text-rose-500"}>
      {up ? "▲" : "▼"} {Math.abs(v).toFixed(0)}%
    </span>
  );
}

type SortKey = "pf" | "fees" | "mcap";

export default function CryptoDesk() {
  const [desk, setDesk] = useState<DeskPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [sort, setSort] = useState<SortKey>("pf");

  useEffect(() => {
    let stop = false;
    const load = () => getJson<DeskPayload>("/api/crypto/desk")
      .then((d) => { if (!stop && d && Array.isArray(d.rows)) { setDesk(d); setFailed(false); } })
      .catch(() => { if (!stop) setFailed(true); });
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => { stop = true; clearInterval(t); };
  }, []);

  const rows = useMemo(() => {
    const rs = [...(desk?.rows ?? [])];
    if (sort === "fees") rs.sort((a, b) => (b.fees_24h ?? -1) - (a.fees_24h ?? -1));
    if (sort === "mcap") rs.sort((a, b) => (b.mcap ?? -1) - (a.mcap ?? -1));
    return rs; // "pf" keeps the server's order (P/F ascending, unpriced last)
  }, [desk, sort]);

  return (
    <section aria-label="Crypto desk" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">The desk — protocols &amp; networks as companies</h2>
          <p className="text-xs text-muted-foreground">
            Fees and revenue are the income statement; P/F and P/S annualize the last 24 hours.
            {desk ? ` Updated ${new Date(desk.as_of).toLocaleTimeString()}.` : ""}
          </p>
        </div>
        <div className="flex gap-1" role="group" aria-label="Sort the desk">
          {([["pf", "Cheapest P/F"], ["fees", "Fees"], ["mcap", "Mkt cap"]] as [SortKey, string][]).map(([k, label]) => (
            <button key={k} type="button" onClick={() => setSort(k)} aria-pressed={sort === k}
                    className={`rounded-full border px-3 py-1 text-[13px] ${sort === k ? "border-slate-400 text-foreground" : "border-border text-muted-foreground"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {failed && !desk ? (
        <p className="text-sm text-muted-foreground">The desk could not be reached just now.</p>
      ) : !desk ? (
        <p className="text-sm text-muted-foreground">Loading the desk…</p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-border/70 bg-card shadow-sm">
          <table className="w-full min-w-[880px] text-sm tabular-nums">
            <thead>
              <tr className="border-b border-border/70 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                <th className="px-4 py-2.5 font-medium">Name</th>
                <th className="px-2 py-2.5 font-medium">Price</th>
                <th className="px-2 py-2.5 font-medium">24h</th>
                <th className="px-2 py-2.5 font-medium">Mkt cap</th>
                <th className="px-2 py-2.5 font-medium">FDV</th>
                <th className="px-2 py-2.5 font-medium">Fees 24h</th>
                <th className="px-2 py-2.5 font-medium">Revenue 24h</th>
                <th className="px-2 py-2.5 font-medium">P/F</th>
                <th className="px-2 py-2.5 font-medium">P/S</th>
                <th className="px-2 py-2.5 font-medium">Fees vs 7d</th>
                <th className="px-2 py-2.5 font-medium">Fees vs 30d</th>
                <th className="px-4 py-2.5 text-right font-medium">TVL</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className="border-b border-border/40 last:border-0">
                  <td className="px-4 py-2.5">
                    <span className="font-medium">{r.name}</span>{" "}
                    <span className="text-xs text-muted-foreground">{r.symbol ?? ""}</span>{" "}
                    <span className={`ml-1 rounded-full border px-1.5 py-px text-[10px] uppercase tracking-wide ${
                      r.kind === "network" ? "border-sky-500/40 text-sky-500" : "border-violet-500/40 text-violet-500"}`}>
                      {r.kind}
                    </span>
                  </td>
                  <td className="px-2 py-2.5">{priceText(r.price)}</td>
                  <td className="px-2 py-2.5">
                    {r.change_24h == null ? "—" : (
                      <span className={r.change_24h >= 0 ? "text-emerald-500" : "text-rose-500"}>
                        {r.change_24h >= 0 ? "+" : ""}{r.change_24h.toFixed(1)}%
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2.5">{bigUsd(r.mcap)}</td>
                  <td className="px-2 py-2.5">{bigUsd(r.fdv)}</td>
                  <td className="px-2 py-2.5">{bigUsd(r.fees_24h)}</td>
                  <td className="px-2 py-2.5">{bigUsd(r.revenue_24h)}</td>
                  <td className="px-2 py-2.5 font-medium">{r.pf == null ? "—" : `${r.pf.toFixed(1)}×`}</td>
                  <td className="px-2 py-2.5">{r.ps == null ? "—" : `${r.ps.toFixed(1)}×`}</td>
                  <td className="px-2 py-2.5"><Trend v={r.fee_trend_7d} /></td>
                  <td className="px-2 py-2.5"><Trend v={r.fee_trend_30d} /></td>
                  <td className="px-4 py-2.5 text-right">{bigUsd(r.tvl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Fees &amp; revenue: DefiLlama, aggregated across each brand&apos;s products (Sky files under Maker).
        Prices, market cap and FDV: CoinGecko. A multiple is only shown when the brand books at least $10K of
        fees a day — below that the annualized number is noise. Token unlocks are not shown: no reliable free
        schedule exists, and an invented one would be worse than none.
      </p>
    </section>
  );
}
