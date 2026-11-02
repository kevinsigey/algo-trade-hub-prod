import type { SeriesEntry } from "@/lib/journal";
import { forecasterLabel } from "@/lib/forecasterLabels";

/** The home page's movers: pure wording/math over the server's series, no scores computed. */

export interface Mover {
  key: string;
  label: string;
  delta: number;
  since: string;
}

/** Edge change between a forecaster's latest series point and the one ~5 points earlier. */
export function biggestMovers(series: SeriesEntry[], count = 3): Mover[] {
  const out: Mover[] = [];
  for (const s of series) {
    const pts = s.points.filter((p) => p.gap !== null);
    if (pts.length < 2) continue;
    const last = pts[pts.length - 1];
    const prior = pts[Math.max(0, pts.length - 6)];
    if (prior === last) continue;
    const delta = -(last.gap as number) - -(prior.gap as number);
    if (delta === 0) continue;
    out.push({ key: `${s.forecaster}@${s.version}`, label: forecasterLabel(s.forecaster, s.version), delta, since: prior.date });
  }
  return out.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, count);
}
