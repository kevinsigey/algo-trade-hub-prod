import { useEffect, useState } from "react";

import { getJson } from "@/lib/getJson";
import type { JournalResponse, JournalScore } from "@/lib/journal";
import { NEEDED } from "@/lib/journalView";

const SERIES: { forecaster: string; label: string }[] = [
  { forecaster: "oil_wti_15m", label: "WTI" },
  { forecaster: "oil_brent_15m", label: "Brent" },
  { forecaster: "natgas_15m", label: "Natural gas" },
];

interface Row {
  label: string;
  settled: number;
  needed: number;
  paired: number;
  model: number | null;
  market: number | null;
}

/** The current version of a forecaster is the one with the most settlements behind it. */
function rowsOf(scores: JournalScore[]): Row[] {
  return SERIES.flatMap(({ forecaster, label }) => {
    const mine = scores.filter((s) => s.forecaster === forecaster)
      .sort((a, b) => b.n_settled - a.n_settled)[0];
    if (!mine) return [];
    return [{
      label,
      settled: mine.n_settled,
      needed: NEEDED["15min"],
      paired: mine.n_baseline ?? mine.n_settled,
      model: mine.brier_on_baseline ?? mine.brier,
      market: mine.brier_baseline,
    }];
  });
}

function Bar({ label, value, max, tone }: { label: string; value: number | null; max: number; tone: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-14 shrink-0 text-[11px] text-slate-400">{label}</span>
      <div className="h-2.5 min-w-0 flex-1 rounded-sm bg-slate-800">
        {value != null && (
          <div className={`h-full rounded-sm ${tone}`} style={{ width: `${Math.max(2, (value / max) * 100)}%` }} />
        )}
      </div>
      <span className="w-10 shrink-0 text-right text-xs tabular-nums text-slate-200">
        {value == null ? "—" : value.toFixed(3)}
      </span>
    </div>
  );
}

/**
 * Are the 15-minute forecasts themselves any good? The journal grades every frozen forecast once its
 * window settles; this charts the model's Brier against Kalshi's own price on the same contracts
 * (the paired read), one block per market. Bars, not a table of decimals (Kevin, 2026-11-09).
 */
export function FifteenSettlements() {
  const [rows, setRows] = useState<Row[] | null>(null);

  useEffect(() => {
    let stop = false;
    getJson<JournalResponse>("/api/journal")
      .then((d) => { if (!stop) setRows(rowsOf(d.forecasters ?? [])); })
      .catch(() => { if (!stop) setRows([]); });
    return () => { stop = true; };
  }, []);

  if (!rows || rows.length === 0) return null;
  const max = Math.max(0.25, ...rows.flatMap((r) => [r.model ?? 0, r.market ?? 0]));
  return (
    <div aria-label="15-minute settlements scoring" className="mt-4">
      <div className="grid gap-4 sm:grid-cols-3">
        {rows.map((r) => {
          const ahead = r.model != null && r.market != null && r.model < r.market;
          const behind = r.model != null && r.market != null && r.model > r.market;
          return (
            <div key={r.label} className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold text-white">{r.label}</h3>
                <span className="text-xs tabular-nums text-slate-400">{r.settled.toLocaleString()} settled</span>
              </div>
              <div className="mt-2 space-y-1.5">
                <Bar label="Model" value={r.model} max={max} tone="bg-sky-400/80" />
                <Bar label="Market" value={r.market} max={max} tone="bg-slate-500/80" />
              </div>
              <p className="mt-2 text-xs text-slate-400">
                {ahead && <span className="font-medium text-emerald-300">model ahead</span>}
                {behind && <span className="font-medium text-rose-300">market ahead</span>}
                {!ahead && !behind && "not scored yet"}
                {r.paired > 0 ? ` · on ${r.paired.toLocaleString()} settlements both priced` : ""}
                {r.settled < r.needed ? ` · still short of the ${r.needed} the journal wants` : ""}
              </p>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Brier score: lower is better — it grades how close each side's stated chances were to what
        actually settled. The model's bar counts only the contracts Kalshi also priced, so the two
        bars grade the same windows.
      </p>
    </div>
  );
}
