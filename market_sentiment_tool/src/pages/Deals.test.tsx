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
  id: 1, kind: "ipo", name: "Anthropic", inputs: {}, created_at: "2026-11-02",
  summary: null, summary_model: null,
  outputs: {
    pw_ps: 97.78, pw_ev_b: 1656.2, bear_ps: 26.33,
    ladder: [{ name: "bear", ps: 26.33, weight: 0.2 }, { name: "bull", ps: 273.25, weight: 0.15 }],
    conditions: { list: [], joint_odds: 0.1485 },
    entry: { at_mid: { talk_ps: 97.5, exp_return_vs_pw_pct: 0.3, mos_vs_pw_pct: 0.3, bear_downside_pct: -73.0,
                       rules: { beats_pw: true, mos_25: false, bear_bound_40: false }, enter: false },
             at_high: { talk_ps: 110, exp_return_vs_pw_pct: -11.1, mos_vs_pw_pct: -12.5, bear_downside_pct: -76.1,
                        rules: { beats_pw: false, mos_25: false, bear_bound_40: false }, enter: false } },
    sensitivity: [{ lever: "bull weight +5 pts", d_pw_ps: 9.16 }],
  },
};

function serve() {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/api/deals/ipo/run") ? IPO_RUN
      : url.includes("/api/deals/runs") ? [] : {};
    return new Response(JSON.stringify(body), { status: 200 });
  }));
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Deals and IPOs page", () => {
  it("runs the prefilled IPO form and renders the paper's verdicts", async () => {
    serve();
    render(<MemoryRouter><Deals /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Deals and IPOs" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run the IPO builder" }));
    expect(await screen.findByText("$97.78")).toBeInTheDocument();
    expect(screen.getAllByText(/Not a clean entry/).length).toBeGreaterThan(0);
    expect(screen.getByText(/bull weight \+5 pts/)).toBeInTheDocument();
  });

  it("toggles to the M&A builder with public/private sides", async () => {
    serve();
    render(<MemoryRouter><Deals /></MemoryRouter>);
    fireEvent.click(screen.getByRole("tab", { name: "M&A builder" }));
    expect(screen.getByText("Acquirer")).toBeInTheDocument();
    expect(screen.getAllByText("Public ticker").length).toBe(2);
    expect(screen.getByText("Offer and synergies")).toBeInTheDocument();
  });
});
