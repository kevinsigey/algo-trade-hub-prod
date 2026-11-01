import { useEffect, useState } from "react";
import { AlertTriangle, CloudSun, Loader2 } from "lucide-react";

import { useWeather } from "@/hooks/useWeather";
import { buildApiUrl } from "@/lib/api";
import { getJson } from "@/lib/getJson";
import { US_STATE_PATHS, US_VIEWBOX } from "@/lib/usStates";
import { cityHeadline, markerLayout, type WeatherCity, type WeatherMapResponse } from "@/lib/weatherMap";
import {
  WEATHER_INTRO,
  formatOutcome,
  formatProb,
  weatherStats,
  weatherLabel,
  weatherChip,
  type Chip,
} from "@/lib/weather";

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
  const city = cities.find((c) => c.sid === selected) ?? cities[0];
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
      </div>
    ) : null;

  return (
    <section aria-label="Weather map">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-3">
        <svg viewBox={US_VIEWBOX} className="w-full" role="img" aria-label="US map of forecast cities">
          {Object.entries(US_STATE_PATHS).map(([name, d]) => (
            <path key={name} d={d} className="fill-slate-900 stroke-slate-700" strokeWidth={0.7} />
          ))}
          {cities.map((c) => {
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
          {city.record ? (
            <p className="text-xs tabular-nums text-slate-400">
              Station record: {city.record.n} settled · Brier ours {city.record.brier_ours.toFixed(3)} vs Kalshi {city.record.brier_market.toFixed(3)}
            </p>
          ) : (
            <p className="text-xs text-slate-500">No settled record at this station yet.</p>
          )}
        </div>
        {kindBlock("High", city.high)}
        {kindBlock("Low", city.low)}
        {kindBlock("Rain", city.rain)}
        {!city.high && !city.low && !city.rain && (
          <p className="mt-2 text-sm text-slate-500">No live ensemble freeze for this city — the marker is its settled record.</p>
        )}
      </div>
    </section>
  );
}

export default function Weather() {
  const { today, settled, loading, error } = useWeather();
  const s = weatherStats(today, settled);

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-8 text-slate-100 sm:px-8">
      <div className="mx-auto flex max-w-5xl flex-col gap-6">
        <header className="border-b border-slate-900 pb-6">
          <div className="flex items-center gap-2 text-emerald-400">
            <CloudSun className="h-5 w-5" aria-hidden="true" />
            <span className="text-xs font-bold uppercase tracking-widest">Weather</span>
          </div>
          <h1 className="mt-2 text-3xl font-black uppercase italic tracking-tight text-white sm:text-4xl">
            Weather
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-400">{WEATHER_INTRO}</p>
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
        ) : (
          <>
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Cities today" value={s.cities} sub="distinct cities" />
              <Stat label="Contracts frozen" value={s.todayCount} sub="ensemble vs Kalshi" />
              <Stat label="Settled" value={s.settledCount} sub="with outcome" />
            </div>

            <WeatherMap />

            {today.length === 0 && settled.length === 0 ? (
              <p className="text-sm text-slate-500">No weather data available.</p>
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

            <p className="pb-6 text-xs text-slate-600">
              Read from journal tables. No new forecasting.
            </p>
          </>
        )}

        <DegreeDaysPanel />
      </div>
    </div>
  );
}

interface DegreeRow { hdd: number | null; cdd: number | null; hdd_anomaly: number | null; cdd_anomaly: number | null; share: number }
interface DegreePanel {
  week_end: string; as_of: string;
  national: { hdd: number; cdd: number; hdd_anomaly: number | null; cdd_anomaly: number | null; population_covered_pct: number };
  regions: Record<string, DegreeRow>;
  missing_regions: string[];
}

const signed = (v: number | null) => (v === null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}`);

/** Degree-day demand (phase-2 section 5.3): the week's heating/cooling demand vs its
 * 10-year normal -- the first link of the degree-day -> storage -> gas chain the
 * engines trade on. Serves the weekly snapshot; an unbuilt snapshot says so. */
function DegreeDaysPanel() {
  const [panel, setPanel] = useState<DegreePanel | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    fetch(buildApiUrl("/api/weather/degree-days"))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((body) => {
        // Shape-guard the snapshot like every other panel: a malformed body is
        // "unavailable", never a crash or a panel of invented numbers.
        if (body && typeof body === "object" && body.national && body.regions) setPanel(body as DegreePanel);
        else setUnavailable(true);
      })
      .catch(() => setUnavailable(true));
  }, []);
  return (
    <section>
      <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-400">
        Degree-day demand
      </h2>
      {unavailable ? (
        <p className="text-sm text-slate-500">
          The weekly degree-day snapshot has not been built yet, so there is no demand read to show.
        </p>
      ) : !panel ? (
        <p className="text-sm text-slate-500">Loading the demand snapshot…</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="US heating degree days" value={panel.national.hdd.toFixed(0)}
              sub={`week ending ${panel.week_end}`} />
            <Stat label="HDD vs 10-yr normal" value={signed(panel.national.hdd_anomaly)}
              sub="population-weighted" />
            <Stat label="US cooling degree days" value={panel.national.cdd.toFixed(0)} />
            <Stat label="CDD vs 10-yr normal" value={signed(panel.national.cdd_anomaly)}
              sub={`${panel.national.population_covered_pct}% of population covered`} />
          </div>
          <div className="mt-3 flex flex-col gap-2">
            {Object.entries(panel.regions).map(([name, r]) => (
              <div key={name} className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3">
                <div className="text-sm font-semibold text-slate-200">{name}</div>
                <div className="flex items-center gap-4 text-sm tabular-nums text-slate-300">
                  <span>HDD {r.hdd?.toFixed(0) ?? "—"} ({signed(r.hdd_anomaly)})</span>
                  <span>CDD {r.cdd?.toFixed(0) ?? "—"} ({signed(r.cdd_anomaly)})</span>
                </div>
              </div>
            ))}
          </div>
          {panel.missing_regions.length > 0 && (
            <p className="mt-2 text-xs text-slate-500">
              No read for {panel.missing_regions.join(", ")} this week -- omitted, not zero-filled.
            </p>
          )}
          <p className="mt-2 text-xs text-slate-600">
            Base 65°F, Open-Meteo archive daily means, 2020 Census division shares. A cold surprise
            (HDD above normal) is the first link toward a bigger Thursday storage draw.
          </p>
        </>
      )}
    </section>
  );
}