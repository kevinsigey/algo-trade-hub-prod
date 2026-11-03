import { useEffect, useState } from "react";

import { getJson } from "@/lib/getJson";

// The Workshop's on-chain data (crypto step 3, Kevin, 2026-11-03): the
// Dune series cached for Workshop rules (a condition with source "dune"
// reads one by key). One aggregate line per series -- what it is, how
// much history, how fresh. Renders nothing until a series is cached.

interface DuneSeriesRow {
  key: string;
  query_id: number | null;
  value_column: string | null;
  n_points: number;
  first_date: string | null;
  last_date: string | null;
  updated_at: string | null;
}

const day = (iso: string | null) =>
  iso ? new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "—";

export default function CryptoDuneSeries() {
  const [rows, setRows] = useState<DuneSeriesRow[] | null>(null);
  useEffect(() => {
    let stop = false;
    getJson<{ series: DuneSeriesRow[] }>("/api/workshop/dune-series")
      .then((d) => { if (!stop) setRows(d.series ?? []); })
      .catch(() => { if (!stop) setRows([]); });
    return () => { stop = true; };
  }, []);
  if (!rows || rows.length === 0) return null;
  return (
    <section aria-label="Workshop on-chain data" className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h2 className="text-base font-semibold text-white">On-chain data for the Workshop</h2>
      <p className="mt-1 text-sm text-slate-400">
        Dune series cached for idea rules (source “dune”) — test a crypto idea against what the chain actually did.
      </p>
      <ul className="mt-3 space-y-1.5">
        {rows.map((r) => (
          <li key={r.key} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
            <span className="font-mono font-semibold text-slate-100">{r.key}</span>
            <span className="text-slate-400">
              {r.n_points} days · {day(r.first_date)} → {day(r.last_date)}
            </span>
            {r.updated_at && <span className="text-xs text-slate-500">cached {day(r.updated_at)}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
