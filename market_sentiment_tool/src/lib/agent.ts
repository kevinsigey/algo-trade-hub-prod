import { adminJson } from "@/lib/workshop";

/** The new-idea check: what's still open in the text and what the record already says. */

export interface LedgerCheck {
  error?: string;
  expressible?: boolean;
  note?: string;
  family?: { size: number; tickers: string[] };
  prior_attempts?: number;
  best_prior?: { idea_id: number; title: string | null; value: number; verdict: string; verdict_now: string } | null;
  killed?: { idea_id: number; title: string | null; exact: boolean; reason: string }[];
  duplicate_of_killed?: number | null;
  bar?: { ideas_tested: number; standard: string };
}

export interface InterpretResult {
  /** null: an exact duplicate of a killed idea, so there is no draft. */
  spec: Record<string, unknown> | null;
  questions: string[];
  model: string;
  preflight?: LedgerCheck;
}

export const interpretText = (text: string) =>
  adminJson<InterpretResult>("/api/agent/interpret", { method: "POST", body: JSON.stringify({ text }) });
