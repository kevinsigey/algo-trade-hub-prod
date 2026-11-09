import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: null } }), onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }) } },
}));

import ValuationDebates from "@/components/ValuationDebates";

// A verdict shaped like the Phase 1 API contract: AMGN priced far above its
// bull band, judged a strong short zone, with a put-spread expression whose
// implied move underprices the distance back to the bands.
const VERDICT = {
  id: 7,
  ticker: "AMGN",
  rendered_at: "2026-11-09T15:30:00",
  trigger: "on_demand",
  judge: "free-ai-proposer",
  fact_sheet_id: 42,
  price: 460.42,
  price_as_of: "2026-11-06",
  bands: { bear: 272.18, base: 310.17, bull: 317.92 },
  band_basis: "eps",
  zone: "short_zone_strong",
  verdict: {
    choice_id: "act_at_band_mid",
    direction: "short",
    probability: 0.62,
    rationale: "The price implies far more than the guide supports, and nothing in the file closes that gap.",
  },
  baseline_verdict: "short_zone_strong",
  proposer_pick: { choice_id: "watch", direction: "short", probability: 0.55 },
  options_inputs: {
    implied_move_pct: 4.1,
    expression: "debit_put_spread",
    long_strike: 310.17,
    short_strike: 272.18,
    distance_to_target_pct: 12.3,
    underpriced: true,
  },
  falsifier: "A raised full-year guide that lifts the bull band above the price would void this verdict.",
  grades: {
    "20": { peer_excess_pct: 6.2, relative_pass: true, brier: 0.18 },
    "60": "pending",
  },
};

const FEED = {
  authority: { gate: 40, graded_verdicts: 12, relative_passes: 9, status: "display_only" },
  verdicts: [VERDICT],
  watch: { flags: [], pending_triggers: [] },
};

