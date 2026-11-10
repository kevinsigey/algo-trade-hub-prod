import { useEffect, useState } from "react";

import BacktestsTab from "@/components/BacktestsTab";
import JournalSports from "@/components/JournalSports";
import { LeagueTable } from "@/components/LeagueTable";
import { ModelCards } from "@/components/ModelCards";
import { SkillOverTime } from "@/components/SkillOverTime";
import { WeatherPanel } from "@/components/WeatherPanel";
import { PreJournalContext } from "@/components/PreJournalContext";
import { Chip } from "@/components/Chip";
import { getJson } from "@/lib/getJson";
import type { JournalResponse, SeriesResponse } from "@/lib/journal";
import { viewRows } from "@/lib/journalView";
import { beatingCount, league } from "@/lib/league";

const STORAGE_KEY = "atr:tracker-show-all";

function readShowAll(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeShowAll(value: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
  } catch {
    // ignore
  }
}

/**
 * /journal: the Model Tracker (renamed from "Journal" in Kevin's 2026-11-01 redesign; the route
 * stays /journal so bookmarks keep working). Every predictor's locked-in, scored record, measured
 * against what it competes with.
 *
 * First page: one card per predictor -- headline edge first, the record behind a click. The league
 * table keeps its own tab with its own metrics, and Over time stays a separate tab: the redesign
 * keeps the three views distinct rather than merging them. Header strip: the three numbers.
 * Nothing here computes a score: the server does, and `lib/league.ts` only changes the sign of the gap.
 */

type Tab = "models" | "league" | "time" | "weather" | "sports" | "waiting" | "backtests";

function Number_({ value, label, hint }: { value: string | number; label: string; hint?: string }) {
  return (
    <div className="border border-border bg-card px-4 py-3">
      <div className="font-display text-5xl leading-none tracking-wide text-foreground tabular-nums">{typeof value === "number" ? value.toLocaleString("en-US") : value}</div>
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
  // The merged backtest pages (/scoreboard, /models) redirect to ?view=backtests.
  const [tab, setTab] = useState<Tab>(() =>
    new URLSearchParams(window.location.search).get("view") === "backtests" ? "backtests" : "models",
  );
  const [showAll, setShowAll] = useState(readShowAll);

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

  const allRows = viewRows(data.forecasters);
  const fullCount = allRows.length;

  // Filter only for Models and Journal tabs; Waiting, Over time, Weather, Sports, Backtests
  // and header numbers use all rows.
  const filteredRows = showAll
    ? allRows
    : allRows.filter((r) => !r.forecaster.startsWith("baseline_") && r.scored >= 50);

  // Fallback: if filtering hides everything, show all scored rows (preserves old behavior for
  // test fixtures and edge cases where no model has 50+ settled).
  const displayRows = filteredRows.length > 0 ? filteredRows : allRows.filter((r) => r.scored > 0);

  const table = league(displayRows);
  const allTable = league(allRows);
  const waiting = allTable.filter((r) => r.status === "waiting");
  // The server's numbers, never a sum over the rows (spec §3 step 4, §10: headline stats aggregate only
  // post-calibration forecasters, which `scoring.headline()` enforces).
  const h = data.headline;
  const { beating, measured } = beatingCount(allTable);

  const handleTabKeyDown = (e: React.KeyboardEvent<HTMLElement>, tabs: Tab[]) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (tabs.indexOf(tab) + step + tabs.length) % tabs.length;
    setTab(tabs[next]);
    (e.currentTarget.parentElement?.children[next] as HTMLElement | undefined)?.focus();
  };

  const tabs: [Tab, string][] = [
    ["models", "Models"],
    ["league", "Journal"],
    ["time", "Over time"],
    ["weather", "Weather"],
    ["sports", "Sports"],
    ["waiting", `Waiting (${waiting.length})`],
    ["backtests", "Backtests"],
  ];

  const showFilterButton = tab === "models" || tab === "league";

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-4 md:p-8">
      <header>
        <h1 className="font-display text-5xl uppercase tracking-wide text-foreground">Model Tracker</h1>
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

      {showFilterButton && (
        <button
          type="button"
          aria-pressed={showAll}
          onClick={() => {
            const next = !showAll;
            setShowAll(next);
            writeShowAll(next);
          }}
          className="mb-4 text-sm text-muted-foreground hover:text-foreground underline"
        >
          {showAll ? `Show the main models only` : `Show all ${fullCount} models (baselines and early ones)`}
        </button>
      )}

      <div className={tab === "models" ? "" : "hidden"}>
        <ModelCards rows={table} series={series?.series ?? []} />
      </div>

      <div className={tab === "league" ? "" : "hidden"}>
        <LeagueTable rows={table} />
      </div>

      <div className={tab === "time" ? "" : "hidden"}><SkillOverTime series={series?.series ?? []} /></div>

      <div className={tab === "weather" ? "" : "hidden"}><WeatherPanel /></div>

      <div className={tab === "sports" ? "" : "hidden"}><JournalSports scores={data.forecasters} /></div>

      {/* Mounted only when open: its text is a second board, and the page's word
          budget counts what is mounted. */}
      {tab === "backtests" && <BacktestsTab />}

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
