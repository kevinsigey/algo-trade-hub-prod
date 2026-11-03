import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import ClosedTrades from "@/pages/ClosedTrades";
import Portfolio from "@/pages/Portfolio";
import type { ActivityPayload, ClosedPayload, PortfolioPayload } from "@/lib/paperPortfolio";

// Portfolio lists live ideas through the signed admin fetch, which loads the Supabase client: stub it (no session).
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

function serve(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })));
}

const EMPTY_SCORE = {
  start_at: null, equity: null, return_pct: null, spy_return_pct: null, ahead_pts: null,
  max_drawdown_pct: null, sharpe: null, win_rate: null,
};

function payload(over: Partial<PortfolioPayload>): PortfolioPayload {
  return {
    state: "live", as_of: "2026-11-10T20:41:00Z", account_number: "PA2", scoreboard: EMPTY_SCORE,
    curve: [], composition: [], positions: [], ...over,
  };
}

const page = (el: JSX.Element) => render(<MemoryRouter>{el}</MemoryRouter>);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Portfolio", () => {
  it("says the account is not connected and shows no dollar figure", async () => {
    serve(payload({ state: "not_connected", as_of: null }));
    page(<Portfolio />);
    expect(await screen.findByText("Paper account not connected")).toBeInTheDocument();
    expect(screen.queryByText(/\$0/)).toBeNull();
  });

  it("labels a pre-start test account and shows unknown returns as dashes", async () => {
    serve(payload({
      state: "pre_start",
      scoreboard: { ...EMPTY_SCORE, equity: 100000, start_at: "2026-11-10T20:41:00Z" },
      positions: [{ symbol: "Cash", qty: null, side: null, market_value: 100000, pct_of_book: 100, unrealized_pl: null, idea: null }],
    }));
    page(<Portfolio />);
    expect(await screen.findByText(/^Paper account · not traded yet/)).toBeInTheDocument();
    // The boxes layout (2026-11-02): the equity figure, the Account box's Cash
    // rail row, the positions table's Cash row, and the Composition treemap's
    // Cash tile (tiles carry their value since the sector rebuild) read $100,000.
    expect(screen.getAllByText("$100,000").length).toBe(4);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText("+0.0%")).toBeNull();
  });

  it("shows the scoreboard, the manual bucket and every position", async () => {
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 104820, return_pct: 4.82, spy_return_pct: 2.1, ahead_pts: 2.72, win_rate: 58 },
      composition: [{ idea: "No idea yet (manual)", pct_of_book: 21, unrealized_pl: 640 }],
      positions: [
        { symbol: "GLD", qty: 60, side: "long", market_value: 21900, pct_of_book: 21, unrealized_pl: 640, idea: "No idea yet (manual)" },
        { symbol: "Cash", qty: null, side: null, market_value: 41200, pct_of_book: 39, unrealized_pl: null, idea: null },
      ],
    }));
    page(<Portfolio />);
    expect(await screen.findByText("+4.8%")).toBeInTheDocument();
    expect(screen.getByText("+2.7 pts")).toBeInTheDocument();
    expect(screen.getByText("58%")).toBeInTheDocument();
    expect(screen.getByText("Paper account · live · as of 2:41 PM CT, Tue Nov 10")).toBeInTheDocument();
    expect(screen.getAllByText("No idea yet (manual)").length).toBe(2);
    expect(screen.getByText("Every position · 1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Trades and Orders/ })).toHaveAttribute("href", "/portfolio/closed");
  });
});

describe("Portfolio hand orders (signed-in only)", () => {
  function serveRoutes(adminOk: boolean, posted: Record<string, unknown>[]) {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/portfolio/open-orders")) {
        return new Response(JSON.stringify({ orders: [{
          alpaca_order_id: "a9", client_order_id: "ext-1-stop-mirror-xom", symbol: "XOM",
          side: "sell", type: "stop", time_in_force: "gtc", qty: 49, filled_qty: 0,
          limit_price: null, stop_price: 175, status: "new", submitted_at: "2026-11-02T14:31:00Z",
        }] }), { status: 200 });
      }
      if (url.includes("/api/portfolio/orders")) {
        posted.push(JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>);
        return new Response(JSON.stringify({ order: { id: "a1" }, client_order_id: "manual-abc123", placed_by: "k@example.com" }), { status: 200 });
      }
      if (url.includes("/api/admin/me")) {
        return adminOk
          ? new Response(JSON.stringify({ email: "k@example.com" }), { status: 200 })
          : new Response(JSON.stringify({ detail: "admin only" }), { status: 401 });
      }
      if (url.includes("/api/workshop/ideas")) return new Response(JSON.stringify([]), { status: 200 });
      return new Response(JSON.stringify(payload({})), { status: 200 });
    }));
  }

  it("shows no order form to a signed-out visitor", async () => {
    serveRoutes(false, []);
    page(<Portfolio />);
    expect(await screen.findByText("Every position · 0")).toBeInTheDocument();
    expect(screen.queryByText("Place an order by hand")).toBeNull();
  });

  it("shows the staged orders panel, signed in only", async () => {
    serveRoutes(true, []);
    page(<Portfolio />);
    expect(await screen.findByText("Staged orders")).toBeInTheDocument();
    expect(await screen.findByText("XOM")).toBeInTheDocument();
    expect(screen.getByText("$175.00")).toBeInTheDocument();
    expect(screen.getByText("gtc")).toBeInTheDocument();
  });

  it("hides the staged orders panel from a signed-out visitor", async () => {
    serveRoutes(false, []);
    page(<Portfolio />);
    expect(await screen.findByText("Every position · 0")).toBeInTheDocument();
    expect(screen.queryByText("Staged orders")).toBeNull();
  });

  it("places a market order through the endpoint when signed in", async () => {
    const posted: Record<string, unknown>[] = [];
    serveRoutes(true, posted);
    page(<Portfolio />);
    expect(await screen.findByText("Place an order by hand")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "xle" } });
    fireEvent.change(screen.getByLabelText("Shares"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Place order" }));
    expect(await screen.findByText(/Order sent: buy 3 XLE \(manual-abc123\)/)).toBeInTheDocument();
    expect(posted).toEqual([{ symbol: "XLE", qty: 3, side: "buy", order_type: "market", time_in_force: "day" }]);
  });
});

describe("ClosedTrades", () => {
  it("has an empty state", async () => {
    serve({ state: "live", as_of: "2026-11-10T20:41:00Z", open: [], recent: [], trades: [] } satisfies ActivityPayload);
    page(<ClosedTrades />);
    expect(await screen.findByText("No closed trades yet.")).toBeInTheDocument();
    expect(screen.getByText("No working orders right now.")).toBeInTheDocument();
  });

  it("shows each trade's result", async () => {
    serve({
      state: "live", as_of: "2026-11-10T20:41:00Z", open: [], recent: [],
      trades: [{ symbol: "GLD", qty: 10, entry_price: 200, exit_price: 225, entered_at: "2026-11-02T15:00:00Z",
                 exited_at: "2026-11-05T15:00:00Z", pnl: 250, return_pct: 12.5, held_days: 3, idea: "No idea yet (manual)" }],
    } satisfies ActivityPayload);
    page(<ClosedTrades />);
    expect((await screen.findAllByText("+$250.00")).length).toBe(2); // the row and the total
    expect(screen.getByText("+12.5%")).toBeInTheDocument();
    expect(screen.getByText("3d")).toBeInTheDocument();
  });
});
