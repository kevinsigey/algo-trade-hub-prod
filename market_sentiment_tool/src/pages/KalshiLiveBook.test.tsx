import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Portfolio from "@/pages/Portfolio";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const PILOT = {
  state: "live", real_money: true, enabled: true, halted: false, halt_reason: null,
  balance: 10.25, balance_at: "2026-11-24T15:00:00Z", pnl_since_start: 0.57,
  decisions: 1, fills: 1, fill_rate: 1, mean_slippage_cents: 1, settled: 1,
  live_net_per_contract: 0.57, live_low95_cents: null, paper_net_per_contract: 0.58,
  paper_low95_cents: null, latency_median_s: 120,
  gates: {
    execution: { state: "pending", fills: 1, bar: 50, mean_slippage_cents: null },
    edge: { state: "pending", settled: 1, bar: 150, low95_cents: null, stage3_unlocked: false },
  },
  daily_stop_usd: 2, floor_usd: 5,
  orders: [{
    id: 7, created_at: "2026-11-24T15:00:00Z", series: "KXWTI15M", ticker: "KXWTI15M-26NOV241000-00",
    side: "yes", status: "settled", skip_reason: null, contracts_requested: 1, contracts_filled: 1,
    frozen_quote: 0.4, live_ask: 0.41, fill_price: 0.41, fee_usd: 0.02, outcome: 1, pnl: 0.57,
    paper_pnl: 0.58, window_close: "2026-11-24T15:15:00Z",
  }],
};

function show(pilot: unknown) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new Response(
    JSON.stringify(String(input).includes("/api/kalshi-demo")
      ? { state: "not_connected", demo: true, note: "n", live_pilot: pilot }
      : { books: [] }), { status: 200 })));
  render(<MemoryRouter initialEntries={["/portfolio?book=kalshi"]}><Portfolio /></MemoryRouter>);
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Kalshi live book", () => {
  it("renders the tab link with its REAL MONEY badge", async () => {
    show({ admin_only: true });
    const link = await screen.findByRole("link", { name: /Kalshi live/ });
    expect(link).toHaveAttribute("href", "/portfolio?book=kalshi");
    expect(within(link).getByText("REAL MONEY")).toBeInTheDocument();
  });

  it("admin payload shows balance, state and the orders table", async () => {
    show(PILOT);
    expect(await screen.findByText("KXWTI15M-26NOV241000-00")).toBeInTheDocument();
    expect(screen.getAllByText("$10.25").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Running")).toBeInTheDocument();
    // The orders table is the Positions card's open view.
    fireEvent.click(screen.getByRole("button", { name: "Open Positions" }));
    expect(screen.getByRole("columnheader", { name: "Slippage" })).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("1.0¢")).toBeInTheDocument();
  });

  it("admin_only payload shows the sign-in line", async () => {
    show({ admin_only: true });
    expect(await screen.findByText("Live pilot: sign in as admin to see the real-money account.")).toBeInTheDocument();
  });

  it("empty state explains why there are no orders", async () => {
    show({ ...PILOT, orders: [] });
    expect(await screen.findByText(/No orders yet: the lane only buys when the oil & gas rule clears its 10-point bar\./)).toBeInTheDocument();
  });
});
