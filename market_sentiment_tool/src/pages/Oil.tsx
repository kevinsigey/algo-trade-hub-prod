import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Chip, type Tone } from "@/components/Chip";
import { JournalDetail } from "@/components/JournalDetail";
import { getJson } from "@/lib/getJson";
import ChokepointsMap from "@/components/ChokepointsMap";
import { NextRelease } from "@/components/NextRelease";
import { Stat } from "@/components/Stat";
import type { FrozenForecast, JournalFeed, JournalResponse } from "@/lib/journal";
import { STATUS_WORDS, skillText, totals, viewRows, type Status, type ViewRow } from "@/lib/journalView";

/**
 * /oil: the WTI dashboard (Kevin's redesign, 2026-11-02).
 *
 * The hero is the NEXT HOUR's call: the frozen strike ladder for the upcoming
 * KXWTIH event -- our probability above each strike beside Kalshi's, the level
 * where our probability crosses 50%, and the strikes where we disagree with
 * the market most. That is the guide for watching the hourly market. Below it,
 * the scoring and settlements record (daily and hourly journal rows, the same
 * shared detail view as before) sits behind dropdowns. The page re-reads
 * everything every 10 minutes; the ladder itself refreezes about 65 minutes
 * before each hour. Nothing is computed here that the journal did not freeze:
 * the ladder is the frozen forecasts, read back.
 */
const STATUS_TONE: Record<Status, Tone> = { waiting: "quiet", early: "quiet", ahead: "good", behind: "bad", promoted: "good" };
const OIL = new Set(["oil_wti", "oil_wti_cautious", "kalshi_implied_oil", "baseline_persistence_oil"]);
const OIL_HOURLY = new Set(["oil_wti_hourly", "oil_wti_hourly_cautious", "kalshi_implied_oil_hourly", "baseline_persistence_oil_hourly"]);
const REFRESH_MS = 10 * 60 * 1000;

const MONTHS: Record<string, number> = { JAN: 0, FEB: 1, MAR: 2, APR: 3, MAY: 4, JUN: 5, JUL: 6, AUG: 7, SEP: 8, OCT: 9, NOV: 10, DEC: 11 };

interface LadderRow { strike: number; ours: number; market: number | null }

/** "KXWTIH-26NOV0214" -> "Nov 2 · 2 PM ET" (the suffix hour is the ET settle hour). */
function eventLabel(event: string): string {
  const m = event.match(/-(\d{2})([A-Z]{3})(\d{2})(\d{2})$/);
  if (!m) return event;
  const [, , mon, day, hh] = m;
  const month = new Date(2000, MONTHS[mon] ?? 0, 1).toLocaleString("en-US", { month: "short" });
  const hour = Number(hh);
  return `${month} ${Number(day)} · ${hour % 12 === 0 ? 12 : hour % 12} ${hour < 12 ? "AM" : "PM"} ET`;
}

/** The strike where P(above) crosses 50%, interpolated; null when the ladder never crosses. */
function crossing(rows: LadderRow[], pick: (r: LadderRow) => number | null): number | null {
  for (let i = 0; i + 1 < rows.length; i++) {
    const a = pick(rows[i]);
    const b = pick(rows[i + 1]);
    if (a === null || b === null) continue;
    if (a >= 0.5 && b <= 0.5 && a !== b) {
      return rows[i].strike + ((a - 0.5) / (a - b)) * (rows[i + 1].strike - rows[i].strike);
    }
  }
  return null;
}

