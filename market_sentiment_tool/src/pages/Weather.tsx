import { useEffect, useState } from "react";
import { AlertTriangle, CloudSun, Loader2 } from "lucide-react";

import { useWeather } from "@/hooks/useWeather";
import { getJson } from "@/lib/getJson";
import { US_STATE_PATHS, US_VIEWBOX } from "@/lib/usStates";
import { cityHeadline, markerLayout, type WeatherCity, type WeatherMapResponse } from "@/lib/weatherMap";
import {
  WEATHER_INTRO,
  bucketPickLine,
  formatOutcome,
  formatProb,
  pickSentence,
  weatherStats,
  weatherLabel,
  parseWeatherTarget,
  weatherChip,
  type Chip,
} from "@/lib/weather";
import type { JournalResponse, JournalScore } from "@/lib/journal";

const toneClass: Record<Chip["tone"], string> = {
  ok: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  warn: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  bad: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  flat: "border-slate-600/60 bg-slate-700/20 text-slate-400",
};

function ChipBadge({ chip }: { chip: Chip }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${toneClass[chip.tone]}`}
    >
      {chip.label}
    </span>
  );
}

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-1 text-3xl font-black tracking-tight text-white">{value}</div>
      {sub ? <div className="mt-1 text-xs text-slate-500">{sub}</div> : null}
    </div>
  );
}

/**
 * The map (phase-3 §3.1): one marker per forecast city on a US outline, the
 * headline call on the marker, the full per-city card one click down. Its
 * read is independent of the contract table below -- either can fail without
 * taking the other down. Every probability names its source (ensemble /
 * Kalshi / climatology) and the ensemble's version is printed on the card,
 * so a model swap can never happen silently.
 */
function WeatherMap() {
  const [cities, setCities] = useState<WeatherCity[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    getJson<WeatherMapResponse>("/api/weather/map")
      .then((r) => {
        if (!Array.isArray(r?.cities)) throw new Error("map payload has no cities");
        setCities(r.cities);
        setSelected(r.cities[0]?.sid ?? null);
      })
      .catch(() => setFailed(true));
  }, []);

  if (failed) {
    return <p className="text-sm text-slate-500">The map is unavailable right now — the contract table below still reports.</p>;
  }
  if (!cities) {
    return <p className="text-sm text-slate-500">Loading the map…</p>;
  }
  if (cities.length === 0) {
    return <p className="text-sm text-slate-500">No city forecasts frozen yet.</p>;
  }
  // Step 13: the page is rain-only (highs, lows and ERCOT are retired) --
  // a city plots only when it carries a rain freeze.
  const rainCities = cities.filter((c) => c.rain);
  if (rainCities.length === 0) {
    return <p className="text-sm text-slate-500">No city rain forecasts frozen yet.</p>;
  }
  const city = rainCities.find((c) => c.sid === selected) ?? rainCities[0];
  // Ours and Kalshi side by side, one column each (Kevin's ask, 2026-11-01):
  // the same buckets the marker summarizes, priced by both, climatology muted.
  const kindBlock = (label: string, k: WeatherCity["high"]) =>
    k ? (
      <div key={label} className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          {label} · {k.day} · ensemble {k.version ?? "—"}{k.mean != null ? ` · mean ${k.mean.toFixed(1)}°` : ""}
        </p>
        <table className="mt-1 w-full text-sm tabular-nums">
          <thead>
            <tr className="text-[11px] uppercase tracking-wider text-slate-500">
              <th className="py-0.5 text-left font-medium">Bucket</th>
              <th className="py-0.5 text-right font-semibold text-slate-200">Ours</th>
              <th className="py-0.5 text-right font-semibold text-slate-200">Kalshi</th>
              <th className="py-0.5 text-right font-medium">Climatology</th>
            </tr>
          </thead>
          <tbody>
            {k.buckets.map((b) => (
              <tr key={b.label} className="border-t border-slate-800/60">
                <td className="py-1 text-slate-300">{b.label}</td>
                <td className="py-1 text-right font-semibold text-slate-50">{formatProb(b.ours)}</td>
                <td className="py-1 text-right text-slate-200">{formatProb(b.market)}</td>
                <td className="py-1 text-right text-slate-500">{formatProb(b.clim)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {bucketPickLine(k.buckets) && (
          <p className="mt-2 text-sm text-slate-300">{bucketPickLine(k.buckets)}</p>
        )}
      </div>
    ) : null;

  return (
    <section aria-label="Weather map">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-3">
        <svg viewBox={US_VIEWBOX} className="w-full" role="img" aria-label="US map of forecast cities">
          {Object.entries(US_STATE_PATHS).map(([name, d]) => (
            <path key={name} d={d} className="fill-slate-900 stroke-slate-700" strokeWidth={0.7} />
          ))}
          {rainCities.map((c) => {
            const { point, at, callout } = markerLayout(c);
            const active = c.sid === city.sid;
            return (
              <g key={c.sid}>
                {callout && (
                  <>
                    <line x1={point[0]} y1={point[1]} x2={at[0]} y2={at[1]} className="stroke-slate-600" strokeWidth={1} />
                    <circle cx={point[0]} cy={point[1]} r={2.5} className="fill-slate-400" />
                  </>
                )}
                <g transform={`translate(${at[0]},${at[1]})`} className="cursor-pointer"
                  onClick={() => setSelected(c.sid)}>
                  <title>{`${c.name} — ${cityHeadline(c)}`}</title>
                  <circle r={active ? 13 : 10} className={active ? "fill-emerald-400/30 stroke-emerald-300" : "fill-emerald-500/20 stroke-emerald-500/70"} />
                  <text textAnchor="middle" dominantBaseline="central" className="fill-emerald-100 text-[10px] font-bold">
                    {cityHeadline(c)}
                  </text>
                  <text y={24} textAnchor="middle" className="fill-slate-300 text-[10px]">{c.name}</text>
                </g>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="mt-3 rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold text-white">{city.name}</h2>
        </div>
        {kindBlock("Rain", city.rain)}
      </div>
    </section>
  );
}

/**
 * The ensemble's real record (Kevin's redesign, 2026-11-02): settled Brier by family
 * for ens-v2.1 against v1, Kalshi (the paired baseline on the same contracts) and
 * climatology -- read from the journal, the same rows the Model Tracker scores.
 * An independent read: if it fails, the section simply does not render.
 */
function EnsembleRecord() {
  const [rows, setRows] = useState<JournalScore[] | null>(null);
  useEffect(() => {
    getJson<JournalResponse>("/api/journal")
      .then((r) => setRows(Array.isArray(r?.forecasters) ? r.forecasters : []))
      .catch(() => setRows([]));
  }, []);
  if (!rows || rows.length === 0) return null;
  const families = [
    { label: "Rain", name: "weather_rain" },
  ];
  const find = (name: string, version: string) =>
    rows.find((r) => r.forecaster === name && r.forecaster_version === version);
  const clim = (name: string) => rows.find((r) => r.forecaster === `baseline_climatology_${name}`);
  const b = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(3));
  const built = families
    .map((f) => ({ ...f, v21: find(f.name, "ens-v2.1"), v1: find(f.name, "ens-v1"), c: clim(f.name) }))
    .filter((f) => f.v21 || f.v1 || f.c);
  if (built.length === 0) return null;
  return (
    <section aria-label="Ensemble record" className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400">Ensemble record — settled contracts</h2>
      <p className="mt-1 text-xs text-slate-500">Brier score: lower is better, 0.25 is a coin flip. Kalshi is scored on the same contracts as ens-v2.1.</p>
      <table className="mt-2 w-full text-sm tabular-nums">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
            <th className="py-1 font-medium">Family</th>
            <th className="py-1 text-right font-semibold text-slate-200">ens-v2.1</th>
            <th className="py-1 text-right font-medium">ens-v1</th>
            <th className="py-1 text-right font-medium">Kalshi</th>
            <th className="py-1 text-right font-medium">Climatology</th>
            <th className="py-1 text-right font-medium">Settled (v2.1)</th>
          </tr>
        </thead>
        <tbody>
          {built.map((f) => (
            <tr key={f.name} className="border-t border-slate-800/60">
              <td className="py-1.5 text-slate-300">{f.label}</td>
              <td className="py-1.5 text-right font-semibold text-slate-50">{b(f.v21?.brier_on_baseline ?? f.v21?.brier)}</td>
              <td className="py-1.5 text-right text-slate-300">{b(f.v1?.brier_on_baseline ?? f.v1?.brier)}</td>
              <td className="py-1.5 text-right text-slate-300">{b(f.v21?.brier_baseline)}</td>
              <td className="py-1.5 text-right text-slate-300">{b(f.c?.brier)}</td>
              <td className="py-1.5 text-right text-slate-400">{f.v21 ? f.v21.n_baseline ?? f.v21.n_settled : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default function Weather() {
  const { today: allToday, settled: allSettled, loading, error } = useWeather();
  // Step 13: rain only -- the temperature families are retired, so their
  // rows never render here (the journal still freezes and settles them).
  const today = allToday.filter((r) => parseWeatherTarget(r.target).kind === "rain");
  const settled = allSettled.filter((r) => parseWeatherTarget(r.target).kind === "rain");
  const s = weatherStats(today, settled);

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-5 text-slate-100 md:px-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-3">
        <header>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-white">
            <CloudSun className="h-5 w-5 text-emerald-400" aria-hidden="true" /> Weather
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-400">{WEATHER_INTRO}</p>
        </header>

        {loading ? (
          <div className="flex items-center gap-2 text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading…
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        ) : null}
        {loading || error ? null : (
          <>
            {/* One screen (2026-11-06): the map on the left, the record and the numbers on the right. */}
            <div className="grid gap-3 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
              <WeatherMap />
              <div className="flex min-w-0 flex-col gap-3">
                <div className="grid grid-cols-3 gap-2">
                  <Stat label="Cities today" value={s.cities} sub="distinct cities" />
                  <Stat label="Contracts frozen" value={s.todayCount} sub="ensemble vs Kalshi" />
                  <Stat label="Settled" value={s.settledCount} sub="with outcome" />
                </div>
                <EnsembleRecord />
              </div>
            </div>

            {today.length === 0 && settled.length === 0 ? (
              <p className="text-sm text-slate-500">No rain data available.</p>
            ) : (
              <details>
                <summary className="cursor-pointer text-sm font-bold uppercase tracking-wider text-slate-400">
                  All contracts, the long way
                </summary>
                {today.length > 0 ? (
                  <section>
                    <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-400">
                      Today's forecast
                    </h2>
                    <div className="flex flex-col gap-2">
                      {today.map((row) => (
                        <div
                          key={row.target}
                          className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3"
                        >
                          <div>
                            <div className="text-sm font-semibold text-slate-200">
                              {weatherLabel(row)}
                            </div>
                            <div className="text-xs text-slate-500">{weatherChip(row)}</div>
                            {pickSentence(row.ensemble, row.climatology) && (
                              <div className="mt-0.5 text-xs text-slate-400">{pickSentence(row.ensemble, row.climatology)}</div>
                            )}
                          </div>
                          <div className="flex items-center gap-4 text-sm tabular-nums">
                            <span className="text-slate-300">ens {formatProb(row.ensemble)}</span>
                            <span className="text-slate-300">kalshi {formatProb(row.kalshi)}</span>
                            <span className="text-slate-300">clim {formatProb(row.climatology)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                ) : null}

                {settled.length > 0 ? (
                  <section>
                    <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-400">
                      Settled history
                    </h2>
                    <div className="flex flex-col gap-2">
                      {settled.map((row) => (
                        <div
                          key={row.target}
                          className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3"
                        >
                          <div>
                            <div className="text-sm font-semibold text-slate-200">
                              {weatherLabel(row)}
                            </div>
                            <div className="text-xs text-slate-500">{weatherChip(row)}</div>
                          </div>
                          <div className="flex items-center gap-4 text-sm tabular-nums">
                            <span className="text-slate-300">ens {formatProb(row.ensemble)}</span>
                            <span className="text-slate-300">kalshi {formatProb(row.kalshi)}</span>
                            <ChipBadge
                              chip={{
                                label: formatOutcome(row.outcome),
                                tone: row.outcome === 1 ? "ok" : row.outcome === 0 ? "bad" : "flat",
                              }}
                            />
                            {row.realized_value !== null && row.realized_value !== undefined ? (
                              <span className="text-slate-400">{row.realized_value}°F</span>
                            ) : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                ) : null}
              </details>
            )}

            <p className="text-xs text-slate-600">
              Read from journal tables. No new forecasting.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
