/** Deals and IPOs: run records as saved by the API. */

/** The AI summary as a structured document (Kevin, 2026-11-03): the
 * writer returns JSON; the page renders sections, bullets and tables
 * with real components instead of raw markdown in a <pre>. */
export interface SummaryTable { columns: string[]; rows: string[][] }
export interface SummarySection {
  title: string; paragraphs: string[]; bullets: string[]; table: SummaryTable | null;
}
export interface SummaryDoc { headline: string; sections: SummarySection[]; takeaway: string }

export interface DealRun {
  id: number;
  kind: "ipo" | "ma";
  name: string;
  inputs: Record<string, any>;
  outputs: Record<string, any>;
  summary: string | null;
  summary_doc?: SummaryDoc | null;
  summary_model: string | null;
  created_at: string;
}

export interface DealRunRow {
  id: number;
  kind: "ipo" | "ma";
  name: string;
  created_at: string;
  has_summary: boolean;
  headline: { pw_ps?: number | null; bear_ps?: number | null;
              offer_ps?: number | null; premium_pct?: number | null; fair_ps?: number | null };
}
