import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Deals from "@/pages/Deals";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const IPO_RUN = {
  id: 1, kind: "ipo", name: "Anthropic", inputs: { talk_low_ps: 85, talk_high_ps: 110 }, created_at: "2026-11-02",
  summary: null, summary_model: null,
  outputs: {
    pw_ps: 97.78, pw_ev_b: 1656.2, bear_ps: 26.33, prob_below_talk_mid: 0.85, implied_ps_at_pw: 25.5,
    ladder: [{ name: "bear", ps: 26.33, weight: 0.2 }, { name: "bull", ps: 273.25, weight: 0.15 }],
    conditions: { list: [], joint_odds: 0.1485 },
    entry: { at_mid: { talk_ps: 97.5, exp_return_vs_pw_pct: 0.3, mos_vs_pw_pct: 0.3, bear_downside_pct: -73.0,
                       rules: { beats_pw: true, mos_25: false, bear_bound_40: false }, enter: false },
             at_high: { talk_ps: 110, exp_return_vs_pw_pct: -11.1, mos_vs_pw_pct: -12.5, bear_downside_pct: -76.1,
                        rules: { beats_pw: false, mos_25: false, bear_bound_40: false }, enter: false } },
    sensitivity: [{ lever: "bull weight +5 pts", d_pw_ps: 9.16 }],
  },
};

const SIDE = { name: "Side", fields: { revenue: { ps_low: 20, ps_high: 30 }, ebitda: { ps_low: 32, ps_high: 48 } },
               dcf_ps: 24.5, ps_low: 20, ps_high: 48, ps_mid: 29.4 };
const MA_RUN = {
  id: 7, kind: "ma", name: "Acq / Tgt (model)", inputs: {}, created_at: "2026-11-02",
  summary: null, summary_model: null,
  outputs: {
    acquirer: { ...SIDE, name: "Acq" }, target: { ...SIDE, name: "Tgt" },
    fair_value: { ps: 29.37, ps_low: 24.1, ps_high: 34.6, methods: { revenue: 25, ebitda: 40, dcf: 24.5 },
                  weights: { revenue: 0.4, ebitda: 0.3, dcf: 0.3 }, vs_offer_pct: 53.3,
                  verdict: "the offer pays ABOVE our fair-value range -- the acquirer is paying for the synergies upfront" },
    offer: { cash_ps: 5, exchange_ratio: 0.8, value_ps: 45, undisturbed_ps: 40, premium_pct: 12.5 },
    ratio_range: { low: 0.42, high: 2.4, offered: 0.8, inside: true, position: 0.19 },
    pro_forma: { combined_revenue_b: 80, combined_ebitda_b: 16, new_shares_b: 1.6, combined_shares_b: 3.6,
                 ev_at_offer_b: 190, ev_to_revenue: 2.4, ev_to_ebitda: 11.9,
                 ownership: { acquirer_pct: 55.6, target_pct: 44.4 } },
    cases: { bear: { synergy_pv_b: 3.1, accretion_pct: 1.2, target_captures_b: 31.2, acquirer_captures_b: -28.1 },
             base: { synergy_pv_b: 6.3, accretion_pct: 4.4, target_captures_b: 31.2, acquirer_captures_b: -24.9 },
             bull: { synergy_pv_b: 12.6, accretion_pct: 9.1, target_captures_b: 31.2, acquirer_captures_b: -18.6 } },
  },
};

const ROWS = [
  { id: 7, kind: "ma", name: "Acq / Tgt (model)", created_at: "2026-11-02", has_summary: false,
    headline: { offer_ps: 45, premium_pct: 12.5, fair_ps: 29.37 } },
];

function serve() {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/api/deals/ipo/run") ? IPO_RUN
      : url.endsWith("/api/deals/runs/7") ? MA_RUN
      : url.includes("/api/deals/runs") ? ROWS : {};
    return new Response(JSON.stringify(body), { status: 200 });
  }));
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Deals and IPOs page", () => {
  it("opens on the M&A builder with public/private sides and source toggle", async () => {
    serve();
    render(<MemoryRouter><Deals /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Deals and IPOs" })).toBeInTheDocument();
    expect(screen.getByText("Acquirer")).toBeInTheDocument();
    expect(screen.getAllByText("Public ticker").length).toBe(2);
    expect(screen.getByText("Offer and synergies")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Public ticker")[0]);
    expect(screen.getAllByText("Filed (EDGAR)").length).toBeGreaterThan(0);
  });

  it("runs the prefilled IPO form and renders our fair value + verdicts", async () => {
    serve();
    render(<MemoryRouter><Deals /></MemoryRouter>);
    fireEvent.click(screen.getByRole("tab", { name: "IPO builder" }));
    fireEvent.click(screen.getByRole("button", { name: "Run the IPO builder" }));
    expect(await screen.findByText("$97.78")).toBeInTheDocument();
    expect(screen.getAllByText(/Not a clean entry/).length).toBeGreaterThan(0);
    expect(screen.getByText(/bull weight \+5 pts/)).toBeInTheDocument();
    expect(screen.getByText("85%")).toBeInTheDocument();
  });

  it("opens a saved draft centrally with the fair-value record", async () => {
    serve();
    render(<MemoryRouter><Deals /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("tab", { name: /Saved drafts/ }));
    fireEvent.click(await screen.findByText("Acq / Tgt (model)"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Our fair value for the target")).toBeInTheDocument();
    expect(screen.getByText(/paying for the synergies upfront/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Draft the AI summary" })).toBeInTheDocument();
  });
});
