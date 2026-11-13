import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import KalshiDemoBook from "@/pages/KalshiDemoBook";
import Portfolio from "@/pages/Portfolio";

// Portfolio lists live ideas through the signed admin fetch, which loads the Supabase client: stub it (no session).
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const NOTE = "Demo account, fake money, demo order book. Demo fills don't prove the edge; the shadow record is the measure.";

const LIVE = {
  state: "live",
  demo: true,
  as_of: "2026-11-12T17:00:00Z",
  balance: 505,
  starting_balance: 500,
  pnl_since_start: 7.5,
  pnl_today: 2.3,
  positions_unavailable: false,
  positions: [{
    ticker: "KXNATGAS15M-26NOV121215-00", series: "KXNATGAS15M", strike: 2.5,
    side: "yes", contracts: 12, avg_price: 0.4, yes_bid: 0.45, yes_ask: 0.47,
    open_pnl: 0.6, close_time: "2026-11-12T17:05:00Z",
  }],
  performance: {
    demo_curve: [{ at: "2026-11-12T15:00:00Z", pnl: -4.3 }, { at: "2026-11-12T16:00:00Z", pnl: 2.3 }],
    shadow_curve: [{ at: "2026-11-12T15:00:00Z", pnl: -4.3 }, { at: "2026-11-12T16:00:00Z", pnl: 2.3 }],
    shadow_curve_per_contract: [{ at: "2026-11-12T15:00:00Z", pnl: -0.43 }, { at: "2026-11-12T16:00:00Z", pnl: 0.12 }],
    fill_rate: 0.6667, avg_slippage_cents: 0.5, win_rate: 0.5, pnl_per_contract: 0.1045,
    decisions_not_traded: { caps: 1, no_depth: 1, missed: 1 },
  },
  lanes: [
    { gate_version: "v1", orders: 1, settled: 1, win_rate: 1, pnl: 6.6, pnl_per_contract: 0.55 },
  ],
  orders: [{
    id: 1, created_at: "2026-11-12T15:50:00Z", target: "kalshi:KXNATGAS15M-26NOV121200-00",
    ticker: "KXNATGAS15M-26NOV121200-00", side: "yes", gate_version: "v1",
    contracts: 12, contracts_filled: 12, limit_price: 0.4, frozen_quote: 0.4,
    ask_size: 90, status: "settled", skip_reason: null, fill_price: 0.41,
    filled_at: "2026-11-12T15:52:00Z", window_close: "2026-11-12T16:00:00Z",
    outcome: 1, settlement_pnl: 6.6,
  }],
  note: NOTE,
};

