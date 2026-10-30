import { forecasterLabel, baselineName, CALIBRATED_SUFFIX, CAUTIOUS_SUFFIX } from "@/lib/forecasterLabels";
import { isMarket, type JournalScore } from "@/lib/journal";
import { EARLY_N, NEEDED, type ViewRow } from "@/lib/journalView";

/**
 * The journal's league table: one row per predictor, grouped, ordered by evidence.
 *
 * One sign convention everywhere: EDGE is positive when the predictor beats what it is measured
 * against. The server's `gap` is a paired Brier gap where NEGATIVE is better, so edge = -gap and the
 * conversion happens in exactly this one place. Nothing else on the page may print a raw gap.
 */

export const Z95 = 1.96;

export type GroupId = "sports" | "macro" | "weather";

export const GROUPS: { id: GroupId; label: string; blurb: string }[] = [
  { id: "sports", label: "Sports", blurb: "Winners, spreads and totals, scored against the Kalshi price." },
  { id: "macro", label: "Macro & markets", blurb: "Inflation, jobs, the Fed and tomorrow's moves." },
  { id: "weather", label: "Weather & energy", blurb: "Temperatures, rain, the Texas grid and gasoline." },
];

export type LeagueStatus = "beating" | "level" | "behind" | "early" | "waiting";

export const STATUS_LABEL: Record<LeagueStatus, string> = {
  beating: "Beating the baseline",
  level: "Level",
  behind: "Behind",
  early: "Too early to say",
  waiting: "Waiting for results",
};

/** Predictors the owner runs that this journal does not score yet. Said plainly, never hidden. */
export const NOT_YET: { label: string; group: GroupId }[] = [
  { label: "Premier League", group: "sports" },
  { label: "NBA", group: "sports" },
  { label: "Formula 1", group: "sports" },
];

export function baseName(forecaster: string): string {
  return forecaster.replace(new RegExp(`(${CAUTIOUS_SUFFIX}|${CALIBRATED_SUFFIX})$`), "");
}

/** A predictor is a forecaster at a version ("cpi_nowcast@cpi-core-v1" is core CPI, not a variant of CPI).
 *  Cautious and calibrated copies carry their model's version, with a "+wNN" window suffix dropped. */
function predictorId(r: ViewRow): string {
  return `${baseName(r.forecaster)}@${r.score.forecaster_version.replace(/\+w\d+$/, "")}`;
}

export function groupOf(forecaster: string): GroupId {
  const f = baseName(forecaster);
  if (f.startsWith("sports_")) return "sports";
  if (f.startsWith("weather_") || f === "ercot_peak" || f === "gas") return "weather";
  return "macro";
}

/** Positive = beats the baseline. null when the server measured no gap. */
export function edgeOf(score: Pick<JournalScore, "gap">): number | null {
  return score.gap === null || score.gap === undefined ? null : -score.gap;
}

export function statusOf(edge: number | null, se: number | null, scored: number): LeagueStatus {
  if (scored === 0) return "waiting";
  if (edge === null || se === null || scored < EARLY_N) return "early";
  if (edge - Z95 * se > 0) return "beating";
  if (edge + Z95 * se < 0) return "behind";
  return "level";
}

export interface LeagueRow {
  id: string;
  label: string;
  group: GroupId;
  primary: ViewRow;
  variants: ViewRow[];
  scored: number;
  needed: number;
  edge: number | null;
  se: number | null;
  against: string;
  status: LeagueStatus;
  promoted: boolean;
}

const isBaseline = (r: ViewRow) => r.forecaster.startsWith("baseline_") || isMarket(r.score);

/** Edge in words with its 95% half-width: "+0.021 ± 0.016". Three places, a dash when unmeasured. */
export function edgeText(edge: number | null, se: number | null): string {
  if (edge === null) return "—";
  const sign = edge > 0 ? "+" : edge < 0 ? "−" : "";
  const e = `${sign}${Math.abs(edge).toFixed(3)}`;
  return se === null ? e : `${e} ± ${(Z95 * se).toFixed(3)}`;
}

export function league(rows: ViewRow[]): LeagueRow[] {
  const byPredictor = new Map<string, ViewRow[]>();
  for (const r of rows.filter((x) => !isBaseline(x))) {
    const id = predictorId(r);
    byPredictor.set(id, [...(byPredictor.get(id) ?? []), r]);
  }
  const out: LeagueRow[] = [];
  for (const [id, variants] of byPredictor) {
    // The variant with the most evidence leads; a plain model wins a tie. The rest sit behind a disclosure.
    const base = id.replace(/@.*$/, "");
    const sorted = [...variants].sort((a, b) => b.scored - a.scored || Number(a.forecaster !== base) - Number(b.forecaster !== base));
    const primary = sorted[0];
    const edge = edgeOf(primary.score);
    const se = primary.score.gap_se ?? null;
    out.push({
      id,
      label: forecasterLabel(base, id.replace(/^.*@/, "")),
      group: groupOf(base),
      primary,
      variants: sorted.slice(1),
      scored: primary.scored,
      needed: NEEDED[primary.score.cadence] ?? NEEDED.daily,
      edge,
      se,
      against: baselineName(primary.baseline),
      status: statusOf(edge, se, primary.scored),
      promoted: sorted.some((v) => v.score.gate_status === "PROMOTED"),
    });
  }
  const rank = (s: LeagueStatus) => ["beating", "level", "behind", "early", "waiting"].indexOf(s);
  return out.sort((a, b) => rank(a.status) - rank(b.status) || b.scored - a.scored || a.label.localeCompare(b.label));
}

export function byGroup(rows: LeagueRow[]): { group: (typeof GROUPS)[number]; rows: LeagueRow[] }[] {
  return GROUPS.map((group) => ({ group, rows: rows.filter((r) => r.group === group.id) })).filter((g) => g.rows.length > 0 || NOT_YET.some((n) => n.group === g.group.id));
}

/** "3 of 11 beating their baseline": counts only predictors with a measured verdict. */
export function beatingCount(rows: LeagueRow[]): { beating: number; measured: number } {
  const measured = rows.filter((r) => r.status === "beating" || r.status === "level" || r.status === "behind");
  return { beating: measured.filter((r) => r.status === "beating").length, measured: measured.length };
}

/** Symmetric axis, rounded outward to 0.01, wide enough for every interval on screen. */
export function axisSpan(rows: LeagueRow[]): number {
  const reach = Math.max(0.01, ...rows.map((r) => (r.edge === null ? 0 : Math.abs(r.edge) + (r.se === null ? 0 : Z95 * r.se))));
  return Math.ceil(reach * 100) / 100;
}
