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
