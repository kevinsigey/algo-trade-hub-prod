import { useEffect, useState } from "react";

import { LeagueTable } from "@/components/LeagueTable";
import { SkillOverTime } from "@/components/SkillOverTime";
import { WeatherPanel } from "@/components/WeatherPanel";
import { PreJournalContext } from "@/components/PreJournalContext";
import { Chip } from "@/components/Chip";
import { getJson } from "@/lib/getJson";
import type { JournalResponse, SeriesResponse } from "@/lib/journal";
import { viewRows } from "@/lib/journalView";
import { beatingCount, league } from "@/lib/league";

/**
 * /journal: the product. Every predictor's locked-in, scored record, measured against what it competes with.
 *
 * Header strip: the three numbers. Then the league table, grouped, one row per predictor, with edge
 * where positive always means "beats it". Over time, weather and the waiting list are one tab away.
 * Nothing here computes a score: the server does, and `lib/league.ts` only changes the sign of the gap.
 */

type Tab = "league" | "time" | "weather" | "waiting";

function Number_({ value, label, hint }: { value: string | number; label: string; hint?: string }) {
  return (
    <div className="border border-border bg-card px-4 py-3">
      <div className="font-display text-5xl leading-none tracking-wide text-foreground tabular-nums">{value}</div>
      <div className="mt-1 text-sm text-foreground">{label}</div>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export default function Journal() {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [series, setSeries] = useState<SeriesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backtests, setBacktests] = useState(false);
  const [tab, setTab] = useState<Tab>("league");

  useEffect(() => {
    Promise.all([
      getJson<JournalResponse>("/api/journal"),
      getJson<SeriesResponse>("/api/journal/series"),
    ]).then(([journal, serie]) => {
      setData(journal);
      setSeries(serie);
    }).catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="p-8">
        <div className="border border-pr-loss bg-card p-4 text-sm text-foreground">
          <p className="font-semibold">Journal unavailable</p>
          <p className="mt-1 text-muted-foreground">{error}</p>
        </div>
      </div>
    );
  }
  if (!data || !series) return <div className="p-8 text-muted-foreground">Loading journal…</div>;

  const rows = viewRows(data.forecasters);
  const table = league(rows);
  const waiting = table.filter((r) => r.status === "waiting");
  // The server's numbers, never a sum over the rows (spec §3 step 4, §10: headline stats aggregate only
  // post-calibration forecasters, which `scoring.headline()` enforces).
  const h = data.headline;
  const { beating, measured } = beatingCount(table);

  const handleTabKeyDown = (e: React.KeyboardEvent<HTMLElement>, tabs: Tab[]) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (tabs.indexOf(tab) + step + tabs.length) % tabs.length;
    setTab(tabs[next]);
    (e.currentTarget.parentElement?.children[next] as HTMLElement | undefined)?.focus();
  };

  const tabs: [Tab, string][] = [
    ["league", "League table"],
    ["time", "Over time"],
    ["weather", "Weather"],
    ["waiting", `Waiting (${waiting.length})`],
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-4 md:p-8">
      <header>
        <h1 className="font-display text-5xl uppercase tracking-wide text-foreground">Prediction Journal</h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          Every forecast is locked in before the event and scored after. No orders are placed.
        </p>
      </header>

      <section aria-label="Totals" className="grid gap-3 sm:grid-cols-3">
        <Number_ value={h.frozen_calibrated} label="forecasts locked in" />
        <Number_ value={h.settled_calibrated} label="scored so far" />
        <Number_
          value={measured === 0 ? "none yet" : `${beating} of ${measured}`}
          label="beating what they are measured against"
          hint="Counted only when the whole 95% interval is above zero."
        />
      </section>

      <div role="tablist" aria-label="Journal views" className="-mb-4 flex gap-1 overflow-x-auto border-b border-border">
        {tabs.map(([id, text]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
            onKeyDown={(e) => handleTabKeyDown(e, tabs.map(([t]) => t))}
            className={`whitespace-nowrap border-b-2 px-4 py-2 text-sm font-semibold ${tab === id ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          >
            {text}
          </button>
        ))}
      </div>

      <div className={tab === "league" ? "" : "hidden"}>
        <LeagueTable rows={table} />
      </div>

      <div className={tab === "time" ? "" : "hidden"}><SkillOverTime series={series?.series ?? []} /></div>

      <div className={tab === "weather" ? "" : "hidden"}><WeatherPanel /></div>

      {waiting.length > 0 ? (
        <section aria-label="Waiting" className={tab === "waiting" ? "" : "hidden"}>
          <ul className="flex flex-wrap gap-2">
            {waiting.map((row) => (
              <li key={row.id} className="flex items-center gap-2">
                <Chip title={row.primary.key}>{row.label}</Chip>
                {row.primary.experimental && <span className="text-xs text-muted-foreground">Experimental</span>}
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <section aria-label="Waiting" className={tab === "waiting" ? "" : "hidden"}>
          <p className="py-8 text-center text-muted-foreground">No forecasters waiting to be scored.</p>
        </section>
      )}

      <details onToggle={(e) => setBacktests((e.currentTarget as HTMLDetailsElement).open)} className="border-t border-border pt-4">
        <summary className="cursor-pointer text-sm text-muted-foreground">Past backtests (not counted)</summary>
        <div className="mt-3">{backtests && <PreJournalContext />}</div>
      </details>
    </div>
  );
}
