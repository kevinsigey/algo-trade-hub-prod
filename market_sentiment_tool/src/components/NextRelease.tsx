import { useEffect, useState } from "react";

import { getJson } from "@/lib/getJson";

/**
 * The next jobs / CPI release as the model sees it right now.
 *
 * The journal only locks a forecast 24 hours before the report, so for most of the month it has nothing
 * to show. These rows come from the same models run early (`/api/journal/previews`); they are replaced on
 * every run, never scored, and labelled as such. The server computes every number here.
 */
export type Preview = {
  target: string;
  forecaster: string;
  forecaster_version: string;
  family: string;
  close_at: string;
  probability: number;
  market_prob: number | null;
  payload: Record<string, number | string | null>;
  computed_at: string;
};

const pct = (p: number | null) => (p === null ? "—" : `${Math.round(p * 100)}%`);

/** KXPAYROLLS strikes are jobs, KXCPI strikes are percent. */
export function strikeOf(target: string, family: string): string {
  const raw = target.split("-T").pop() ?? "";
  const n = Number(raw);
  if (Number.isNaN(n)) return raw;
  if (family === "labor") return `${n >= 1000 ? Math.round(n / 1000) : n}k`;
  if (family === "oil") return `$${n}`;
  return `${n}%`;
}

export function headline(rows: Preview[], family: string): string | null {
  const p = rows[0]?.payload;
  if (!p) return null;
  if (family === "labor" && typeof p.mu_k === "number") return `${Math.round(p.mu_k)}k jobs`;
  if (family === "cpi" && typeof p.nowcast === "number") return `${p.nowcast.toFixed(2)}% m/m`;
  if (family === "oil" && typeof p.last_settlement === "number") return `last settle $${p.last_settlement.toFixed(2)}`;
  return null;
}

export function NextRelease({ family, title, previews }: { family: string; title: string; previews?: Preview[] }) {
  const [rows, setRows] = useState<Preview[] | null>(previews ?? null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (previews) return;
    getJson<{ previews: Preview[] }>("/api/journal/previews").then((r) => setRows(r.previews ?? [])).catch(() => setFailed(true));
  }, [previews]);

  if (failed || rows === null) return null; // a preview is an extra; its absence must not break the page
  const mine = rows.filter((r) => r.family === family);
  // One card per model, for its NEXT release only: strikes of a later month (also open on Kalshi) are a different report.
  const eventOf = (r: Preview) => r.target.split("-T")[0];
  const nextEvent = new Map<string, Preview>();
  for (const r of mine) {
    const k = `${r.forecaster}|${r.forecaster_version}`;
    const cur = nextEvent.get(k);
    if (!cur || r.close_at < cur.close_at) nextEvent.set(k, r);
  }
  const groups = [...nextEvent.keys()];
  if (groups.length === 0) return null;

  return (
    <section aria-label={title} className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-200">{title}</h2>
        <p className="text-xs text-slate-500">Current estimate, not locked in. It locks {family === "oil" ? "2 hours before the settlement" : "24 hours before the report"} and is scored after.</p>
      </div>
      {groups.map((g) => {
        const set = mine.filter((r) => `${r.forecaster}|${r.forecaster_version}` === g && eventOf(r) === eventOf(nextEvent.get(g)!))
          .sort((a, b) => Number(a.target.split("-T").pop()) - Number(b.target.split("-T").pop()));
        const when = new Date(set[0].close_at).toLocaleDateString("en-US", { month: "short", day: "numeric" });
        return (
          <div key={g} className="rounded-lg border border-slate-800 p-4" data-preview="">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div className="text-3xl font-semibold tabular-nums text-white">{headline(set, family) ?? "—"}</div>
              <div className="text-sm text-slate-400">report {when}</div>
            </div>
            <table className="mt-3 w-full text-sm tabular-nums">
              <thead className="text-xs uppercase text-slate-500">
                <tr><th className="py-1 text-left font-normal">Above</th><th className="py-1 text-right font-normal">Ours</th><th className="py-1 text-right font-normal">Kalshi</th></tr>
              </thead>
              <tbody>
                {set.map((r) => (
                  <tr key={r.target} className="border-t border-slate-800/60">
                    <td className="py-1 text-slate-300">{strikeOf(r.target, family)}</td>
                    <td className="py-1 text-right text-slate-100">{pct(r.probability)}</td>
                    <td className="py-1 text-right text-slate-400">{pct(r.market_prob)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </section>
  );
}
