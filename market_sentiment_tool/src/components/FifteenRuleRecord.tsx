import { useEffect, useState } from "react";

import { getJson } from "@/lib/getJson";

interface Stats { n: number; net_per_contract: number | null; total: number; win_rate: number | null; low95: number | null; ready: boolean; windows?: number }
interface Trade { series: string; target: string; frozen_at: string; side: "yes" | "no"; cost: number; model: number; outcome: number; pnl: number }
interface OffsetStat { offset_min: number; windows: number; priced: number; mean_edge_net: number | null; n: number; net_per_contract: number | null; win_rate: number | null; mean_move_to_settle_bps: number | null; mean_move_to_60m_bps: number | null }
interface Bar { basis: string; trades: number; ready_trades: number; ready: boolean; low95: number | null; windows?: number; pending?: number; control?: { basis: string; trades: number; ready: boolean; low95: number | null } }
interface RuleRecord {
  rule: string; prereg_at: string; ready_trades: number; replay: Stats; forward: Stats;
  pending: number; recent: Trade[]; unavailable?: boolean;
  by_session?: { open: Stats; closed: Stats };
  gate?: { rule: string; forward: Stats; by_session?: { open: Stats; closed: Stats } };
  bar?: Bar;
  decisions?: { recorded: number; buy: number; skip: number; by_reason: Record<string, number> };
  offsets?: { by_offset: OffsetStat[] };
}

const REASON_LABELS: [string, string][] = [
  ["no_edge", "no edge"], ["no_quote", "no quote"], ["no_prediction", "no prediction"],
  ["stale_tape", "stale tape"], ["halt", "halt"],
];

