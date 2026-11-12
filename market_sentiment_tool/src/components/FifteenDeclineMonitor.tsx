import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";

/** One model's settled trades for a day and market, P&L per trade after fees. */
export interface DeclineCell { trades: number; pnl_per_trade: number | null }
export interface DeclineRow { day: string; series: string; live: DeclineCell; blend: DeclineCell; volregime: DeclineCell }

type Model = "live" | "blend" | "volregime";
type SortKey = "day" | "series" | `${Model}:trades` | `${Model}:pnl`;
// The decisions table's v1 rule: the live gate for oil and gas, a record only for metals (live_gate=False).
const MODELS: [Model, string][] = [["live", "v1 rule"], ["blend", "Blend"], ["volregime", "Vol-regime"]];

const cent1 = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}¢`;

function read(r: DeclineRow, key: SortKey): string | number | null {
  if (key === "day" || key === "series") return r[key];
  const [model, field] = key.split(":") as [Model, "trades" | "pnl"];
  return field === "trades" ? r[model].trades : r[model].pnl_per_trade;
}

/** Day by day, per market: the live rule, the blend and the volatility-regime challenger side by side,
 * so a decline shows up the day it starts. Read only; sorted by any column. */
export function FifteenDeclineMonitor({ rows }: { rows: DeclineRow[] }) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "day", desc: true });
  const ordered = useMemo(() => [...rows].sort((a, b) => {
    const x = read(a, sort.key), y = read(b, sort.key);
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    const order = typeof x === "string" ? x.localeCompare(String(y)) : x - Number(y);
    return sort.desc ? -order : order;
  }), [rows, sort]);
  if (rows.length === 0) return <p className="text-xs text-slate-400">No decisions in the last two weeks yet.</p>;
  const head = (key: SortKey, label: string, align = "text-right") => (
    <th key={key} scope="col" aria-sort={sort.key === key ? (sort.desc ? "descending" : "ascending") : "none"}
        className={`pb-1 pr-3 font-medium ${align}`}>
      <button type="button" onClick={() => setSort({ key, desc: sort.key === key ? !sort.desc : key !== "series" })}
              className="inline-flex items-center gap-0.5 rounded hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
        {label}
        {sort.key === key && (sort.desc ? <ArrowDown className="h-3 w-3" aria-hidden="true" /> : <ArrowUp className="h-3 w-3" aria-hidden="true" />)}
      </button>
    </th>
  );
  return (
    <div className="max-h-96 overflow-auto">
      <table aria-label="15-minute decline monitor" className="w-full max-w-3xl text-xs tabular-nums">
        <thead className="sticky top-0 bg-slate-900">
          <tr className="text-left text-slate-500">
            <th colSpan={2} />
            {MODELS.map(([m, label]) => <th key={m} colSpan={2} scope="colgroup" className="pr-3 text-right font-medium text-slate-400">{label}</th>)}
          </tr>
          <tr className="text-left text-slate-500">
            {head("day", "Day (ET)", "text-left")}
            {head("series", "Market", "text-left")}
            {MODELS.flatMap(([m]) => [head(`${m}:trades`, "Trades"), head(`${m}:pnl`, "Per trade")])}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/70 text-slate-300">
          {ordered.map((r) => (
            <tr key={`${r.day}-${r.series}`}>
              <td className="py-1 pr-3 text-slate-200">{r.day.slice(5)}</td>
              <td className="py-1 pr-3">{r.series}</td>
              {MODELS.flatMap(([m]) => {
                const c = r[m];
                return [
                  <td key={`${m}-n`} className="py-1 pr-3 text-right">{c.trades}</td>,
                  <td key={`${m}-p`} className={`py-1 pr-3 text-right ${c.pnl_per_trade == null ? "text-slate-500" : c.pnl_per_trade >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                    {c.pnl_per_trade == null ? "—" : cent1(c.pnl_per_trade)}
                  </td>,
                ];
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
