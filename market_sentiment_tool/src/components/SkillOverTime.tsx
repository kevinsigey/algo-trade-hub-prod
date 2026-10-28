import { Area, CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from "recharts";

import { forecasterLabel } from "@/lib/forecasterLabels";
import type { SeriesEntry } from "@/lib/journal";

const BAND_OPACITY = 0.14;
const UNKNOWN = "#909aa8";
const AHEAD = "#3ddc84";
const BEHIND = "#ff6b6b";

interface BandPoint {
  date: string;
  upper: number;
  lower: number;
}

/** Small multiples: one sparkline per forecaster showing EDGE over time (positive beats the baseline) with a ±2 SE shaded band.
 *
 *  Every number comes from /api/journal/series; nothing is computed here. Null gap -> no line point
 *  (never a dot at 0). Null se -> line only, no band. */
export function SkillOverTime({ series }: { series: SeriesEntry[] }) {
  // Shared y-domain so the sparklines are comparable across forecasters.
  // The server's gap is negative-is-better; the page speaks in edge, positive-is-better.
  const gaps = series.flatMap((s) => s.points.map((p) => p.gap).filter((v): v is number => v !== null).map((g) => -g));
  const [yMin, yMax] =
    gaps.length > 0
      ? [(Math.min(0, ...gaps) as number) * 1.5, (Math.max(0, ...gaps) as number) * 1.5 || 0.01]
      : [-1, 1];

  return (
    <section aria-label="Edge over time" className="grid gap-4">
      <h2 className="col-span-full font-display text-2xl uppercase tracking-wide text-foreground">Edge over time</h2>
      <p className="col-span-full -mt-2 text-sm text-muted-foreground">Above zero beats what the predictor is measured against. Shaded band is plus or minus two standard errors.</p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {series.map((s) => {
          const pts = [...s.points].sort((a, b) => a.date.localeCompare(b.date));
          const label = forecasterLabel(s.forecaster, s.version);
          const latest = [...pts].reverse().find((p) => p.gap !== null);
          const latestGap = latest?.gap ?? null;
          const color = latestGap === null ? UNKNOWN : latestGap < 0 ? AHEAD : BEHIND;  // gap < 0 is edge > 0

          const linePts = pts.filter((p) => p.gap !== null).map((p) => ({ date: p.date, gap: -(p.gap as number) }));
          const bandPts: BandPoint[] = pts
            .filter((p) => p.gap !== null && p.se !== null)
            .map((p) => ({ date: p.date, upper: -(p.gap as number) + 2 * (p.se as number), lower: -(p.gap as number) - 2 * (p.se as number) }));

          if (linePts.length === 0) {
            return (
              <div key={s.forecaster} className="flex flex-col items-center gap-1 h-36">
                <div className="text-xs text-muted-foreground">{label}</div>
                <span className="text-muted-foreground">—</span>
              </div>
            );
          }

          return (
            <div key={s.forecaster} className="flex flex-col gap-1 h-36">
              <div className="text-xs text-muted-foreground">{label}</div>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={linePts} margin={{ top: 4, right: 4, bottom: 16, left: 16 }}>
                  <CartesianGrid stroke="#2b333f" />
                  <XAxis
                    type="category"
                    dataKey="date"
                    tick={{ fill: "#909aa8", fontSize: 8 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    type="number"
                    dataKey="gap"
                    domain={[yMin, yMax]}
                    tick={{ fill: "#909aa8", fontSize: 8 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  {bandPts.length > 0 && (
                    <Area type="linear" dataKey="upper" fill={color} fillOpacity={BAND_OPACITY} />
                  )}
                  {bandPts.length > 0 && (
                    <Area type="linear" dataKey="lower" fill={color} fillOpacity={BAND_OPACITY} />
                  )}
                  <Line type="linear" dataKey="gap" stroke={color} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          );
        })}
      </div>
    </section>
  );
}
