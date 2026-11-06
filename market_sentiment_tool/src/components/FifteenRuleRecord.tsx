import { useEffect, useState } from "react";

import { getJson } from "@/lib/getJson";

interface Stats { n: number; net_per_contract: number | null; total: number; win_rate: number | null; low95: number | null; ready: boolean }
interface Trade { series: string; target: string; frozen_at: string; side: "yes" | "no"; cost: number; model: number; outcome: number; pnl: number }
interface RuleRecord {
  rule: string; prereg_at: string; ready_trades: number; replay: Stats; forward: Stats;
  pending: number; recent: Trade[]; unavailable?: boolean;
}

const c = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}¢`;

function etShort(iso: string): string {
  return new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/**
 * The 15-minute trade rule's paper record (Kevin, 2026-11-05: "develop its own winning strategy that can be
 * copied easily, and once it's legitimate we can automate it"). One plain rule, fixed before its forward
 * record began; only trades after that count toward the go-live bar. The replay that suggested the rule is
 * shown apart, because a rule always looks good on the data it was picked from.
 */
export function FifteenRuleRecord() {
  const [rec, setRec] = useState<RuleRecord | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let stop = false;
    getJson<RuleRecord>("/api/oil/fifteen-rule")
      .then((r) => { if (!stop) setRec(r); })
      .catch(() => { if (!stop) setFailed(true); });
    return () => { stop = true; };
  }, []);

  if (failed) return <p className="mt-4 text-sm text-slate-400">The trade rule's record is unavailable right now.</p>;
  // A reply without the record's shape (an older server, a proxy page) hides the box rather than crash the page.
  if (!rec?.forward || !rec.replay) return null;
  const f = rec.forward;
  const pct = Math.min(100, (f.n / rec.ready_trades) * 100);
  return (
    <details className="group mt-5 border-t border-slate-800 pt-4">
      <summary className="cursor-pointer text-sm font-semibold text-slate-200 hover:text-white">
        The trade rule, on paper{" "}
        <span className="font-normal text-slate-400">· {f.n}/{rec.ready_trades} trades so far</span>
      </summary>
      <p className="mt-1 max-w-[70ch] text-sm text-slate-300">{rec.rule}</p>
      <div className="mt-3 flex flex-wrap items-baseline gap-x-6 gap-y-1 tabular-nums">
        {f.n === 0 ? (
          <span className="text-sm text-slate-400">No forward trades yet. The record starts {etShort(rec.prereg_at)} ET.</span>
        ) : (
          <>
            <span className={`text-lg font-semibold ${(f.net_per_contract ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
              {c(f.net_per_contract ?? 0)} a contract
            </span>
            <span className="text-sm text-slate-400">win rate {Math.round((f.win_rate ?? 0) * 100)}% · {f.total >= 0 ? "+" : "−"}${Math.abs(f.total).toFixed(2)} on one contract each</span>
          </>
        )}
      </div>
      <div className="mt-2">
        <div className="h-1.5 max-w-sm rounded-full bg-slate-800" role="img" aria-label={`${f.n} of ${rec.ready_trades} forward trades`}>
          <div className="h-full rounded-full bg-emerald-400/80" style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-1 text-xs text-slate-400">
          {f.n} of {rec.ready_trades} forward trades. Copyable once it has {rec.ready_trades} and is still ahead at the
          low end of its 95% range{f.low95 != null ? ` (now ${c(f.low95)})` : ""}.{f.ready ? " It has cleared that bar." : ""}
          {rec.pending ? ` ${rec.pending} waiting to settle.` : ""}
        </p>
      </div>
      {rec.recent.length > 0 && (
        <table className="mt-3 w-full max-w-xl text-xs tabular-nums">
          <thead><tr className="text-left text-slate-500">
            <th className="pb-1 pr-3 font-medium">Window</th><th className="pb-1 pr-3 font-medium">Market</th>
            <th className="pb-1 pr-3 font-medium">Bought</th><th className="pb-1 text-right font-medium">Result</th>
          </tr></thead>
          <tbody className="divide-y divide-slate-800/70 text-slate-300">
            {rec.recent.slice(0, 6).map((t) => (
              <tr key={`${t.series}-${t.target}`}>
                <td className="py-1 pr-3">{etShort(t.frozen_at)}</td>
                <td className="py-1 pr-3">{t.series}</td>
                <td className="py-1 pr-3">{t.side.toUpperCase()} at {Math.round(t.cost * 100)}¢ (model {Math.round((t.side === "yes" ? t.model : 1 - t.model) * 100)}%)</td>
                <td className={`py-1 text-right ${t.pnl >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{c(t.pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-2 text-xs text-slate-500">
        Replay before the rule was fixed: {rec.replay.n} trades, {rec.replay.net_per_contract == null ? "—" : c(rec.replay.net_per_contract)} a
        contract. Fills at the quoted price are assumed; paper only.
      </p>
    </details>
  );
}
