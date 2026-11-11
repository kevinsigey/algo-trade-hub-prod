import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const payload = {
  state: "live", as_of: "2026-11-03T00:21:46Z",
  open: [{ symbol: "GLD", side: "buy", qty: 28, filled_qty: 0, type: "market", time_in_force: "opg",
           status: "accepted", limit_price: null, stop_price: null, filled_avg_price: null,
           submitted_at: "2026-11-03T12:30:00Z", filled_at: null, asset: "stock", source: "Workshop idea" }],
  recent: [{ symbol: "XLE", side: "buy", qty: 1, filled_qty: 1, type: "market", time_in_force: "day",
             status: "filled", limit_price: null, stop_price: null, filled_avg_price: 68.1,
             submitted_at: "2026-11-02T14:00:00Z", filled_at: "2026-11-02T14:00:01Z", asset: "stock", source: "Manual" }],
  trades: [],
};

const { state } = vi.hoisted(() => ({ state: { payload: null as unknown } }));
vi.mock("@/hooks/usePaperPortfolio", () => ({
  useApi: () => ({ data: state.payload, error: null, loading: false }),
}));
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: null } }) } },
}));

import ClosedTrades from "./ClosedTrades";

describe("Trades and Orders page", () => {
  it("shows open orders, the recent tape, and the closed-trades section together", () => {
    state.payload = payload;
    render(<MemoryRouter><ClosedTrades /></MemoryRouter>);
    expect(screen.getByText(/Open orders · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Recent orders · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Closed trades · 0/)).toBeInTheDocument();
    expect(screen.getByText("GLD")).toBeInTheDocument();
    expect(screen.getByText("XLE")).toBeInTheDocument();
    expect(screen.getByText("No closed trades yet.")).toBeInTheDocument();
  });

  it("splits closed results into tested ideas and discretionary trades, with reasons", () => {
    state.payload = {
      ...payload,
      trades: [
        { symbol: "AAA", qty: 10, entry_price: 100, exit_price: 102, entered_at: "2026-11-01T15:00:00Z",
          exited_at: "2026-11-03T15:00:00Z", pnl: 268.5, return_pct: 2, held_days: 2, idea: "T8 Core" },
        { symbol: "BBB", qty: 5, entry_price: 50, exit_price: 49, entered_at: "2026-11-02T15:00:00Z",
          exited_at: "2026-11-04T15:00:00Z", pnl: -1752, return_pct: -2, held_days: 2, idea: "No idea yet (manual)" },
      ],
      results_split: {
        tested: { trades: 1, pnl: 268.5, wins: 1 },
        discretionary: { trades: 1, pnl: -1752, wins: 0,
                         reasons: [{ reason: "no reason recorded", trades: 1, pnl: -1752 }] },
      },
    };
    render(<MemoryRouter><ClosedTrades /></MemoryRouter>);
    expect(screen.getByText("Results by kind")).toBeInTheDocument();
    expect(screen.getByText("Tested ideas")).toBeInTheDocument();
    expect(screen.getAllByText("+$268.50").length).toBeGreaterThan(0);
    expect(screen.getByText("Discretionary")).toBeInTheDocument();
    expect(screen.getAllByText("−$1,752.00").length).toBeGreaterThan(0);
    expect(screen.getByText(/no reason recorded/)).toBeInTheDocument();
  });
});
