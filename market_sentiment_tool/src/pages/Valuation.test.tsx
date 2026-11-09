import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

// Fixtures mirror the live payload's shapes (PostgREST numerics as strings).
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
  directions: { eps_gaap: { period: "full year 2026", mid: 18.81, prev_mid: 16.36,
    direction: "raised", recorded_at: "2026-11-03T21:05:44+00:00" } },
  fundamentals: { cash: { value: 9129000000, as_of: "2025-12-31" },
    eps_diluted: { value: 14.23, as_of: "2025-12-31" }, missing: [] },
  inputs: { guidance_records: [
    { metric: "eps_gaap", period: "full year 2026", low: 18.34, high: 19.28,
      consensus: null, accession: "0000318154-26-000153",
      created_at: "2026-11-03T21:05:44+00:00" } ] },
  computed_at: "2026-11-09T18:00:00Z",
};

const CVS = {
  ...AMGN, ticker: "CVS", peer_group: "health_care_services",
  peer_multiple: "11.13", peer_count: 5, price: "85.17",
  anchor: { metric: "eps_adjusted", period: "full year 2026", period_key: "FY2026",
    low: 8.2, high: 8.2, mid: 8.2, point_guide: true, consensus: null,
    recorded_at: "2026-11-05T12:00:00+00:00", accession: "0000950103-26-000001" },
  bands: { bear: 82.11, base: 91.23, bull: 91.23 }, implied_eps: "7.65",
  gap_range_widths: null, baseline_verdict: "buy_zone",
  directions: { eps_adjusted: { period: "full year 2026", mid: 8.2,
    direction: "first", recorded_at: "2026-11-05T12:00:00+00:00" } },
  falsifier: "Falsified if CVS guides FY2026 EPS below 8.20.",
};

const LLY = {
  ...AMGN, ticker: "LLY", band_basis: "revenue", peer_group: "pharmaceuticals",
  peer_multiple: "3.81", peer_count: 7, price: "1395.48",
  anchor: { metric: "revenue", period: "full year 2026", period_key: "FY2026",
    low: 91000000000, high: 92000000000, mid: 91500000000, point_guide: false,
    consensus: null, recorded_at: "2026-11-04T12:00:00+00:00",
    accession: "0000059478-26-000101" },
  bands: { bear: 347.35, base: 388.07, bull: 390.19 }, implied_eps: null,
  implied_revenue: "366000000000", gap_range_widths: "237.53",
  baseline_verdict: "short_zone_strong",
  directions: { revenue: { period: "full year 2026", mid: 91500000000,
    direction: "held", recorded_at: "2026-11-04T12:00:00+00:00" } },
  falsifier: "Falsified if LLY guides FY2026 revenue below the recorded low end.",
};

const KO = {
  ...AMGN, ticker: "KO", status: "guide_rejected", bands: null, anchor: null,
  baseline_verdict: "no_bands", peer_group: "soft_drinks_and_non_alcoholic_beverages",
  falsifier: "No band to falsify: KO has no usable full-year guide on record on either basis (EPS or revenue). The next recorded full-year guide creates the bands.",
  directions: { eps_adjusted: { period: "Full Year 2026", mid: 9.0,
    direction: "first", recorded_at: "2026-10-27T10:58:13+00:00" } },
  inputs: { guidance_records: [
    { metric: "eps_adjusted", period: "Full Year 2026", low: 9.0, high: 9.0,
      consensus: 3.34, accession: "0000051143-26-000077",
      created_at: "2026-10-27T10:58:13+00:00" } ] },
};

const AAPL = {
  ...AMGN, ticker: "AAPL", status: "no_full_year_guide", bands: null,
  anchor: null, baseline_verdict: "no_bands", peer_group: null,
  peer_multiple: null, peer_count: null, peer_basis: null,
  falsifier: "No band to falsify: AAPL has no usable full-year guide on record on either basis (EPS or revenue).",
  directions: {}, inputs: { guidance_records: [] },
};

const SHEETS = [AMGN, CVS, LLY, KO, AAPL];

