/**
 * Batch 2: the compact verdict chips + the per-name decision view.
 *
 * A chip is the compact persistence read of a rendered verdict — name,
 * date, verdict, confidence, exhibit snapshot id, JUDGE IDENTITY, and a
 * one-line dissent. The judge line matters: until the pinned Jev seat is
 * wired (Kevin's Nov 18 credits), verdicts are rendered by the free AI
 * seat and say so — no chip may read as a Jev verdict before then.
 */

export interface VerdictChip {
  ticker: string;
  verdict_id: number;
  rendered_at: string;
  judge: string | null;
  choice_id: string | null;
  direction: string | null;
  confidence: number | null;
  rationale: string | null;
  dissent: string | null;
  snapshot_id: number | null;
  fact_sheet_id: number | null;
  trigger: string | null;
  zone: string | null;
}

export interface ChipsPayload {
  generated_at: string;
  chips: Record<string, VerdictChip>;
}

const CHOICE_LABELS: Record<string, string> = {
  act_at_band_low: "Act at the low band",
  act_at_band_mid: "Act at the mid band",
  watch: "Watch",
  pass: "Pass",
};

export function chipChoiceLabel(choiceId: string | null | undefined): string {
  if (!choiceId) return "—";
  return CHOICE_LABELS[choiceId] ?? choiceId;
}

/** "Act at the mid band · long · 58%" — the chip's headline. Confidence
 * is the seat's stated probability; when the seat gave none, the line
 * says so rather than implying a number. */
export function chipHeadline(chip: VerdictChip): string {
  const parts = [chipChoiceLabel(chip.choice_id)];
  if (chip.direction && chip.direction !== "none") parts.push(chip.direction);
  parts.push(chip.confidence != null
    ? `${Math.round(chip.confidence * 100)}% confidence`
    : "no stated confidence");
  return parts.join(" · ");
}

/** The judge identity in plain words, with the Nov 18 state stated. */
export function chipJudgeText(chip: VerdictChip): string {
  if (!chip.judge) return "Judge not recorded";
  if (chip.judge === "free-ai-proposer") {
    return "Judge: free AI (proposer) — the pinned Jev seat waits on Nov 18 credits";
  }
  if (chip.judge.startsWith("jev:")) return `Judge: Jev (${chip.judge.slice(4)})`;
  return `Judge: ${chip.judge}`;
}

/** Round 4: the aggregate debate queue (GET /api/debate-candidates) --
 * the candidates for the latest completed snapshot with their states,
 * the pending counts by class, and the named exclusions generation
 * persisted with their reasons. Stamped like everything else (scar #9):
 * snapshot id + computed-at and the generation's own computed-at. */
export interface DebateCandidateRow {
  ticker: string;
  candidate_class: "conjunction" | "entrant" | "zone";
  priority: number;
  state: string;
  sources?: {
    zone?: string | null;
    entrants?: unknown[];
    screens?: { name?: string }[];
    held?: { books?: string[]; sleeves?: string[] } | null;
  } | null;
  verdict_id?: number | null;
  computed_at?: string | null;
}

export interface DebateQueuePayload {
  snapshot: { id: number; computed_at: string | null; completed_at: string | null;
              sheet_count?: number | null; banded_count?: number | null } | null;
  counts: { entrants: number; zone_names: number; conjunctions: number; total: number };
  candidates: DebateCandidateRow[];
  excluded: { ticker: string; reason: string | null; computed_at?: string | null }[];
  pending_by_class: { conjunction: number; entrant: number; zone: number };
  generated_at: string | null;
}

export interface NameDecision {
  ticker: string;
  snapshot: { id: number; computed_at: string | null; completed_at: string | null } | null;
  know: {
    fact_sheet_id: number | null;
    status: string;
    tier: string | null;
    price: number | string | null;
    price_as_of: string | null;
    price_vendor: string | null;
    band_basis: string | null;
    anchor: Record<string, unknown> | null;
    bands: { bear: number; base: number; bull: number } | null;
    peer: { group: string | null; multiple: number | string | null; count: number | null; basis: string | null };
    guidance_percentile: number | string | null;
    gap_range_widths: number | string | null;
    directions: Record<string, { direction: string; mid: number | null }>;
    fundamentals_present: Record<string, { value: number; as_of: string }>;
    fundamentals_missing: string[];
    guard_rejections: string[];
    ingest_notes: string[];
    stale: boolean;
    stale_reasons: string[];
    computed_at: string | null;
    snapshot_id: number | null;
  } | null;
  systems: {
    zone: string | null;
    gap_range_widths: number | string | null;
    screens: { screen_id: number; screen_name: string; member_since: string | null; in_last_run: boolean }[];
    entrants: { screen_id: number; screen_name: string; date: string }[];
    crossings: { id: number; book: string; zone: string; action: string; score_20: number | null; created_at: string; snapshot_id: number | null }[];
    print_classification: { classification: string; as_of: string | null } | null;
  };
  judgment: {
    verdict: VerdictChip | null;
    candidate: { candidate_class: string; priority: number; state: string; snapshot_id: number | null; computed_at: string | null } | null;
    falsifier: string | null;
    falsifier_source: string | null;
    crossings_graded: number;
    crossings_mean_score: number | null;
  };
  missing: string[];
}
