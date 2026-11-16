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
