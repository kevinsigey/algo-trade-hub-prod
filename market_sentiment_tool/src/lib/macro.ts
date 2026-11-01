/**
 * Macro predictions dashboard types + the one verdict rule (phase-3 §1).
 * The payload is composed server-side from the hub's existing reads; this
 * module only shapes it. `recordVerdict` is the page's only judgement and it
 * is sample-first: below the shared early-sample floor the honest sentence is
 * "too early", never a winner.
 */
import { EARLY_N, isEarlySample } from "@/lib/sample";

export interface MacroCall {
  label: string;
  ours: number | null;
  market: number | null;
  last_actual: number | null;
  as_of: string | null;
}

export interface MacroRecord {
  source: "scoreboard" | "journal";
  n_settled: number | null;
  brier_ours: number | null;
  brier_market: number | null;
  gap?: number | null;
  gap_se?: number | null;
  gate_status: string | null;
  promotion_status: string | null;
  diagnostics_flags: string[];
}

export interface MacroTrailPoint {
  label: string;
  ours: number | null;
  market: number | null;
  actual: number | null;
}

export interface MacroCard {
  key: string;
  title: string;
  predicts: string;
  detail_href: string;
  display_only: boolean;
  call: MacroCall | null;
  record: MacroRecord | null;
  trail: MacroTrailPoint[];
  trail_kind: "value" | "probability";
  next_release: string | null;
}

export interface MacroResponse {
  as_of: string;
  cards: MacroCard[];
}

export function recordVerdict(rec: MacroRecord | null): string {
  if (!rec) return "Record unavailable";
  if (isEarlySample(rec.n_settled)) {
    return `Too early to say — ${rec.n_settled ?? 0} settled, judged from ${EARLY_N}.`;
  }
  if (rec.brier_ours == null || rec.brier_market == null) return "Record incomplete";
  if (rec.brier_ours < rec.brier_market) return "Ahead of the market on Brier so far";
  if (rec.brier_ours > rec.brier_market) return "Behind the market on Brier so far";
  return "Level with the market on Brier so far";
}
