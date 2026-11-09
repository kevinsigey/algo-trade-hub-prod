import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import BandCrossings from "@/pages/BandCrossings";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const PAYLOAD = {
  mode: "log_only",
  orders_enabled: false,
  falsifier: { gate: 20, graded: 0, mean_score: null, status: "accruing" },
  scans: [{ id: 1, kind: "baseline", started_at: "2026-11-09T13:00:00Z",
            banded_names: 21, crossings_written: 0 }],
  crossings: [
    { id: 2, created_at: "2026-11-10T13:00:00Z", scan_kind: "event", book: "main",
      ticker: "CVS", industry: "health_care_services", band_basis: "eps",
      bear: "82.11", base: "91.23", bull: "91.23", price: "85.17",
      price_as_of: "2026-11-07", zone: "base", prev_action: null,
      action: "starter", target_pct: "2.0", delta_usd: "2000.00",
      held_mv: "0", guide_status: "intact", guide_direction: "first",
      t1_classification: null, suppress_reason: null,
      pc_outcome: "would_pass", pc_detail: "portfolio check passes",
      mode: "log_only", outcome_20: null, score_20: null },
    { id: 1, created_at: "2026-11-10T13:00:00Z", scan_kind: "event", book: "big",
      ticker: "CEG", industry: "Utilities", band_basis: "eps",
      bear: "185.90", base: "215.54", bull: "224.52", price: "249.95",
      price_as_of: "2026-11-07", zone: "above_bull", prev_action: null,
      action: "none", target_pct: null, delta_usd: null,
      held_mv: "0", guide_status: "raised", guide_direction: "raised",
      t1_classification: null, suppress_reason: "no_t1_classification",
      pc_outcome: null, pc_detail: null,
      mode: "log_only", outcome_20: null, score_20: null },
  ],
};

function serve(payload: unknown = PAYLOAD) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/band-crossings")) {
      return new Response(JSON.stringify(payload), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Band crossings section", () => {
  it("states log-only up front and lists crossings with their check outcomes", async () => {
    serve();
    render(<BandCrossings />);
    const section = await screen.findByTestId("band-crossings");
    expect(await within(section).findByText(/LOG-ONLY/)).toBeTruthy();
    expect(within(section).getByText(/0\/20 graded/)).toBeTruthy();
    expect(within(section).getByText("CVS")).toBeTruthy();
    expect(within(section).getByText(/Starter to 2% of book/)).toBeTruthy();
    expect(within(section).getByText("would pass")).toBeTruthy();
    // The spec's worked example: CEG above its bull band is NOT a long —
    // it reads as no action, gated on the missing T1 classification.
    expect(within(section).getByText(/No action — no T1 classification on file/)).toBeTruthy();
  });

  it("expands a row to the full record, portfolio-check detail included", async () => {
    serve();
    render(<BandCrossings />);
    const section = await screen.findByTestId("band-crossings");
    fireEvent.click(within(section).getByLabelText("Detail for CVS crossing 2"));
    await waitFor(() => {
      expect(within(section).getByText(/Portfolio check: portfolio check passes/)).toBeTruthy();
    });
    expect(within(section).getByText(/bands bear 82.11 \/ base 91.23 \/ bull 91.23/)).toBeTruthy();
  });

  it("renders the empty state before any crossing exists", async () => {
    serve({ ...PAYLOAD, crossings: [] });
    render(<BandCrossings />);
    const section = await screen.findByTestId("band-crossings");
    expect(await within(section).findByText(/No crossings yet/)).toBeTruthy();
  });
});
