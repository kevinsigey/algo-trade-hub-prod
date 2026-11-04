import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import GapDesk, { type GapDeskPayload } from "@/components/GapDesk";

const SCORE = { n: 0, model_brier: null, market_brier: null, brier_delta: null, model_log_loss: null,
                market_log_loss: null, calibration: [] };
const EMPTY: GapDeskPayload = {
  as_of: "2026-11-04T12:15:00Z", started_at: "2026-11-04T12:15:00Z",
  evidence: { status: "NOT ENOUGH EVIDENCE", days: 0.2, pairs: 0, min_days: 28, min_pairs: 150 },
  grade: { all: SCORE, crypto: SCORE, oil: SCORE },
  ledger: { bankroll: 10000, return_pct: 0, max_drawdown_pct: 0, resolved: 0, open: 0, win_rate: null, avg_entry_gap_pts: null },
  gross_only: false, open_positions: [], closed_positions: [], top_gaps: [], near_misses: [], funnel: {},
};

function serve(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })));
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("GapDesk", () => {
  it("leads with the evidence status and shows unknowns as dashes", async () => {
    serve(EMPTY);
    render(<GapDesk category="oil" />);
    expect(await screen.findByText(/NOT ENOUGH EVIDENCE: 0.2 of 28 days, 0 of 150 paired forecasts/)).toBeInTheDocument();
    expect(screen.getByText(/Paper ledger, no orders/)).toBeInTheDocument();
    expect(screen.getByText("Paper return (net)")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(1);
    expect(screen.queryByText(/buy|sell/i)).toBeNull();
  });

  it("shows this desk's passing gaps, labels gross P&L and marks an unknown exit", async () => {
    serve({
      ...EMPTY, gross_only: true,
      top_gaps: [
        { ticker: "KXWTI-A", category: "oil", side: "yes", model_prob: 0.7, yes_ask: 0.6, no_ask: 0.4, gap_pts: 10, failed: [], settles_at: "x" },
        { ticker: "KXBTC-B", category: "crypto", side: "no", model_prob: 0.2, yes_ask: 0.3, no_ask: 0.7, gap_pts: 10, failed: [], settles_at: "x" },
      ],
      open_positions: [{ ticker: "KXWTI-A", category: "oil", side: "yes", model_at_entry: 0.7, entry_price: 0.6, gap_pts: 10, contracts: 100, exit_state: "UNKNOWN: gap_closed but no bid" }],
    });
    render(<GapDesk category="oil" />);
    expect(await screen.findByText("Paper return (gross)")).toBeInTheDocument();
    expect(screen.getByText("UNKNOWN: gap_closed but no bid")).toBeInTheDocument();
    expect(screen.queryByText("KXBTC-B")).toBeNull();
  });

  it("renders nothing when the read fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));
    const { container } = render(<GapDesk category="crypto" />);
    await new Promise((r) => setTimeout(r, 0));
    expect(container).toBeEmptyDOMElement();
  });
});
