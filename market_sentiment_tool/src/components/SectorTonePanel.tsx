import { useEffect, useState } from "react";

import { adminJson } from "@/lib/workshop";

interface SectorTone {
  sector: string;
  basket: string;
  etf: string;
  tone_day: string | null;
  tone: number | null;
  z: number | null;
}

interface ToneResponse {
  as_of: string;
  sectors: SectorTone[];
}

/**
 * The Workshop's sector-tone feature (2026-11-01): every SPDR sector's news
 * tone today -- the day's GDELT mean tone and its trailing-60-day z, the exact
 * reads the journal's `<sector>_news_tone` rows freeze on and a Workshop
 * condition can use (`source news, series <BASKET>, measure zscore`).
 * A sector that cannot be read shows a dash, never a stale number.
 */
export function SectorTonePanel() {
  const [data, setData] = useState<ToneResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    adminJson<ToneResponse>("/api/workshop/tone")
      .then((d) => (Array.isArray(d?.sectors) ? setData(d) : setFailed(true)))
      .catch(() => setFailed(true));
  }, []);

  if (failed) return null; // the panel is an extra; its absence must not break the page
  return (
    <section aria-label="Sector news tone" className="mt-12">
      <h2 className="text-lg font-semibold text-white">Sector news tone</h2>
      <p className="mt-1 text-sm text-slate-400">
        What the news about each industry sounds like today, against its own last 60 days. The journal grades
        each sector's tone against its ETF every session; in an idea, read it as source <em>news</em>, series
        the basket name, measure <em>zscore</em>.
      </p>
      {data === null ? (
        <p className="mt-3 text-sm text-slate-400">Loading…</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="py-1 pr-3 font-medium">Sector</th>
                <th className="py-1 pr-3 font-medium">ETF</th>
                <th className="py-1 pr-3 font-medium">Tone day</th>
                <th className="py-1 pr-3 text-right font-medium">Tone</th>
                <th className="py-1 text-right font-medium">Z (60d)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {data.sectors.map((s) => (
                <tr key={s.sector}>
                  <td className="py-1.5 pr-3 capitalize text-slate-200">{s.sector}</td>
                  <td className="py-1.5 pr-3 text-slate-400">{s.etf}</td>
                  <td className="py-1.5 pr-3 text-slate-400">{s.tone_day ?? "—"}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-slate-200">
                    {s.tone === null ? "—" : s.tone.toFixed(2)}
                  </td>
                  <td className={`py-1.5 text-right tabular-nums font-medium ${s.z === null ? "text-slate-400" : s.z <= -1 ? "text-emerald-300" : s.z >= 1 ? "text-rose-300" : "text-slate-200"}`}>
                    {s.z === null ? "—" : s.z.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
