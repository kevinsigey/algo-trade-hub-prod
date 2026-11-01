/** Types for GET /api/weather/map (phase-3 §3.1): per-city summaries composed
 * server-side from journal payloads. A kind's `version` names the model its
 * numbers came from (ens-v1 today; ens-v2 only when it earns the headline). */
export interface WeatherBucket {
  label: string;
  ours: number | null;
  market: number | null;
  clim: number | null;
}

export interface WeatherKindSummary {
  day: string;
  mean: number | null;
  version: string | null;
  buckets: WeatherBucket[];
}

export interface WeatherCity {
  sid: string;
  name: string;
  lat: number;
  lon: number;
  high: WeatherKindSummary | null;
  low: WeatherKindSummary | null;
  rain: WeatherKindSummary | null;
  record: { n: number; brier_ours: number; brier_market: number } | null;
}

export interface WeatherMapResponse {
  cities: WeatherCity[];
}

/** The marker's headline: the ensemble mean for temps, the rain probability. */
export function cityHeadline(c: WeatherCity): string {
  if (c.high?.mean != null) return `${Math.round(c.high.mean)}°`;
  if (c.low?.mean != null) return `${Math.round(c.low.mean)}°`;
  const rain = c.rain?.buckets[0];
  if (rain?.ours != null) return `${Math.round(rain.ours * 100)}% rain`;
  return "—";
}

import { projectUs } from "@/lib/usStates";

/** Northeast callouts (Kevin's ask, 2026-11-01): Boston, New York, Newark,
 * Trenton and Philadelphia sit within ~70px of each other at their true
 * coordinates -- an unreadable blob at marker size. Their labeled circles
 * fan out over the Atlantic in latitude order (offsets in px from the true
 * point, which keeps a dot and a leader line), so every circle and name
 * stays clear of its neighbours. Washington DC keeps its true position:
 * it is far enough south-west to clear the fan. */
export const MARKER_CALLOUTS: Record<string, [number, number]> = {
  BOS: [36, -32],
  NYC: [59, -12],
  EWR: [66, 34],
  TTN: [53, 74],
  PHL: [34, 113],
};

export interface MarkerLayout {
  /** The city's true projected position (the dot a callout points back to). */
  point: [number, number];
  /** Where the labeled circle is drawn: the true point, or the callout end. */
  at: [number, number];
  callout: boolean;
}

export function markerLayout(c: WeatherCity): MarkerLayout {
  const point = projectUs(c.lon, c.lat);
  const off = MARKER_CALLOUTS[c.sid];
  return off
    ? { point, at: [point[0] + off[0], point[1] + off[1]], callout: true }
    : { point, at: point, callout: false };
}