function serveKalshi(kalshiBody: unknown) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/kalshi-demo")) {
      return new Response(JSON.stringify(kalshiBody), { status: 200 });
    }
    if (url.includes("/api/portfolio/books")) {
      return new Response(JSON.stringify({
        books: [
          { book: "main", label: "Main book" },
          { book: "big", label: "$1M book" },
        ],
      }), { status: 200 });
    }
    return new Response(JSON.stringify({
      state: "not_connected", as_of: null, scoreboard: null,
      curve: [], composition: [], positions: [],
    }), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("Kalshi (demo) Portfolio tab", () => {
  it("renders the third tab with its DEMO badge and the demo book, not the Alpaca body", async () => {
    serveKalshi(LIVE);
    render(
      <MemoryRouter initialEntries={["/portfolio?book=kalshi"]}>
        <Portfolio />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Kalshi (demo)")).toBeInTheDocument();
    expect(screen.getAllByText("DEMO").length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByText("$505.00")).toBeInTheDocument();
    expect(screen.getByText(NOTE)).toBeInTheDocument();
    expect(screen.getByText("KXNATGAS15M-26NOV121215-00")).toBeInTheDocument();
    expect(screen.getByText("KXNATGAS15M-26NOV121200-00")).toBeInTheDocument();
    expect(screen.queryByText("Net liquidation value")).toBeNull();
    expect(screen.queryByRole("button", { name: /buy|sell|place order/i })).toBeNull();
  });

  it("shows the not-connected empty state when the demo key is unset", async () => {
    serveKalshi({ state: "not_connected", demo: true, note: NOTE });
    render(
      <MemoryRouter initialEntries={["/portfolio?book=kalshi"]}>
        <Portfolio />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Kalshi demo account not connected")).toBeInTheDocument();
    expect(screen.getByText(NOTE)).toBeInTheDocument();
  });

  it("refetches every 30 seconds", async () => {
    vi.useFakeTimers();
    const fetchMock = serveKalshi(LIVE);
    render(
      <MemoryRouter>
        <KalshiDemoBook />
      </MemoryRouter>,
    );
    await act(async () => {});
    const kalshiCalls = () =>
      fetchMock.mock.calls.filter(([u]) => String(u).includes("/api/kalshi-demo")).length;
    expect(kalshiCalls()).toBe(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(kalshiCalls()).toBe(2);
  });

  it("shows a failed refresh alongside the last good report", async () => {
    vi.useFakeTimers();
    let kalshiCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/kalshi-demo")) {
        kalshiCalls += 1;
        if (kalshiCalls > 1) throw new Error("network down");
        return new Response(JSON.stringify(LIVE), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    render(
      <MemoryRouter>
        <KalshiDemoBook />
      </MemoryRouter>,
    );
    await act(async () => {});
    expect(screen.getByText("$505.00")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(screen.getByText(/Refresh failed/)).toBeInTheDocument();
    // The retained report is still on screen, marked with its as_of time.
    expect(screen.getByText("$505.00")).toBeInTheDocument();
    expect(screen.getByText(/showing the last report, as of/)).toBeInTheDocument();
  });

  it("gives the demo book the card treatment: every card renders and opens to its detail", async () => {
    serveKalshi(LIVE);
    render(<MemoryRouter><KalshiDemoBook /></MemoryRouter>);
    expect(await screen.findByText("$505.00")).toBeInTheDocument();
    for (const name of ["Demo balance", "P&L today", "Open positions", "Demo vs shadow", "Positions", "Orders"]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
    // The performance card opens to every stat and the curve.
    const opener = screen.getByRole("button", { name: "Open Demo vs shadow" });
    opener.focus();
    fireEvent.click(opener);
    const full = within(screen.getByRole("dialog"));
    expect(full.getByText("Avg slippage vs frozen quote")).toBeInTheDocument();
    expect(full.getByText(/caps 1 · no depth 1 · missed 1/)).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
    // Positions and orders open to their full tables.
    fireEvent.click(screen.getByRole("button", { name: "Open Positions" }));
    expect(within(screen.getByRole("dialog")).getByText("$0.45 / $0.47")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Open Orders" }));
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: /Fill/ })).toBeInTheDocument();
  });

  it("shows at most 5 orders on the page and every order in the open view", async () => {
    const orders = Array.from({ length: 8 }, (_, i) => ({
      ...LIVE.orders[0], id: i + 1, ticker: `KXNATGAS15M-T${i}`, created_at: `2026-11-12T15:0${i}:00Z`,
    }));
    serveKalshi({ ...LIVE, orders });
    render(<MemoryRouter><KalshiDemoBook /></MemoryRouter>);
    expect(await screen.findByText("$505.00")).toBeInTheDocument();
    const card = screen.getByRole("region", { name: "Orders" });
    expect(card.querySelectorAll("[data-peek] li")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "Open Orders" }));
    expect(within(screen.getByRole("dialog")).getAllByRole("row")).toHaveLength(1 + 8);
  });

  it("shows unavailable positions as a dash, not 0", async () => {
    serveKalshi({ ...LIVE, positions: [], positions_unavailable: true });
    render(<MemoryRouter><KalshiDemoBook /></MemoryRouter>);
    expect(await screen.findByText("$505.00")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Positions" })).getByText("—")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Open positions" })).getByText("—")).toBeInTheDocument();
  });
});

describe("Kalshi demo lanes", () => {
  it("shows each lane's own record in the Orders card when two lanes have traded", async () => {
    serveKalshi({
      ...LIVE,
      lanes: [
        { gate_version: "v1", orders: 4, settled: 3, win_rate: 0.6667, pnl: 6.6, pnl_per_contract: 0.55 },
        { gate_version: "v4-edge20-shadow", orders: 2, settled: 1, win_rate: 0, pnl: -2.4, pnl_per_contract: -0.4 },
      ],
    });
    render(<MemoryRouter><KalshiDemoBook /></MemoryRouter>);
    expect(await screen.findByText("$505.00")).toBeInTheDocument();
    const card = screen.getByRole("region", { name: "Orders" });
    expect(within(card).getByText("v4-edge20-shadow")).toBeInTheDocument();
    expect(within(card).getByText(/1 settled/)).toBeInTheDocument();
    expect(within(card).getByText(/3 settled/)).toBeInTheDocument();
  });
});
