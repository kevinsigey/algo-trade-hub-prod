import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import ClosedTrades from "@/pages/ClosedTrades";
import Portfolio from "@/pages/Portfolio";
import { concentration, curveRange } from "@/lib/paperPortfolio";
import type { ActivityPayload, BooksPayload, PortfolioPayload, PositionRow } from "@/lib/paperPortfolio";

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
    state: "live", as_of: "2026-11-10T20:41:00Z", scoreboard: EMPTY_SCORE,
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
    expect(await screen.findByText(/^Paper account · not the account on record/)).toBeInTheDocument();
    // The net liquidation figure and the rail's Cash row. The treemap's Cash tile may render later.
    expect(screen.getAllByText("$100,000").length).toBeGreaterThanOrEqual(2);
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
    expect(screen.queryByText("Strategy HQ")).toBeNull();
    expect(screen.getByText("Net liquidation value")).toBeInTheDocument();
    expect(screen.getByText("58%")).toBeInTheDocument();
    expect(screen.getByText("Paper account · live · as of 2:41 PM CT, Tue Nov 10")).toBeInTheDocument();
    // Manual shares read as their own row in the By-idea summary, one per symbol.
    expect(screen.getByText("GLD (manual)")).toBeInTheDocument();
    expect(screen.getByText("Positions · 1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /All orders and trades/ })).toHaveAttribute("href", "/portfolio/closed?book=main");
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
    expect(await screen.findByText("Positions · 0")).toBeInTheDocument();
    expect(screen.queryByText("Place an order by hand")).toBeNull();
  });

  it("shows the staged orders panel, signed in only", async () => {
    serveRoutes(true, []);
    page(<Portfolio />);
    expect(await screen.findByText(/^Staged orders/)).toBeInTheDocument();
    expect(await screen.findByText("XOM")).toBeInTheDocument();
    // The summary line carries the price and the time in force together.
    expect(screen.getByText(/\$175\.00 · gtc/)).toBeInTheDocument();
  });

  it("hides the staged orders panel from a signed-out visitor", async () => {
    serveRoutes(false, []);
    page(<Portfolio />);
    expect(await screen.findByText("Positions · 0")).toBeInTheDocument();
    expect(screen.queryByText(/^Staged orders/)).toBeNull();
  });

  it("places a market order through the endpoint when signed in", async () => {
    const posted: Record<string, unknown>[] = [];
    serveRoutes(true, posted);
    page(<Portfolio />);
    expect(await screen.findByText("Place an order by hand")).toBeInTheDocument();
    // The form opens from its panel, so the page stays one screen.
    fireEvent.click(screen.getByRole("button", { name: "Open Place an order by hand in full" }));
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "xle" } });
    fireEvent.change(screen.getByLabelText("Shares"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Place order" }));
    expect(await screen.findByText(/Order sent: buy 3 XLE \(manual-abc123\)/)).toBeInTheDocument();
    expect(posted).toEqual([{ symbol: "XLE", qty: 3, side: "buy", order_type: "market", time_in_force: "day", book: "main" }]);
  });

  it("places a single-leg option order with an intent and a day time-in-force", async () => {
    const posted: Record<string, unknown>[] = [];
    serveRoutes(true, posted);
    page(<Portfolio />);
    expect(await screen.findByText("Place an order by hand")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Place an order by hand in full" }));
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "SPY261113P00570000" } });
    // The form names the contract it parsed and counts contracts, not shares.
    expect(await screen.findByText("SPY Nov 13 2026 $570 put")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Contracts"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "limit" } });
    fireEvent.change(screen.getByLabelText("Limit price"), { target: { value: "2.40" } });
    fireEvent.click(screen.getByRole("button", { name: "Place order" }));
    expect(await screen.findByText(/Order sent: buy 2 SPY261113P00570000 \(manual-abc123\)/)).toBeInTheDocument();
    expect(posted).toEqual([{ symbol: "SPY261113P00570000", qty: 2, side: "buy", order_type: "limit",
      time_in_force: "day", position_intent: "buy_to_open", limit_price: 2.4, book: "main" }]);
  });

  it("places a combo as legs plus one net limit, with absolute quantities", async () => {
    const posted: Record<string, unknown>[] = [];
    serveRoutes(true, posted);
    page(<Portfolio />);
    expect(await screen.findByText("Place an order by hand")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Place an order by hand in full" }));
    fireEvent.click(screen.getByRole("button", { name: "Combo (spread)" }));
    fireEvent.change(screen.getByLabelText("Leg 1 symbol"), { target: { value: "SPY261113P00570000" } });
    fireEvent.change(screen.getByLabelText("Leg 1 qty"), { target: { value: "6" } });
    fireEvent.change(screen.getByLabelText("Leg 2 symbol"), { target: { value: "SPY261113P00565000" } });
    fireEvent.change(screen.getByLabelText("Leg 2 qty"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Net limit price"), { target: { value: "1.20" } });
    fireEvent.click(screen.getByRole("button", { name: "Place order" }));
    expect(await screen.findByText(/Order sent: combo of 2 legs \(manual-abc123\)/)).toBeInTheDocument();
    expect(posted).toEqual([{ legs: [
      { symbol: "SPY261113P00570000", side: "buy", qty: 6, position_intent: "buy_to_open" },
      { symbol: "SPY261113P00565000", side: "sell", qty: 3, position_intent: "sell_to_open" },
    ], order_type: "limit", limit_price: 1.2, time_in_force: "day", book: "main" }]);
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
    // The summary line carries the hold; the full table opens from the panel.
    expect(screen.getByText(/· 3d/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Closed trades · 1 in full" }));
    expect(within(screen.getByRole("dialog")).getByText("3d")).toBeInTheDocument();
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
        equity: 104820, return_pct: 4.82, positions: 3, live_ideas: 2 },
      { book: "big", label: "$1M book", detail: "$1M paper account", state: "not_connected", as_of: null,
        equity: null, return_pct: null, positions: 0, live_ideas: 0 },
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
          book: "big",
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

  it("opens on the main book, with each book's headline as a tab", async () => {
    const urls: string[] = [];
    serveBooks(urls);
    page(<Portfolio />);
    // The $1M tab says plainly that it is not connected -- no invented numbers.
    const bigCard = await screen.findByRole("link", { name: /\$1M book/ });
    expect(bigCard).toHaveAttribute("href", "/portfolio?book=big");
    expect(bigCard.textContent).toContain("not connected");
    const mainCard = screen.getByRole("link", { name: /Main book/ });
    expect(mainCard).toHaveAttribute("href", "/portfolio?book=main");
    expect(mainCard.textContent).toContain("$104,820");
    expect(mainCard).toHaveAttribute("aria-current", "page");
    expect(await screen.findByText("Positions · 0")).toBeInTheDocument();
  });

  it("scopes every read to the $1M book when ?book=big, with the switcher on top", async () => {
    const urls: string[] = [];
    serveBooks(urls);
    render(<MemoryRouter initialEntries={["/portfolio?book=big"]}><Portfolio /></MemoryRouter>);
    expect((await screen.findAllByText("$1,000,000")).length).toBeGreaterThanOrEqual(1);
    expect(urls.some((u) => u.includes("/api/portfolio?book=big"))).toBe(true);
    expect(urls.some((u) => u.includes("/api/portfolio/closed?book=big"))).toBe(true);
    expect(screen.getByRole("link", { name: /\$1M book/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /All orders and trades/ })).toHaveAttribute("href", "/portfolio/closed?book=big");
    // The hand order form and staged orders are main-book doors; they stay off this page.
    expect(screen.queryByText("Place an order by hand")).toBeNull();
    expect(screen.queryByText(/^Staged orders/)).toBeNull();
  });
});

describe("Portfolio positions", () => {
  const row = (symbol: string, value: number, over: Partial<PositionRow> = {}): PositionRow => ({
    symbol, qty: 10, side: "long", market_value: value, pct_of_book: 5, unrealized_pl: 10, idea: "Chips", ...over,
  });

  it("shows broker columns, nests an option under its stock and sorts on click", async () => {
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 100000 },
      positions: [
        row("NVDA261204C00200000", 900), row("MU", 3000, { last_price: 300, change_pct: 1.5, day_pl: 45 }), row("NVDA", 2000, { day_pl: -60 }),
      ],
    }));
    page(<Portfolio />);
    await screen.findByText("Positions · 3");
    // The panel shows the largest holdings; the full sortable table opens from it.
    fireEvent.click(screen.getByRole("button", { name: "Open Positions · 3 in full" }));
    const table = () => screen.getByRole("dialog", { name: "Positions · 3" });
    const names = () => within(table()).getAllByRole("row").slice(1, 4).map((r) => r.querySelector("td")!.textContent);
    expect(names()).toEqual(["MU", "NVDA", "NVDA Dec 4 2026 $200 call"]);
    expect(screen.getByText("$300.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Market value" }));
    expect(names()).toEqual(["NVDA", "NVDA Dec 4 2026 $200 call", "MU"]);
  });

  it("sorts Chg % and Day P&L by signed value, not magnitude", async () => {
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 100000 },
      positions: [
        row("AAA", 4000, { change_pct: 2, day_pl: 30 }),
        row("BBB", 3000, { change_pct: -8, day_pl: -90 }),
        row("CCC", 2000, { change_pct: 0, day_pl: 0 }),
        row("DDD", 1000, { change_pct: 5, day_pl: -10 }),
      ],
    }));
    page(<Portfolio />);
    await screen.findByText("Positions · 4");
    fireEvent.click(screen.getByRole("button", { name: "Open Positions · 4 in full" }));
    const table = () => screen.getByRole("dialog", { name: "Positions · 4" });
    const names = () => within(table()).getAllByRole("row").slice(1, 5).map((r) => r.querySelector("td")!.textContent);
    // Highest to lowest means +5, +2, 0, -8: gainers on top, losers at the bottom.
    fireEvent.click(screen.getByRole("button", { name: "Chg %" }));
    expect(names()).toEqual(["DDD", "AAA", "CCC", "BBB"]);
    fireEvent.click(screen.getByRole("button", { name: "Chg %" }));
    expect(names()).toEqual(["BBB", "CCC", "AAA", "DDD"]);
    fireEvent.click(screen.getByRole("button", { name: "Day P&L" }));
    expect(names()).toEqual(["AAA", "CCC", "DDD", "BBB"]);
  });
});

