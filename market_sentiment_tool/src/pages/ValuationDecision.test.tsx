import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Valuation from "@/pages/Valuation";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const AMGN = {
  ticker: "AMGN", tier: "watch", status: "banded", band_basis: "eps",
  price: "460.42", price_as_of: "2026-11-06", peer_group: "biotechnology",
  peer_multiple: "16.49", peer_count: 7, peer_basis: "industry_group",
  anchor: { metric: "eps_gaap", period: "full year 2026", period_key: "FY2026",
    low: 18.34, high: 19.28, mid: 18.81, point_guide: false, consensus: null,
    recorded_at: "2026-11-03T21:05:44+00:00", accession: "0000318154-26-000153" },
  bands: { bear: 272.18, base: 310.17, bull: 317.92 },
  implied_eps: "27.92", implied_revenue: null, gap_range_widths: "9.69",
  guidance_percentile: null, baseline_verdict: "short_zone_strong", stale: false,
  falsifier: "Falsified if AMGN guides FY2026 EPS below 18.34 at the next print.",
  directions: {}, fundamentals: { missing: [] },
  inputs: { guidance_records: [] },
  computed_at: "2026-11-09T18:00:00Z",
};

const CHIP = {
  ticker: "AMGN", verdict_id: 7, rendered_at: "2026-11-10T06:00:00+00:00",
  judge: "free-ai-proposer", choice_id: "act_at_band_mid", direction: "short",
  confidence: 0.62, rationale: "the price implies more than the file",
  dissent: "The guide is conservative and improving.",
  snapshot_id: 3, fact_sheet_id: 41, trigger: "band_zone",
  zone: "short_zone_strong",
};

const DECISION = {
  ticker: "AMGN",
  snapshot: { id: 3, computed_at: "2026-11-10T03:44:00Z", completed_at: "2026-11-10T03:50:00Z" },
  know: { fact_sheet_id: 41, status: "banded", tier: "watch", price: 460.42,
    price_as_of: "2026-11-06", price_vendor: "Yahoo Finance", band_basis: "eps",
    anchor: null, bands: { bear: 272.18, base: 310.17, bull: 317.92 },
    peer: { group: "biotechnology", multiple: 16.49, count: 7, basis: "industry_group" },
    guidance_percentile: null, gap_range_widths: 9.69, directions: {},
    fundamentals_present: {}, fundamentals_missing: [],
    guard_rejections: [], ingest_notes: [], stale: false, stale_reasons: [],
    computed_at: "2026-11-09T18:00:00Z", snapshot_id: 3 },
  systems: { zone: "short_zone_strong", gap_range_widths: 9.69,
    screens: [], entrants: [], crossings: [],
    print_classification: null },
  judgment: { verdict: CHIP, candidate: null,
    falsifier: "Falsified if AMGN guides FY2026 EPS below 18.34 at the next print.",
    falsifier_source: "verdict record", crossings_graded: 0,
    crossings_mean_score: null },
  missing: ["not a member of any recorded screen run",
            "no print classification on record for this name"],
};

function serve() {
  const f = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/name-decision/AMGN")) {
      return new Response(JSON.stringify(DECISION), { status: 200 });
    }
    if (url.includes("/api/verdict-chips")) {
      return new Response(JSON.stringify(
        { generated_at: "2026-11-10T12:00:00Z", chips: { AMGN: CHIP } }),
        { status: 200 });
    }
    if (url.includes("/api/valuation-bands/AMGN")) {
      return new Response(JSON.stringify({ ...AMGN, peer_members: ["GILD"] }), { status: 200 });
    }
    if (url.includes("/api/valuation-bands")) {
      return new Response(JSON.stringify({
        snapshot: { id: 3, computed_at: "2026-11-10T03:44:00Z",
          completed_at: "2026-11-10T03:50:00Z", sheet_count: 1,
          banded_count: 1, source: "valuation_run" },
        sheets: [AMGN],
      }), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Guidance tab — Batch 2 verdict chip + decision view", () => {
  it("puts the verdict element on the name's own row", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const chip = await screen.findByTestId("verdict-chip-AMGN");
    expect(chip).toHaveTextContent("Debate: Act at the mid band · short · 62% confidence");
    expect(chip).toHaveTextContent("Dissent: The guide is conservative and improving.");
  });

  it("opens the decision view for a ?decision= deep link", async () => {
    serve();
    render(
      <MemoryRouter initialEntries={["/valuation?decision=AMGN"]}>
        <Valuation />
      </MemoryRouter>);
    await screen.findByText("What we know");
    const view = screen.getByTestId("decision-AMGN");
    expect(view).toHaveTextContent("What we know");
    expect(view).toHaveTextContent("What the systems say");
    expect(view).toHaveTextContent("The judgment");
    expect(view).toHaveTextContent("What is missing");
    expect(view).toHaveTextContent("no print classification on record for this name");
    expect(view).toHaveTextContent("against snapshot #3");
  });
});