function serve(routes: Record<string, { status?: number; body: unknown }>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => url.includes(k));
    const hit = key ? routes[key] : { status: 200, body: {} };
    return new Response(JSON.stringify(hit.body), { status: hit.status ?? 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ValuationDebates", () => {
  it("renders a verdict card with both controls, the judge line, and its grades", async () => {
    serve({ "/api/valuation-verdicts": { body: FEED } });
    render(<ValuationDebates />);

    expect(await screen.findByText("AMGN")).toBeInTheDocument();
    expect(screen.getByText("Strong short zone")).toBeInTheDocument();
    expect(screen.getByText("Act at the mid band")).toBeInTheDocument();
    expect(screen.getByText(/short · 62%/)).toBeInTheDocument();
    expect(screen.getByText("Judge: free AI (proposer) — Jev seat pending credits")).toBeInTheDocument();
    expect(screen.getByText(/price implies far more than the guide supports/)).toBeInTheDocument();

    // Both controls, side by side: the band rule's zone and the proposer's own pick.
    expect(screen.getByText("Band rule: Strong short zone")).toBeInTheDocument();
    expect(screen.getByText("Proposer's own pick: Watch")).toBeInTheDocument();

    // The price-vs-bands bar states every level as chips, so labels never collide.
    expect(screen.getByText("Bear $272.18")).toBeInTheDocument();
    expect(screen.getByText("Base $310.17")).toBeInTheDocument();
    expect(screen.getByText("Bull $317.92")).toBeInTheDocument();
    expect(screen.getByText("Price $460.42")).toBeInTheDocument();

    expect(screen.getByText(/Options: debit put spread 310\.17 → 272\.18 — implied move 4\.1% underprices the 12\.3% distance/)).toBeInTheDocument();
    expect(screen.getByText(/Falsifier: A raised full-year guide/)).toBeInTheDocument();
    expect(screen.getByText("+20d: beat peers by 6.2% ✓")).toBeInTheDocument();
    expect(screen.getByText("+60d: pending")).toBeInTheDocument();
    expect(screen.getByText(/price as of 2026-11-06/)).toBeInTheDocument();
  });

  it("shows the display-only chip and the authority gate counts", async () => {
    serve({ "/api/valuation-verdicts": { body: FEED } });
    render(<ValuationDebates />);
    expect(await screen.findByText("Authority gate: 9/40 relative passes (12 graded)")).toBeInTheDocument();
    expect(screen.getAllByText("Display only — verdicts are graded, they do not feed ideas or orders").length).toBeGreaterThan(0);
  });

  it("posts a run, and on a reused verdict offers a fresh run with force", async () => {
    const f = serve({
      "/api/valuation-verdicts": { body: FEED },
      "/api/valuation-verdicts/run": { status: 200, body: { reused: 7, age_hours: 3 } },
    });
    render(<ValuationDebates />);
    await screen.findByText("AMGN");

    fireEvent.change(screen.getByLabelText("Run a valuation debate on a ticker"), { target: { value: "amgn" } });
    fireEvent.click(screen.getByRole("button", { name: "Run the valuation debate" }));
    expect(await screen.findByText(/AMGN already has a verdict from 3h ago/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run fresh anyway" }));
    await waitFor(() => {
      const posts = f.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
      expect(posts.length).toBe(2);
      expect(String(posts[0][0])).toContain("/api/valuation-verdicts/run");
      expect((posts[0][1] as RequestInit).body).toBe(JSON.stringify({ ticker: "AMGN", force: false }));
      expect((posts[1][1] as RequestInit).body).toBe(JSON.stringify({ ticker: "AMGN", force: true }));
    });
  });

  it("shows the server's detail when a run is refused (422)", async () => {
    serve({
      "/api/valuation-verdicts": { body: { ...FEED, verdicts: [] } },
      "/api/valuation-verdicts/run": { status: 422, body: { detail: "No fact sheet for ZZZ — the name is not banded." } },
    });
    render(<ValuationDebates />);
    fireEvent.change(screen.getByLabelText("Run a valuation debate on a ticker"), { target: { value: "ZZZ" } });
    fireEvent.click(screen.getByRole("button", { name: "Run the valuation debate" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No fact sheet for ZZZ — the name is not banded.");
  });

  it("renders band-watch flags with the potential-sell accent and the queued-trigger count", async () => {
    serve({
      "/api/valuation-verdicts": {
        body: {
          ...FEED,
          watch: {
            flags: [
              { book: "main", symbol: "AAPL", underlying: "AAPL", flag: "potential_sell", detail: "above_bull",
                price: 123.4, bands: { bear: 90, base: 105, bull: 115 } },
              { book: "big", symbol: "MSFT", underlying: "MSFT", flag: "comfortable_hold", detail: "inside_bands",
                price: 400, bands: { bear: 350, base: 420, bull: 480 } },
            ],
            pending_triggers: [
              { ticker: "AMGN", kind: "crossing", priority: "high", created_at: "2026-11-09T10:00:00" },
              { ticker: "XOM", kind: "new_guidance", priority: "normal", created_at: "2026-11-09T10:05:00" },
              { ticker: "HD", kind: "crossing", priority: "high", created_at: "2026-11-09T10:10:00" },
            ],
          },
        },
      },
    });
    render(<ValuationDebates />);
    expect(await screen.findByText("Band watch — held positions")).toBeInTheDocument();
    const sellLine = screen.getByText(/Potential sell — above the top band/);
    expect(sellLine.closest("div")?.className).toContain("amber");
    expect(screen.getByText(/Comfortable hold — inside its bands/)).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("3 debate triggers queued")).toBeInTheDocument();
  });

  it("shows the empty state when there are no verdicts, flags, or triggers yet", async () => {
    serve({
      "/api/valuation-verdicts": {
        body: {
          authority: { gate: 40, graded_verdicts: 0, relative_passes: 0, status: "display_only" },
          verdicts: [],
          watch: { flags: [], pending_triggers: [] },
        },
      },
    });
    render(<ValuationDebates />);
    expect(await screen.findByText(/No valuation verdicts yet — run the first one above/)).toBeInTheDocument();
    expect(screen.getByText("Authority gate: 0/40 relative passes (0 graded)")).toBeInTheDocument();
    expect(screen.queryByText("Band watch — held positions")).toBeNull();
  });
});