describe("Portfolio circuit breaker", () => {
  const state = (over: object) => ({
    enabled: true, tripped: false, reasons: [], daily_limit_pct: 2, drawdown_limit_pct: null,
    daily_loss_pct: 0.5, drawdown_pct: 1, high_water: 100000, ...over,
  });

  it("reads off, on and tripped", async () => {
    serve(payload({ scoreboard: { ...EMPTY_SCORE, equity: 100000 }, breaker: state({ enabled: false }) }));
    const { unmount } = page(<Portfolio />);
    expect(await screen.findByText("Off")).toBeInTheDocument();
    unmount();
    serve(payload({ scoreboard: { ...EMPTY_SCORE, equity: 100000 }, breaker: state({}) }));
    const second = page(<Portfolio />);
    expect(await screen.findByText("On, 0.5% of 2% daily")).toBeInTheDocument();
    second.unmount();
    serve(payload({ scoreboard: { ...EMPTY_SCORE, equity: 100000 },
                    breaker: state({ tripped: true, reasons: ["daily loss 3%"] }) }));
    page(<Portfolio />);
    expect(await screen.findByText(/Circuit breaker tripped: daily loss 3%/)).toBeInTheDocument();
  });
});

describe("Portfolio helpers", () => {
  it("rebases the chosen range to start at zero", () => {
    const curve = [
      { t: "2026-01-01T00:00:00Z", portfolio_pct: 0, spy_pct: 0 },
      { t: "2026-10-30T00:00:00Z", portfolio_pct: 10, spy_pct: 5 },
      { t: "2026-11-02T00:00:00Z", portfolio_pct: 21, spy_pct: 5 },
    ];
    const week = curveRange(curve, "1W", new Date("2026-11-03T00:00:00Z"));
    expect(week.length).toBe(2);
    expect(week[0].portfolio_pct).toBeCloseTo(0);
    expect(week[1].portfolio_pct).toBeCloseTo(10);
    expect(curveRange(curve, "All")).toBe(curve);
  });

  it("flags a sector over 40% of what's invested, but not the broad market", () => {
    const rows = [
      { symbol: "MU", sector: "Technology", market_value: 500, idea: "A" },
      { symbol: "TSM", sector: "Technology", market_value: 300, idea: "B" },
      { symbol: "SPY", sector: "Broad Market", market_value: 1500, idea: "C" },
    ] as PositionRow[];
    expect(concentration(rows)).toEqual([]);
    const heavy = concentration(rows.slice(0, 2));
    expect(heavy[0].sector).toBe("Technology");
    expect(heavy[0].pct).toBe(100);
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

describe("Portfolio check card", () => {
  const CARD = {
    book: "main", as_of: "2026-11-09T19:00:00Z", equity: 1050000, cash: 150000,
    cash_pct: 14.29, invested: 900000,
    sleeves: [
      { id: "t4_ballast", label: "T4 ballast (W18 core)", weight_pct: 51.89, sleeve_max_pct: null,
        exit_only: false, status: "ok", correlation_to_book: 0.42,
        members: [
          { symbol: "GLD", weight_pct: 13.0, target_pct: 11, max_pct: 12, min_pct: 2, status: "over" },
          { symbol: "XLP", weight_pct: 5.56, target_pct: null, max_pct: 8, min_pct: 2, status: "ok" },
        ] },
      { id: "t8_ai", label: "T8 AI winners core", weight_pct: 6.0, sleeve_max_pct: 10,
        exit_only: false, status: "ok", correlation_to_book: 0.83,
        members: [{ symbol: "NVDA", weight_pct: 1.0, target_pct: 1.67, max_pct: null, min_pct: null, status: "ok" }] },
      { id: "ibit", label: "IBIT BTC sleeve", weight_pct: 3.78, sleeve_max_pct: null,
        exit_only: true, status: "ok", correlation_to_book: null,
        members: [{ symbol: "IBIT", weight_pct: 3.78, target_pct: null, max_pct: null, min_pct: null, status: "ok" }] },
    ],
    unassigned: [],
    clusters: {
      rates: { label: "Rates factor", pct: 16.67, with_flagged_pct: 29.67 },
      ai_complex: { label: "AI complex", pct: 7.89 },
      gold: { label: "Gold", pct: 13.0 },
    },
    recent_checks: [
      { at: "2026-11-09T18:00:00Z", source: "machine_preflight", symbol: "GLD", outcome: "block",
        detail: "GLD would be 13.5% of invested after this order, over GLD's cap of 12%" },
      { at: "2026-11-09T17:00:00Z", source: "machine_preflight", symbol: "XLP", outcome: "pass",
        detail: "portfolio check passes" },
    ],
    targets_updated_at: "2026-11-09T12:00:00Z", series_refreshed_at: null, unpriced: [],
  };

  it("renders sleeve weights against caps, clusters, cash and recent outcomes", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/portfolio/portfolio-check")) return new Response(JSON.stringify(CARD), { status: 200 });
      if (url.includes("/api/portfolio/manual-actions")) return new Response(JSON.stringify({ book: "main", actions: [] }), { status: 200 });
      if (url.includes("/api/portfolio/books")) return new Response(JSON.stringify({ books: [] }), { status: 200 });
      if (url.includes("/api/portfolio")) {
        return new Response(JSON.stringify(payload({
          state: "live",
          positions: [{ symbol: "GLD", qty: 310, side: "long", market_value: 117000, pct_of_book: 13, unrealized_pl: 0, idea: null }],
        })), { status: 200 });
      }
      return new Response("{}", { status: 200 });
    }));
    page(<Portfolio />);
    expect(await screen.findByText("Portfolio check")).toBeInTheDocument();
    const card = within(screen.getByText("Portfolio check").closest("section") as HTMLElement);
    // Resting state is bars, not rows: GLD (over its cap) and XLP (capped) earn
    // bars with floor / target / cap ticks; NVDA (ok, uncapped) does not.
    expect(card.getByText("GLD")).toBeInTheDocument();
    // GLD's bar value and the gold chip carry the same 13.0% (same position).
    expect(card.getAllByText("13.0%")).toHaveLength(2);
    expect(card.getAllByTitle("floor 2%")).toHaveLength(2);
    expect(card.getByTitle("target 11%")).toBeInTheDocument();
    expect(card.getByTitle("cap 12%")).toBeInTheDocument();
    expect(card.getByTitle("cap 8%")).toBeInTheDocument();
    expect(card.queryByText("NVDA")).not.toBeInTheDocument();
    // Sleeve bars, the cash bar, the exit-only note and the cluster chips.
    expect(card.getByText("T4 ballast (W18 core)")).toBeInTheDocument();
    expect(card.getByText(/exit-only/)).toBeInTheDocument();
    expect(card.getByText("Cash")).toBeInTheDocument();
    expect(card.getByText("14.3%")).toBeInTheDocument();
    expect(card.getByText("Rates factor")).toBeInTheDocument();
    expect(card.getByText("16.7%")).toBeInTheDocument();
    expect(card.getByText(/29.7% incl. GLD/)).toBeInTheDocument();
    // The latest outcome rides in the header; the detail (every recent outcome,
    // the member table, the correlation readout) sits behind the open view.
    expect(card.getByText("block")).toBeInTheDocument();
    expect(card.queryByText(/over GLD's cap of 12%/)).not.toBeInTheDocument();
    expect(card.queryByText(/0\.83/)).not.toBeInTheDocument();
    fireEvent.click(card.getByRole("button", { name: "Open Portfolio check in full" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByText(/over GLD's cap of 12%/)).toBeInTheDocument();
    expect(dialog.getByText("0.83")).toBeInTheDocument();
    expect(dialog.getByText("portfolio check passes")).toBeInTheDocument();
  });
});
