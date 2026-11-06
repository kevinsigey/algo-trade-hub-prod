import { useEffect, useState } from "react";

import { getJson } from "@/lib/getJson";
import { cents } from "@/lib/oilFees";

export interface StrikeRecord {
  frozen: number; settled: number; hits: number;
  hit_rate: number | null; net_per_contract: number | null;
  backtest: { events: number; picks: number; hits: number; avg_model: number | null; avg_cost: number | null;
              net_per_contract: number | null } | null;
}

const signedCents = (v: number) => `${v >= 0 ? "+" : "−"}${cents(Math.abs(v))}`;

/** How the pick has done: the rule replayed over frozen quotes, and its own graded picks since. */
export function StrikeRecordLine() {
  const [rec, setRec] = useState<StrikeRecord | null>(null);
  useEffect(() => {
    let stop = false;
    getJson<StrikeRecord>("/api/oil/itm-record").then((r) => { if (!stop) setRec(r); }).catch(() => {});
    return () => { stop = true; };
  }, []);
  if (!rec || typeof rec.frozen !== "number") return null;
  const replay = rec.backtest;
  return (
    <div className="mt-2 space-y-0.5 text-[13px] text-slate-300">
      {replay && replay.picks > 0 && replay.net_per_contract != null && replay.avg_model != null && (
        <p>
          On the live feed so far: <span className="tabular-nums">{replay.hits} of {replay.picks}</span> picks hit
          ({Math.round((replay.hits / replay.picks) * 100)}%, the model said {Math.round(replay.avg_model * 100)}%),{" "}
          <span className={`font-semibold tabular-nums ${replay.net_per_contract >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
            {signedCents(replay.net_per_contract)} per contract after fees
          </span>.
          {replay.net_per_contract < 0 && " This signal hasn't made money so far."}
        </p>
      )}
      {rec.settled > 0 && rec.net_per_contract != null && (
        <p>
          Picks graded since this went up: <span className="tabular-nums">{rec.hits} of {rec.settled}</span> hit,{" "}
          <span className={`font-semibold tabular-nums ${rec.net_per_contract >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
            {signedCents(rec.net_per_contract)} per contract
          </span>.
        </p>
      )}
    </div>
  );
}