function NextHourHero({ ours, market }: { ours: JournalFeed | null; market: JournalFeed | null }) {
  const forecasts = ours?.forecasts ?? [];
  // The next hour is the most recently frozen event: freezes land ~65 minutes
  // before each hour, so the freshest event group is the upcoming settle.
  const events = new Map<string, FrozenForecast[]>();
  for (const f of forecasts) {
    const event = f.target.replace(/^kalshi:/, "").replace(/-T[\d.]+$/, "");
    events.set(event, [...(events.get(event) ?? []), f]);
  }
  let event: string | null = null;
  let group: FrozenForecast[] = [];
  for (const [e, g] of events) {
    if (g.length && (event === null || Math.max(...g.map((f) => Date.parse(f.frozen_at))) > Math.max(...group.map((f) => Date.parse(f.frozen_at))))) {
      event = e;
      group = g;
    }
  }
  if (!event || group.length === 0) {
    return (
      <section aria-label="Next hour" className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 className="text-lg font-semibold text-white">Next hour</h2>
        <p className="mt-1 text-sm text-slate-400">No ladder yet — it freezes 65 minutes before the hour.</p>
      </section>
    );
  }
  const marketByTarget = new Map((market?.forecasts ?? []).map((f) => [f.target, f.probability]));
  const rows: LadderRow[] = group
    .map((f) => {
      const strike = Number(f.target.match(/-T([\d.]+)$/)?.[1]);
      return { strike, ours: f.probability, market: marketByTarget.get(f.target) ?? f.market_prob };
    })
    .filter((r) => Number.isFinite(r.strike))
    .sort((a, b) => a.strike - b.strike);
  const band = rows.filter((r) => r.ours >= 0.02 && r.ours <= 0.98);
  const shown = band.length >= 3 ? band : rows;
  const ourLevel = crossing(rows, (r) => r.ours);
  const marketLevel = crossing(rows, (r) => r.market);
  const frozenAt = new Date(Math.max(...group.map((f) => Date.parse(f.frozen_at))));
  const levelText = (v: number | null) => (v === null ? "outside the ladder" : `$${v.toFixed(2)}`);
  return (
    <section aria-label="Next hour" className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-lg font-semibold text-white">Next hour — {eventLabel(event)}</h2>
        <span className="text-xs text-slate-500">
          locked in {frozenAt.toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" })} ET
        </span>
      </div>
      <p className="mt-2 text-base text-slate-100">
        Our 50% level: <span className="font-bold text-white">{levelText(ourLevel)}</span>
        {marketLevel !== null && (
          <> · Kalshi's ladder implies <span className="font-semibold">{levelText(marketLevel)}</span></>
        )}
      </p>
      <p className="mt-1 text-xs text-slate-500">
        Probability the hour settles above each strike — ours beside Kalshi's. Watch the strikes near the 50% level and where the two disagree.
        {shown.length < rows.length && ` Showing the ${shown.length} strikes around the money of ${rows.length}.`}
      </p>
      <table className="mt-3 w-full text-sm tabular-nums">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
            <th className="py-1 font-medium">Strike</th>
            <th className="py-1 font-medium">Us</th>
            <th className="py-1 font-medium">Kalshi</th>
            <th className="py-1 text-right font-medium">Gap</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => {
            const isLevel = ourLevel !== null && Math.abs(r.strike - ourLevel) === Math.min(...shown.map((s) => Math.abs(s.strike - ourLevel)));
            return (
              <tr key={r.strike} className={`border-t border-slate-800/60 ${isLevel ? "bg-slate-800/40" : ""}`}>
                <td className="py-1.5 font-mono text-white">
                  ${r.strike.toFixed(2)}
                  {isLevel && <span className="ml-2 text-[11px] font-semibold uppercase tracking-wide text-amber-300">our 50% level</span>}
                </td>
                <td className="py-1.5 pr-2">
                  <span className="flex items-center gap-2">
                    <span className="h-2 rounded bg-amber-400/80" style={{ width: `${Math.max(2, r.ours * 60)}px` }} />
                    <span className="text-slate-200">{(r.ours * 100).toFixed(0)}%</span>
                  </span>
                </td>
                <td className="py-1.5 pr-2">
                  {r.market === null ? (
                    <span className="text-slate-500">—</span>
                  ) : (
                    <span className="flex items-center gap-2">
                      <span className="h-2 rounded bg-slate-400/80" style={{ width: `${Math.max(2, r.market * 60)}px` }} />
                      <span className="text-slate-300">{(r.market * 100).toFixed(0)}%</span>
                    </span>
                  )}
                </td>
                <td className="py-1.5 text-right text-slate-300">
                  {r.market === null ? "—" : `${r.ours - r.market >= 0 ? "+" : "−"}${Math.abs((r.ours - r.market) * 100).toFixed(0)} pts`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function RecordSection({ title, rows }: { title: string; rows: ViewRow[] }) {
  const [open, setOpen] = useState(false);
  if (rows.length === 0) return null;
  return (
    <section aria-label={title} className="border border-slate-800">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-900/60"
      >
        <span className="text-base font-semibold text-white">{title}</span>
        <span className="text-xs text-slate-500">scoring &amp; settlements</span>
        <ChevronDown className={`ml-auto h-5 w-5 shrink-0 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div className="space-y-6 px-4 pb-4">
          {rows.map((row) => (
            <section key={row.key} aria-label={row.label} className="border-t border-slate-800 pt-4">
              <div className="flex items-baseline justify-between gap-4">
                <h3 className="text-lg font-semibold text-slate-100">{row.label}</h3>
                <div className="flex items-center gap-3">
                  <span className="text-lg tabular-nums text-slate-100">{skillText(row.skill)}</span>
                  <Chip tone={STATUS_TONE[row.status]}>{STATUS_WORDS[row.status]}</Chip>
                </div>
              </div>
              <JournalDetail row={row} />
            </section>
          ))}
        </div>
      )}
    </section>
  );
}

export default function Oil() {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [ours, setOurs] = useState<JournalFeed | null>(null);
  const [market, setMarket] = useState<JournalFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    getJson<JournalResponse>("/api/journal").then(setData).catch((e: Error) => setError(e.message));
  }, [tick]);

  useEffect(() => {
    if (!data) return;
    const hourly = data.forecasters.find((s) => s.forecaster === "oil_wti_hourly");
    const implied = data.forecasters.find((s) => s.forecaster === "kalshi_implied_oil_hourly");
    if (hourly) {
      getJson<JournalFeed>(`/api/journal/feed?forecaster=oil_wti_hourly&version=${hourly.forecaster_version}&limit=250`)
        .then(setOurs)
        .catch(() => setOurs(null));
    }
    if (implied) {
      getJson<JournalFeed>(`/api/journal/feed?forecaster=kalshi_implied_oil_hourly&version=${implied.forecaster_version}&limit=250`)
        .then(setMarket)
        .catch(() => setMarket(null));
    }
  }, [data, tick]);

  if (error) return <div className="p-8 text-rose-300">Oil forecasts unavailable: {error}</div>;
  if (!data) return <div className="p-8 text-slate-400">Loading…</div>;

  const rows = viewRows(data.forecasters.filter((s) => OIL.has(s.forecaster)));
  const hourlyRows = viewRows(data.forecasters.filter((s) => OIL_HOURLY.has(s.forecaster)));
  const t = totals(rows);

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6 md:p-8">
      <header>
        <h1 className="text-3xl font-bold text-white">WTI crude oil</h1>
        <p className="mt-2 text-slate-400">WTI, hourly and daily, scored against Kalshi.</p>
      </header>

      <NextHourHero ours={ours} market={market} />
      <div className="-mt-3 text-right text-[11px] text-slate-600">Refreshes every 10 minutes.</div>

      <ChokepointsMap />

      <NextRelease family="oil" title="Next settlement" />

      <section aria-label="Totals" className="grid gap-3 sm:grid-cols-2">
        <Stat value={t.frozen} label="forecasts locked in" />
        <Stat value={t.scored} label="scored so far" />
      </section>

      {t.frozen === 0 && <p className="text-slate-400">Nothing locked in yet. The next one locks 2 hours before the settlement.</p>}

      <RecordSection title="Daily settlement" rows={rows} />
      <RecordSection title="Hourly settlements" rows={hourlyRows} />
    </div>
  );
}
