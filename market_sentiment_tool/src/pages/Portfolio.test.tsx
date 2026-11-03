import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import ClosedTrades from "@/pages/ClosedTrades";
import Portfolio from "@/pages/Portfolio";
import type { ActivityPayload, BooksPayload, PortfolioPayload } from "@/lib/paperPortfolio";

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
    expect(posted).toEqual([{ symbol: "XLE", qty: 3, side: "buy", order_type: "market", time_in_force: "day", book: "main" }]);
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

  it("reads the $1M book's activity when the URL names it, and the toggle keeps the book", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      urls.push(String(input));
      return new Response(JSON.stringify({ state: "live", as_of: "2026-11-10T20:41:00Z", book: "big", open: [], recent: [], trades: [] }), { status: 200 });
    }));
    render(<MemoryRouter initialEntries={["/portfolio/closed?book=big"]}><ClosedTrades /></MemoryRouter>);
    expect(await screen.findByText("No closed trades yet.")).toBeInTheDocument();
    expect(urls.some((u) => u.includes("/api/portfolio/activity?book=big"))).toBe(true);
    expect(screen.getByRole("link", { name: "$1M book" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Main book" })).toHaveAttribute("href", "/portfolio/closed?book=main");
  });
});

describe("Portfolio books (master view and the $1M book)", () => {
  const BOOKS: BooksPayload = {
    books: [
      { book: "main", label: "Main book", detail: "$100k paper account", state: "live", as_of: "2026-11-10T20:41:00Z",
        account_number: "PA2", equity: 104820, return_pct: 4.82, positions: 3, live_ideas: 2 },
      { book: "big", label: "$1M book", detail: "$1M paper account", state: "not_connected", as_of: null,
        account_number: null, equity: null, return_pct: null, positions: 0, live_ideas: 0 },
    ],
  };

  function serveBooks(urls: string[]) {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url.includes("/api/portfolio/books")) return new Response(JSON.stringify(BOOKS), { status: 200 });
      if (url.includes("/api/admin/me")) return new Response(JSON.stringify({ detail: "admin only" }), { status: 401 });
      if (url.includes("/api/workshop/ideas")) return new Response(JSON.stringify([]), { status: 200 });
      if (url.includes("/api/portfolio/closed")) return new Response(JSON.stringify({ state: "live", as_of: null, trades: [] }), { status: 200 });
      if (url.includes("book=big")) {
        return new Response(JSON.stringify(payload({
          book: "big", account_number: "PA3",
          scoreboard: { ...EMPTY_SCORE, equity: 1000000 },
          positions: [{ symbol: "Cash", qty: null, side: null, market_value: 1000000, pct_of_book: 100, unrealized_pl: null, idea: null }],
        })), { status: 200 });
      }
      return new Response(JSON.stringify(payload({
        scoreboard: { ...EMPTY_SCORE, equity: 104820, return_pct: 4.82 },
        positions: [{ symbol: "Cash", qty: null, side: null, market_value: 104820, pct_of_book: 100, unrealized_pl: null, idea: null }],
      })), { status: 200 });
    }));
  }

  it("opens as a master view: one card per book, the main book's full page below", async () => {
    const urls: string[] = [];
    serveBooks(urls);
    page(<Portfolio />);
    // The $1M card says plainly that it is not connected -- no invented numbers.
    const bigCard = await screen.findByRole("link", { name: /\$1M book/ });
    expect(bigCard).toHaveAttribute("href", "/portfolio?book=big");
    expect(bigCard.textContent).toContain("Paper account not connected");
    const mainCard = screen.getByRole("link", { name: /Main book/ });
    expect(mainCard).toHaveAttribute("href", "/portfolio?book=main");
    expect(mainCard.textContent).toContain("$104,820");
    expect(mainCard.textContent).toContain("2 live ideas");
    // Below the cards the main book's own page still renders (the record).
    expect(await screen.findByText("Every position · 0")).toBeInTheDocument();
  });

  it("scopes every read to the $1M book when ?book=big, with the switcher on top", async () => {
    const urls: string[] = [];
    serveBooks(urls);
    render(<MemoryRouter initialEntries={["/portfolio?book=big"]}><Portfolio /></MemoryRouter>);
    expect((await screen.findAllByText("$1,000,000")).length).toBeGreaterThanOrEqual(1);
    expect(urls.some((u) => u.includes("/api/portfolio?book=big"))).toBe(true);
    expect(urls.some((u) => u.includes("/api/portfolio/closed?book=big"))).toBe(true);
    expect(screen.getByRole("link", { name: "Master — both books" })).toHaveAttribute("href", "/portfolio");
    expect(screen.getByRole("link", { name: "$1M book" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /Trades and Orders/ })).toHaveAttribute("href", "/portfolio/closed?book=big");
    // The hand order form and staged orders are main-book doors; they stay off this page.
    expect(screen.queryByText("Place an order by hand")).toBeNull();
    expect(screen.queryByText("Staged orders")).toBeNull();
  });
});

describe("Manual actions box", () => {
  it("shows the hand-offs for the book in view and resolves them on click", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.includes("/api/admin/me")) return new Response(JSON.stringify({ email: "k" }), { status: 200 });
      if (url.includes("/api/portfolio/manual-actions") && url.includes("book=big")) {
        return new Response(JSON.stringify({ book: "big", actions: [
          { id: 7, idea_id: 50, idea_title: "NVDA call spread", kind: "option", state: "open",
            symbol: "NVDA  261204C00220000", created_at: "2026-11-03T12:30:00Z",
            detail: "one spread risks $2,500, over the budget -- size it by hand" },
        ] }), { status: 200 });
      }
      if (url.includes("/api/portfolio/manual-actions")) return new Response(JSON.stringify({ book: "main", actions: [] }), { status: 200 });
      if (url.includes("/resolve")) return new Response(JSON.stringify({ resolved: 7, state: "done" }), { status: 200 });
      if (url.includes("/api/portfolio/books")) return new Response(JSON.stringify({ books: [] }), { status: 200 });
      if (url.includes("/api/portfolio")) return new Response(JSON.stringify({ state: "live", book: "big", scoreboard: null }), { status: 200 });
      return new Response("{}", { status: 200 });
    }));
    render(<MemoryRouter initialEntries={["/portfolio?book=big"]}><Portfolio /></MemoryRouter>);
    expect(await screen.findByText("Needs your hand")).toBeInTheDocument();
    expect(screen.getByText(/over the budget/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByText(/over the budget/)).not.toBeInTheDocument());
    expect(calls.some((c) => c.includes("POST") && c.includes("/manual-actions/7/resolve"))).toBe(true);
  });
});
