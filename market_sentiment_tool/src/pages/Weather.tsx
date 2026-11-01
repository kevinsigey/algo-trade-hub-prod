import { useEffect, useState } from "react";
import { AlertTriangle, CloudSun, Loader2 } from "lucide-react";

import { useWeather } from "@/hooks/useWeather";
import { buildApiUrl } from "@/lib/api";
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

            {today.length === 0 && settled.length === 0 ? (
              <p className="text-sm text-slate-500">No weather data available.</p>
            ) : (
              <>
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
              </>
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