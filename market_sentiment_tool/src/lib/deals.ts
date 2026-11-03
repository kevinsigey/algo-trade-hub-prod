/** Deals and IPOs: run records as saved by the API. */

/** The AI summary as a structured document (Kevin, 2026-11-03): the
 * writer returns JSON; the page renders sections, bullets and tables
 * with real components instead of raw markdown in a <pre>. */
export interface SummaryTable { columns: string[]; rows: string[][] }
export interface SummarySection {
  title: string; paragraphs: string[]; bullets: string[]; table: SummaryTable | null;
}
export interface SummaryDoc { headline: string; sections: SummarySection[]; takeaway: string }

/** The builders' output shapes (tradehub/deals/ipo.py, ma.py) -- typed so the
 * detail components read fields, not `any` (ESLint item from the handover). */
export interface IpoEntryTest {
  talk_ps: number; exp_return_vs_pw_pct: number; mos_vs_pw_pct: number; bear_downside_pct: number;
  rules: { beats_pw: boolean; mos_25: boolean; bear_bound_40: boolean }; enter: boolean;
}
export interface IpoOutputs {
  ladder: { name: string; weight: number; ps: number }[];
  pw_ps: number; pw_ev_b: number; pw_equity_b: number; bear_ps: number;
  prob_below_talk_mid: number | null; implied_ps_at_pw: number | null;
  implied_ps_on_run_rate: number | null;
  entry: { at_mid?: IpoEntryTest; at_high?: IpoEntryTest; missing?: string };
  sensitivity: { lever: string; d_pw_ps: number }[];
  conditions: { list: unknown[]; joint_odds: number | null };
}
export interface MaSide {
  name: string; ps_low: number; ps_high: number; ps_mid: number; dcf_ps: number | null;
  price: number | null; shares_b: number; revenue_b: number | null; ebitda_b: number | null;
  eps: number | null; net_cash_b: number;
  fields: { revenue: { ps_low: number; ps_high: number } | null;
            ebitda: { ps_low: number; ps_high: number } | null };
}
export interface MaCase {
  synergy_pre_tax_b: number | null; synergy_pv_b: number | null; eps_pro_forma: number | null;
  accretion_pct: number | null; target_captures_b: number | null; acquirer_captures_b: number | null;
}
export interface MaOutputs {
  acquirer: MaSide; target: MaSide;
  fair_value: { ps: number; ps_low: number; ps_high: number; weights: Record<string, number>;
                vs_offer_pct: number | null; verdict: string } | null;
  offer: { cash_ps: number; exchange_ratio: number; value_ps: number;
           undisturbed_ps: number | null; premium_pct: number | null };
  ratio_range: { low: number; high: number; offered: number; position: number | null;
                 inside: boolean } | null;
  pro_forma: { combined_revenue_b: number | null; combined_ebitda_b: number | null;
               new_shares_b: number; combined_shares_b: number; ev_at_offer_b: number;
               ev_to_revenue: number | null; ev_to_ebitda: number | null;
               ownership: { acquirer_pct: number; target_pct: number } };
  cases: { bear: MaCase; base: MaCase; bull: MaCase };
}
/** GET /api/deals/public/{ticker}: the filed/yahoo company snapshot. */
export interface PublicCompany {
  name?: string; price?: number | null; shares_b?: number | null; revenue_b?: number | null;
  ebitda_b?: number | null; eps?: number | null; net_cash_b?: number | null;
  rev_multiples?: { low: number; high: number } | null;
  ebitda_multiples?: { low: number; high: number } | null;
  source?: string; as_of?: string; filing_as_of?: string | null; ebitda_basis?: string | null;
}

export interface DealRun {
  id: number;
  kind: "ipo" | "ma";
  name: string;
  inputs: Record<string, unknown>;
  outputs: IpoOutputs | MaOutputs;
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