const c = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}¢`;

function etShort(iso: string): string {
  return new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/**
 * The 15-minute trade rule's paper record (Kevin, 2026-11-05: "develop its own winning strategy that can be
 * copied easily, and once it's legitimate we can automate it"). One plain rule, fixed before its forward
 * record began; only trades after that count toward the go-live bar. Since the 2026-11-09 amendment the
 * bar counts the fee-gated record; the original gross-edge record stays on the panel as the control. The
 * replay that suggested the rule is shown apart, because a rule always looks good on the data it was
 * picked from.
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
  const bar = rec.bar;
  const gf = rec.gate?.forward;
  const pct = Math.min(100, ((bar?.trades ?? f.n) / rec.ready_trades) * 100);
  return (
    <details className="group mt-5 border-t border-slate-800 pt-4">
      <summary className="cursor-pointer text-sm font-semibold text-slate-200 hover:text-white">
        The trade rule, on paper{" "}
        <span className="font-normal text-slate-400">· {bar ? `${bar.trades}/${rec.ready_trades} gated trades so far` : `${f.n}/${rec.ready_trades} trades so far`}</span>
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
        <div className="h-1.5 max-w-sm rounded-full bg-slate-800" role="img" aria-label={bar ? `${bar.trades} of ${rec.ready_trades} settled gated trades` : `${f.n} of ${rec.ready_trades} forward trades`}>
          <div className="h-full rounded-full bg-emerald-400/80" style={{ width: `${pct}%` }} />
        </div>
        {bar ? (
          <p className="mt-1 text-xs text-slate-400">
            {bar.trades} of {rec.ready_trades} settled gated trades{bar.windows != null ? ` in ${bar.windows} separate 15-minute windows` : ""}
            {gf ? <> — {c(gf.net_per_contract ?? 0)} a contract, win rate {Math.round((gf.win_rate ?? 0) * 100)}%</> : ""}. Copyable once the gated record has {rec.ready_trades} and is still ahead at the
            low end of its 95% range{bar.low95 != null ? ` (now ${c(bar.low95)})` : ""}.{bar.ready ? " It has cleared that bar." : ""}
            {(bar.pending ?? rec.pending) ? ` ${(bar.pending ?? rec.pending)} waiting to settle.` : ""}
          </p>
        ) : (
          <p className="mt-1 text-xs text-slate-400">
            {f.n} of {rec.ready_trades} forward trades{f.windows != null ? ` in ${f.windows} separate 15-minute windows` : ""}. Copyable once it has {rec.ready_trades} and is still ahead at the
            low end of its 95% range{f.low95 != null ? ` (now ${c(f.low95)})` : ""}.{f.ready ? " It has cleared that bar." : ""}
            {rec.pending ? ` ${rec.pending} waiting to settle.` : ""}
          </p>
        )}
      </div>
      {rec.by_session && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-slate-300">Trading hours vs closed hours</p>
          <table className="mt-1 w-full max-w-md text-xs tabular-nums">
            <thead><tr className="text-left text-slate-500">
              <th className="pb-1 pr-3 font-medium"></th>
              <th className="pb-1 pr-3 font-medium text-right">Trades</th>
              <th className="pb-1 pr-3 font-medium text-right">Per contract</th>
              <th className="pb-1 text-right font-medium">Win rate</th>
            </tr></thead>
            <tbody className="divide-y divide-slate-800/70 text-slate-300">
              <tr>
                <td className="py-1 pr-3 text-slate-200">When futures were trading</td>
                <td className="py-1 text-right">{rec.by_session.open.n}</td>
                <td className="py-1 text-right">{rec.by_session.open.net_per_contract == null ? "—" : c(rec.by_session.open.net_per_contract)}</td>
                <td className="py-1 text-right">{rec.by_session.open.win_rate == null ? "—" : `${Math.round(rec.by_session.open.win_rate * 100)}%`}</td>
              </tr>
              <tr>
                <td className="py-1 pr-3 text-slate-200">When futures were closed</td>
                <td className="py-1 text-right">{rec.by_session.closed.n}</td>
                <td className="py-1 text-right">{rec.by_session.closed.net_per_contract == null ? "—" : c(rec.by_session.closed.net_per_contract)}</td>
                <td className="py-1 text-right">{rec.by_session.closed.win_rate == null ? "—" : `${Math.round(rec.by_session.closed.win_rate * 100)}%`}</td>
              </tr>
            </tbody>
          </table>
          <p className="mt-1 text-xs text-slate-400">A real edge should hold while futures trade; wins only in closed hours can come from stale prices.</p>
        </div>
      )}
      {rec.bar ? (
        <p className="mt-3 text-xs text-slate-400">
          On the original gross-edge record, kept as a control:{" "}
          {f.n === 0
            ? "no forward trades yet."
            : `${f.n} trades, ${c(f.net_per_contract ?? 0)} a contract, win rate ${Math.round((f.win_rate ?? 0) * 100)}%.`}
        </p>
      ) : rec.gate?.forward && (
        <p className="mt-3 text-xs text-slate-400">
          With the fee netted out of the edge test (the live gate):{" "}
          {rec.gate.forward.n === 0
            ? "no forward trades clear it yet."
            : `${rec.gate.forward.n} trades, ${c(rec.gate.forward.net_per_contract ?? 0)} a contract, win rate ${Math.round((rec.gate.forward.win_rate ?? 0) * 100)}%.`}
        </p>
      )}
      {rec.decisions && rec.decisions.recorded > 0 && (
        <p className="mt-1 text-xs text-slate-400">
          {rec.decisions.recorded} windows on record: {rec.decisions.buy} buys, {rec.decisions.skip} skipped
          {REASON_LABELS.some(([k]) => rec.decisions!.by_reason[k]) &&
            ` (${REASON_LABELS.filter(([k]) => rec.decisions!.by_reason[k]).map(([k, label]) => `${label} ${rec.decisions!.by_reason[k]}`).join(", ")})`}
          .
        </p>
      )}
      {(() => {
        const best = (rec.offsets?.by_offset ?? [])
          .filter((o) => o.n >= 10 && o.net_per_contract != null)
          .sort((a, b) => (b.net_per_contract ?? 0) - (a.net_per_contract ?? 0))[0];
        return best ? (
          <p className="mt-1 text-xs text-slate-400">
            Best entry minute so far: minute {best.offset_min} of the window ({best.n} priced entries, {c(best.net_per_contract ?? 0)} a contract after fees).
          </p>
        ) : null;
      })()}
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
