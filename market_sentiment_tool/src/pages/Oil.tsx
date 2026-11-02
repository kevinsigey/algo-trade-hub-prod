import { useEffect, useState } from "react";

import { Chip, type Tone } from "@/components/Chip";
import { JournalDetail } from "@/components/JournalDetail";
import { getJson } from "@/lib/getJson";
import { NextRelease } from "@/components/NextRelease";
import { Stat } from "@/components/Stat";
import type { JournalResponse } from "@/lib/journal";
import { STATUS_WORDS, skillText, totals, viewRows, type Status } from "@/lib/journalView";

/**
 * /oil: the journal's WTI forecasts, nothing else -- the same shape as /cpi.
 *
 * The journal locks each day's KXWTI forecast 2 hours before the 14:30 ET ICE
 * settlement, beside the Kalshi price, and scores it after, so this page is
 * those rows and the shared detail view. Nothing is computed here.
 */
const STATUS_TONE: Record<Status, Tone> = { waiting: "quiet", early: "quiet", ahead: "good", behind: "bad", promoted: "good" };
const OIL = new Set(["oil_wti", "oil_wti_cautious", "kalshi_implied_oil", "baseline_persistence_oil"]);

export default function Oil() {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<JournalResponse>("/api/journal").then(setData).catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="p-8 text-rose-300">Oil forecasts unavailable: {error}</div>;
  if (!data) return <div className="p-8 text-slate-400">Loading…</div>;

  const rows = viewRows(data.forecasters.filter((s) => OIL.has(s.forecaster)));
  const t = totals(rows);

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6 md:p-8">
      <header>
        <h1 className="text-3xl font-bold text-white">WTI crude oil</h1>
        <p className="mt-2 text-slate-400">Our forecast for each day's ICE WTI settlement, locked in 2 hours before the 14:30 ET settlement, beside the Kalshi price.</p>
      </header>

      <NextRelease family="oil" title="Next settlement" />

      <section aria-label="Totals" className="grid gap-3 sm:grid-cols-2">
        <Stat value={t.frozen} label="forecasts locked in" />
        <Stat value={t.scored} label="scored so far" />
      </section>

      {t.frozen === 0 && <p className="text-slate-400">Nothing locked in yet. The next one locks 2 hours before the settlement.</p>}

      {rows.map((row) => (
        <section key={row.key} aria-label={row.label} className="border-t border-slate-800 pt-4">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="text-lg font-semibold text-slate-100">{row.label}</h2>
            <div className="flex items-center gap-3">
              <span className="text-lg tabular-nums text-slate-100">{skillText(row.skill)}</span>
              <Chip tone={STATUS_TONE[row.status]}>{STATUS_WORDS[row.status]}</Chip>
            </div>
          </div>
          <JournalDetail row={row} />
        </section>
      ))}
    </div>
  );
}
