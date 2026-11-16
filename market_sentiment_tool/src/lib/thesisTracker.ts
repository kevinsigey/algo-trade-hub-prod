// The Thesis Tracker read model (GET /api/thesis/cards). One forecast
// card per covered name per print, frozen before the release; the two
// pre-print signals (whisper, money flow) are separate fields and are
// graded separately -- there is deliberately no combined score field.
export type ForecastCard = {
  id: number;
  ticker: string;
  thesis_id: number;
  print_at: string;
  whisper_esp: number | null;
  whisper_sign: "positive" | "negative" | "flat" | null;
  money_flow_direction: "inflow" | "outflow" | "mixed" | null;
  money_flow_evidence: { text?: string; source?: string }[];
  guide_position: string | null;
  predicted_direction: "up" | "down" | "flat" | null;
  opposing_case_ref: string | null;
  classification: "improved" | "intact" | "deteriorated" | null;
  supersedes_id: number | null;
  frozen_at: string;
  // Added by the read endpoint, not stored: true when a later pre-print
  // card replaces this one. Superseded cards are never graded.
  superseded: boolean;
};

export type ThesisCardsPayload = {
  cards: ForecastCard[];
};

// The Thesis Scoreboard read model (GET /api/thesis/scoreboard, PR 7).
// Claims are graded by the falsifiers' own frozen windows; the two
// signals stay separate fields here too -- no combined score exists.
export type ClaimBlock = {
  claim: "A" | "B" | "C";
  thesis_slug: string | null;
  metric: string;
  state: string;
  deadline: string | null;
  days_to_deadline: number | null;
  graded: number;
  hits: number | null;
  rate: number | null;
  interval: [number, number] | null;
  progress_verdict: string | null;
  // Claim A
  prints_target?: number;
  prints_remaining?: number;
  window_separation?: number | null;
  rolling60_separation?: number | null;
  // Claim B
  clusters_target?: number;
  clusters_graded?: number;
  clusters_remaining?: number;
  mean_excess?: number | null;
  note?: string;
  // Claim C
  fires_target?: number;
  fires_remaining?: number;
  net?: number;
};

export type SignalBlock = {
  graded: number;
  hits: number;
  rate: number | null;
  interval: [number, number] | null;
};

export type PlayKindBlock = {
  links: number;
  trades: number;
  wins: number;
  pnl: number;
  hit_rate: number | null;
  interval: [number, number] | null;
};

export type Scoreboard = {
  generated_at: string;
  theses: {
    slug: string; title: string; sleeve: string; status: string;
    kill_line_count: number; spec_ref: string | null;
  }[];
  claims: ClaimBlock[];
  signals: { whisper: SignalBlock; money_flow: SignalBlock };
  play_kinds: Record<string, PlayKindBlock>;
  sizing: {
    config: {
      unit_v2_premium: number; unit_v2_top: number;
      unit_fallback: number; play_kind_c_live: boolean;
      cash_floor_pct: number;
    };
    health: { last_grader_run_at: string | null; last_grader_ok: boolean };
    governing_unit: { unit: number; source: string; fresh: boolean };
  };
  regime: {
    odds: {
      state: string | null; stalemate: number | null; boom: number | null;
      crash: number | null; as_of: string | null;
    };
    capex: {
      figure_usd_bn: number | null; crash_below_usd_bn: number;
      boom_at_or_above_usd_bn: number; grading: string | null;
      state: string | null; as_of: string | null;
    };
    crash_triggers: { fired: string[]; fired_count: number; state: string | null };
    credit_lights: {
      key: string; label: string; state: string;
      as_of: string | null; age_days: number | null;
    }[];
  };
  cash_gauge: {
    floor_pct: number;
    books: { book: string; cash_pct: number | null; breach: boolean }[];
  };
  breaches: {
    refusals: {
      at: string | null; route: string | null; outcome: string;
      detail: string | null; cash_floor: boolean;
    }[];
    stale_files: {
      path: string; thesis_slug: string | null;
      amended_at: string | null; last_decision_at: string | null;
    }[];
  };
};

export type ThesisScoreboardPayload = {
  scoreboard: Scoreboard | null;
};