const AMGN_DETAIL = { ...AMGN,
  peer_members: ["ABBV", "AMGN", "BIIB", "GILD", "INCY", "MRNA", "REGN", "VRTX"] };

function serve() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/valuation-bands/AMGN")) {
      return new Response(JSON.stringify(AMGN_DETAIL), { status: 200 });
    }
    if (url.includes("/api/valuation-bands")) {
      return new Response(JSON.stringify(SHEETS), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Valuation tab", () => {
  it("states plainly that zones are display-only, not trade recommendations", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    expect(await screen.findByText(/not trade recommendations/i)).toBeInTheDocument();
  });

  it("summarizes coverage and zones in the header strip", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const strip = await screen.findByTestId("valuation-summary");
    expect(strip).toHaveTextContent("5 fact sheets");
    expect(strip).toHaveTextContent("3 banded");
    expect(strip).toHaveTextContent("2 EPS basis");
    expect(strip).toHaveTextContent("1 revenue basis");
    expect(strip).toHaveTextContent("1 in a buy zone");
    expect(strip).toHaveTextContent("2 in short zones");
    expect(strip).toHaveTextContent("2 not banded");
  });

  it("keeps the two bases in separate, labeled tables", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const eps = await screen.findByTestId("basis-eps");
    const rev = screen.getByTestId("basis-revenue");
    expect(within(eps).getByText("AMGN")).toBeInTheDocument();
    expect(within(eps).getByText("CVS")).toBeInTheDocument();
    expect(within(eps).queryByText("LLY")).toBeNull();
    expect(within(rev).getByText("LLY")).toBeInTheDocument();
    expect(within(rev).getByText("FY2026 revenue $91.00–92.00B")).toBeInTheDocument();
    expect(within(eps).getByText("FY2026 EPS 18.34–19.28")).toBeInTheDocument();
  });

  it("shows the guide direction and the zone in plain words", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const eps = await screen.findByTestId("basis-eps");
    expect(within(eps).getByText("Strong short zone")).toBeInTheDocument();
    expect(within(eps).getByText("Buy zone")).toBeInTheDocument();
    expect(within(eps).getByText("Raised")).toBeInTheDocument();
  });

  it("explains every zone in a legend", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const legend = await screen.findByTestId("zone-legend");
    expect(legend).toHaveTextContent("Strong buy zone");
    expect(legend).toHaveTextContent("No-chase");
    expect(legend).toHaveTextContent("guide midpoint");
  });

  it("lists unbanded names with their state and the recorded reason", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const un = await screen.findByTestId("unbanded");
    expect(within(un).getByText("KO")).toBeInTheDocument();
    expect(within(un).getByText("AAPL")).toBeInTheDocument();
    expect(within(un).getByText(/rejected by the guards/i)).toBeInTheDocument();
    expect(within(un).getByText(/No full-year guide on record/i)).toBeInTheDocument();
    // Both sheets' recorded notes carry the phrase; presence is the assertion.
    expect(within(un).getAllByText(/no usable full-year guide on record/i).length).toBeGreaterThan(0);
  });

  it("expands a banded row into the band chart and the full fact sheet", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const eps = await screen.findByTestId("basis-eps");
    fireEvent.click(within(eps).getByRole("button", { name: /AMGN/ }));
    // The band chart: bear/base/bull bar with the price marked.
    const chart = await screen.findByTestId("band-chart-AMGN");
    expect(chart).toHaveTextContent("Bear $272.18");
    expect(chart).toHaveTextContent("Bull $317.92");
    expect(chart).toHaveTextContent("Price $460.42");
    // Provenance + peers (detail fetch) + falsifier. The accession appears in
    // both the provenance block and the records table -- correctly, twice.
    expect((await screen.findAllByText("0000318154-26-000153")).length).toBeGreaterThan(0);
    expect(await screen.findByText(/ABBV/)).toBeInTheDocument();
    expect(screen.getByText(/Falsified if AMGN guides/)).toBeInTheDocument();
    expect(screen.getByText("Biotechnology")).toBeInTheDocument();
  });
});
