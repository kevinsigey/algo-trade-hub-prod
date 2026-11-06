import { useEffect, useState } from "react";

import { getJson } from "@/lib/getJson";
import { pct, type SniperVerdict } from "@/lib/crypto";

/** The crypto sniper's closed record: a worker that stopped on June 2, 2026, graded once. A record, not a signal. */
export function SniperRecord() {
  const [verdict, setVerdict] = useState<SniperVerdict | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    getJson<SniperVerdict>("/api/crypto/sniper-verdict").then(setVerdict).catch(() => setUnavailable(true));
  }, []);

  if (unavailable) {
    return <p className="text-sm text-muted-foreground">The closed record has not been graded yet.</p>;
  }
  if (!verdict?.population || !verdict.overall) return null; // a partial reply hides the record rather than crash
  const p = verdict.population;
  return (
    <div className="rounded-2xl border border-border/70 bg-card p-5 shadow-sm">
      <div className="grid gap-4 sm:grid-cols-4">
        <div>
          <p className="text-2xl font-semibold tabular-nums">{p.graded.toLocaleString()}</p>
          <p className="text-sm text-muted-foreground">rows graded (of {p.grading_population.toLocaleString()} archived)</p>
        </div>
        <div>
          <p className="text-2xl font-semibold tabular-nums">{pct(verdict.overall.hit_rate)}</p>
          <p className="text-sm text-muted-foreground">hit rate on the evaluator's next-hour rule</p>
        </div>
        <div>
          <p className="text-2xl font-semibold tabular-nums">{verdict.overall.brier_score?.toFixed(3) ?? "—"}</p>
          <p className="text-sm text-muted-foreground">shadow Brier (0.250 is a coin flip)</p>
        </div>
        <div>
          <p className="text-2xl font-semibold tabular-nums">{pct(p.dead_zone_share)}</p>
          <p className="text-sm text-muted-foreground">of rows sat in the model's dead zone</p>
        </div>
      </div>
      <div className="mt-4 space-y-1 text-sm">
        {(["BTC", "ETH"] as const).map((asset) => {
          const a = verdict.by_asset[asset];
          return a ? (
            <p key={asset} className="tabular-nums">
              {asset}: {a.count.toLocaleString()} graded · hit rate {pct(a.hit_rate)} · Brier{" "}
              {a.brier_score?.toFixed(3) ?? "—"}
            </p>
          ) : null;
        })}
      </div>
      <p className="mt-4 text-xs text-muted-foreground">
        The worker ran Apr 8 – Jun 2, 2026 against the Kalshi demo API; every signal's execution was skipped or
        blocked. Graded once on {verdict.graded_on} with the hub's existing shadow evaluator ({verdict.price_source}{" "}
        hourly closes) — a closed record, never refreshed. {verdict.method}
      </p>
    </div>
  );
}

