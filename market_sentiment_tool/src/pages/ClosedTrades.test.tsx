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

vi.mock("@/hooks/usePaperPortfolio", () => ({
  useApi: () => ({ data: payload, error: null, loading: false }),
}));
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: null } }) } },
}));

import ClosedTrades from "./ClosedTrades";

describe("Trades and Orders page", () => {
  it("shows open orders, the recent tape, and the closed-trades section together", () => {
    render(<MemoryRouter><ClosedTrades /></MemoryRouter>);
    expect(screen.getByText(/Open orders · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Recent orders · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Closed trades · 0/)).toBeInTheDocument();
    expect(screen.getByText("GLD")).toBeInTheDocument();
    expect(screen.getByText("XLE")).toBeInTheDocument();
    expect(screen.getByText("No closed trades yet.")).toBeInTheDocument();
  });
});
