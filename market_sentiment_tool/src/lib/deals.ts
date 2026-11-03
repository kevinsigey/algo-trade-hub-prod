/** Deals and IPOs (Part B): run records as saved by the API. */

export interface DealRun {
  id: number;
  kind: "ipo" | "ma";
  name: string;
  inputs: Record<string, any>;
  outputs: Record<string, any>;
  summary: string | null;
  summary_model: string | null;
  created_at: string;
}

export interface DealRunRow {
  id: number;
  kind: "ipo" | "ma";
  name: string;
  created_at: string;
  has_summary: boolean;
}
