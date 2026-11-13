import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import ClosedTrades from "@/pages/ClosedTrades";
import Portfolio from "@/pages/Portfolio";
import { concentration, curveRange } from "@/lib/paperPortfolio";
import { checkChips } from "@/pages/portfolio/Header";
import type { ActivityPayload, BooksPayload, PortfolioPayload, PositionRow } from "@/lib/paperPortfolio";

// Portfolio's admin reads go through the signed fetch, which loads the
// Supabase client: stub it. No session by default (a visitor); a test that
// plays Kevin sets a token first. Without a session no admin call is sent.
const session = vi.hoisted(() => ({ token: null as string | null }));
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: session.token ? { access_token: session.token } : null } }),
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

const pageAt = (url: string) => render(<MemoryRouter initialEntries={[url]}><Portfolio /></MemoryRouter>);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  session.token = null;
});

/** Open a dashboard card and return its open view. */
function openCard(name: string | RegExp) {
  fireEvent.click(screen.getByRole("button", { name: typeof name === "string" ? `Open ${name}` : name }));
  return within(screen.getByRole("dialog"));
}

const region = (name: string) => within(screen.getByRole("region", { name }));

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
    expect(screen.getByText("Paper account · live · as of 2:41 PM CT, Tue Nov 10")).toBeInTheDocument();
    // Manual shares read as their own row in the By-idea summary, one per symbol.
    expect(screen.getByText("GLD (manual)")).toBeInTheDocument();
    expect(region("Positions").getByText("1")).toBeInTheDocument();
  });
});

describe("Portfolio hand orders (signed-in only)", () => {
  function serveRoutes(adminOk: boolean, posted: Record<string, unknown>[]) {
    if (adminOk) session.token = "jwt";
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
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText("Recent orders")).toBeInTheDocument();
    expect(screen.queryByText("Place an order by hand")).toBeNull();
  });

  it("shows the staged orders panel, signed in only", async () => {
    serveRoutes(true, []);
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText("Staged orders")).toBeInTheDocument();
    expect(await screen.findByText("XOM")).toBeInTheDocument();
    // The card shows the count and the top rows; the open view's full
    // table carries the price and the time in force as their own cells.
    expect(region("Staged orders").getByText("1")).toBeInTheDocument();
    const full = openCard("Staged orders");
    expect(full.getByText("$175.00")).toBeInTheDocument();
    expect(full.getByText("gtc")).toBeInTheDocument();
  });

  it("hides the staged orders panel from a signed-out visitor", async () => {
    serveRoutes(false, []);
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText("Recent orders")).toBeInTheDocument();
    expect(screen.queryByText("Staged orders")).toBeNull();
  });

  it("lists closed trades in full on the Trade tab", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/portfolio/closed")) {
        return new Response(JSON.stringify({
          state: "live", as_of: "2026-11-12T20:00:00Z", book: "main",
          trades: [{ symbol: "NVDA", sector: "Technology", qty: 10, entry_price: 100, exit_price: 110,
                     entered_at: "2026-11-02T15:00:00Z", exited_at: "2026-11-10T20:00:00Z",
                     pnl: 100, return_pct: 10, held_days: 8, idea: "Idea One" }],
          results_split: null,
        }), { status: 200 });
      }
      if (url.includes("/api/admin/me")) return new Response(JSON.stringify({ detail: "admin only" }), { status: 401 });
      return new Response(JSON.stringify(payload({})), { status: 200 });
    }));
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText("NVDA")).toBeInTheDocument();
    expect(region("Closed trades").getByText("1")).toBeInTheDocument();
    // The idea column lives in the open view's full table.
    expect(screen.queryByText("Idea One")).toBeNull();
    expect(openCard("Closed trades").getByText("Idea One")).toBeInTheDocument();
  });

  it("sorts the Trade tab's closed trades by P&L when the header is clicked", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/portfolio/closed")) {
        return new Response(JSON.stringify({
          state: "live", as_of: "2026-11-12T20:00:00Z", book: "main",
          trades: [
            { symbol: "NVDA", sector: "Technology", qty: 10, entry_price: 100, exit_price: 110,
              entered_at: "2026-11-02T15:00:00Z", exited_at: "2026-11-10T20:00:00Z",
              pnl: 100, return_pct: 10, held_days: 8, idea: "Idea One" },
            { symbol: "AAPL", sector: "Technology", qty: 5, entry_price: 200, exit_price: 190,
              entered_at: "2026-11-03T15:00:00Z", exited_at: "2026-11-11T20:00:00Z",
              pnl: -50, return_pct: -5, held_days: 8, idea: "Idea Two" },
          ],
          results_split: null,
        }), { status: 200 });
      }
      if (url.includes("/api/admin/me")) return new Response(JSON.stringify({ detail: "admin only" }), { status: 401 });
      return new Response(JSON.stringify(payload({})), { status: 200 });
    }));
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    openCard("Closed trades");
    const symbolsInOrder = () => [...screen.getByRole("dialog").querySelectorAll("tbody tr")]
      .map((tr) => tr.textContent ?? "").filter((t) => t.includes("NVDA") || t.includes("AAPL"))
      .map((t) => (t.includes("NVDA") ? "NVDA" : "AAPL"));
    // Default: newest exit first (AAPL, Nov 11).
    expect(symbolsInOrder()).toEqual(["AAPL", "NVDA"]);
    // First P&L click sorts descending (NVDA +100 first), second ascending.
    fireEvent.click(screen.getByRole("button", { name: /^P&L/ }));
    expect(symbolsInOrder()).toEqual(["NVDA", "AAPL"]);
    fireEvent.click(screen.getByRole("button", { name: /^P&L/ }));
    expect(symbolsInOrder()).toEqual(["AAPL", "NVDA"]);
  });

  it("shows closed trades as unreadable, not empty, when the read fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/portfolio/closed")) {
        return new Response(JSON.stringify({ detail: "boom" }), { status: 500 });
      }
      if (url.includes("/api/admin/me")) return new Response(JSON.stringify({ detail: "admin only" }), { status: 401 });
      return new Response(JSON.stringify(payload({})), { status: 200 });
    }));
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText(/Couldn't read closed trades/)).toBeInTheDocument();
    expect(screen.queryByText("No closed trades yet.")).toBeNull();
    // The count reads as unknown, never 0.
    expect(region("Closed trades").queryByText("0")).toBeNull();
    expect(region("Closed trades").getByText("—")).toBeInTheDocument();
  });

  it("retries a transient admin-check failure and then loads the hand-off queue", async () => {
    session.token = "jwt";
    const urls: string[] = [];
    const startedAt = Date.now();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url.includes("/api/admin/me")) {
        // Every component's first check fails (500); checks after the
        // first second succeed, so only a retrying component gets in.
        return Date.now() - startedAt < 1000
          ? new Response(JSON.stringify({ detail: "boom" }), { status: 500 })
          : new Response(JSON.stringify({ email: "k@example.com" }), { status: 200 });
      }
      if (url.includes("/api/portfolio/manual-actions")) {
        return new Response(JSON.stringify({ book: "main", actions: [] }), { status: 200 });
      }
      if (url.includes("/api/workshop/ideas")) return new Response(JSON.stringify([]), { status: 200 });
      return new Response(JSON.stringify(payload({})), { status: 200 });
    }));
    pageAt("/portfolio?tab=trade");
    // The failed check shows as a failed read, not a silent dark queue.
    expect(await screen.findByText(/Couldn't read the hand-off list/, {}, { timeout: 5000 })).toBeInTheDocument();
    // The retry succeeds, the queue loads, and the failure box clears.
    await waitFor(() => expect(urls.some((u) => u.includes("/api/portfolio/manual-actions"))).toBe(true), { timeout: 5000 });
    await waitFor(() => expect(screen.queryByText(/Couldn't read the hand-off list/)).toBeNull(), { timeout: 5000 });
  });

  it("keeps the hand-off failure visible while the admin check keeps failing", async () => {
    session.token = "jwt";
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url.includes("/api/admin/me")) return new Response(JSON.stringify({ detail: "boom" }), { status: 500 });
      return new Response(JSON.stringify(payload({})), { status: 200 });
    }));
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText(/Couldn't read the hand-off list/, {}, { timeout: 5000 })).toBeInTheDocument();
    // Past the two quick retries, the queue endpoint is still untouched
    // and the failure is still on screen.
    await new Promise((r) => setTimeout(r, 2500));
    expect(urls.some((u) => u.includes("/api/portfolio/manual-actions"))).toBe(false);
    expect(screen.getByText(/Couldn't read the hand-off list/)).toBeInTheDocument();
  });

  it("never polls the manual-actions endpoint for a signed-out visitor", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url.includes("/api/admin/me")) return new Response(JSON.stringify({ detail: "admin only" }), { status: 401 });
      return new Response(JSON.stringify(payload({})), { status: 200 });
    }));
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText("Recent orders")).toBeInTheDocument();
    expect(urls.some((u) => u.includes("/api/portfolio/manual-actions"))).toBe(false);
  });

  it("places a market order through the endpoint when signed in", async () => {
    const posted: Record<string, unknown>[] = [];
    serveRoutes(true, posted);
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText("Place an order by hand")).toBeInTheDocument();
    // The ticket is open on the Trade tab -- no pop-up to open first.
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "xle" } });
    fireEvent.change(screen.getByLabelText("Shares"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Place order" }));
    expect(await screen.findByText(/Order sent: buy 3 XLE \(manual-abc123\)/)).toBeInTheDocument();
    expect(posted).toEqual([{ symbol: "XLE", qty: 3, side: "buy", order_type: "market", time_in_force: "day", book: "main" }]);
  });

  it("places a single-leg option order with an intent and a day time-in-force", async () => {
    const posted: Record<string, unknown>[] = [];
    serveRoutes(true, posted);
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText("Place an order by hand")).toBeInTheDocument();
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
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText("Place an order by hand")).toBeInTheDocument();
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
    expect(await screen.findByRole("region", { name: "Positions" })).toBeInTheDocument();
    expect(region("Positions").getByText("0")).toBeInTheDocument();
  });

  it("scopes every read to the $1M book when ?book=big, with the switcher on top", async () => {
    const urls: string[] = [];
    serveBooks(urls);
    render(<MemoryRouter initialEntries={["/portfolio?book=big"]}><Portfolio /></MemoryRouter>);
    expect((await screen.findAllByText("$1,000,000")).length).toBeGreaterThanOrEqual(1);
    expect(urls.some((u) => u.includes("/api/portfolio?book=big"))).toBe(true);
    expect(urls.some((u) => u.includes("/api/portfolio/closed?book=big"))).toBe(true);
    expect(screen.getByRole("link", { name: /\$1M book/ })).toHaveAttribute("aria-current", "page");
    // Signed out, the hand order form and staged orders stay off the page --
    // asserted on the Trade tab too, where they would render if their own
    // access checks failed.
    expect(screen.queryByText("Place an order by hand")).toBeNull();
    expect(screen.queryByText("Staged orders")).toBeNull();
    cleanup();
    render(<MemoryRouter initialEntries={["/portfolio?book=big&tab=trade"]}><Portfolio /></MemoryRouter>);
    expect(await screen.findByText("Recent orders")).toBeInTheDocument();
    expect(screen.queryByText("Place an order by hand")).toBeNull();
    expect(screen.queryByText("Staged orders")).toBeNull();
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
    await screen.findByRole("region", { name: "Positions" });
    // The card peeks; the full sortable table is in its open view.
    openCard("Positions");
    const table = () => within(screen.getByRole("dialog"));
    const names = () => table().getAllByRole("row").slice(1, 4).map((r) => r.querySelector("td")!.textContent);
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
    await screen.findByRole("region", { name: "Positions" });
    openCard("Positions");
    const table = () => within(screen.getByRole("dialog"));
    const names = () => table().getAllByRole("row").slice(1, 5).map((r) => r.querySelector("td")!.textContent);
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

describe("Portfolio redesign (header, warnings strip, tabs)", () => {
  it("splits today at the 4 PM close in the header, with SPY beside it", async () => {
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 98839, return_pct: -3.5, spy_return_pct: -0.4, ahead_pts: -3.1 },
      today: {
        state: "after_hours", prior_close_at: "2026-11-10T21:30:00Z", close_at: "2026-11-11T21:05:00Z",
        regular_pl: -1161, regular_pct: -1.16, after_hours_pl: -84, after_hours_pct: -0.08,
        spy_regular_pct: -0.02, spy_after_hours_pct: 0.11,
      },
      positions: [{ symbol: "Cash", qty: null, side: null, market_value: 98839, pct_of_book: 100, unrealized_pl: null, idea: null }],
    }));
    page(<Portfolio />);
    expect(await screen.findByText(/Today −\$1,161/)).toBeInTheDocument();
    expect(screen.getByText(/After hours −\$84 since 4:00 PM/)).toBeInTheDocument();
    expect(screen.getByText("After hours", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText(/SPY \+0\.1%/)).toBeInTheDocument();
  });

  it("shows QQQ beside SPY in the header when the payload carries it", async () => {
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 98839, return_pct: -3.5, spy_return_pct: -0.4, ahead_pts: -3.1,
                    qqq_return_pct: 5.0, ahead_qqq_pts: -8.5 },
      today: {
        state: "regular", prior_close_at: "2026-11-10T21:30:00Z", close_at: null,
        regular_pl: -1161, regular_pct: -1.16, after_hours_pl: null, after_hours_pct: null,
        spy_regular_pct: -0.02, spy_after_hours_pct: null,
        qqq_regular_pct: -0.5, qqq_after_hours_pct: null,
      },
      positions: [{ symbol: "Cash", qty: null, side: null, market_value: 98839, pct_of_book: 100, unrealized_pl: null, idea: null }],
    }));
    page(<Portfolio />);
    expect(await screen.findByText(/QQQ −0\.5%/)).toBeInTheDocument();
    expect(screen.getByText(/QQQ \+5\.0%/)).toBeInTheDocument();
    expect(screen.getByText("−8.5 pts")).toBeInTheDocument();
  });

  it("labels a closed day with its own day, not Today, and no after-hours tag", async () => {
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 100200, return_pct: 0.2, spy_return_pct: 0.1, ahead_pts: 0.1 },
      today: {
        state: "closed_day", prior_close_at: "2026-11-12T21:30:00Z", close_at: "2026-11-13T21:05:00Z",
        regular_pl: 200, regular_pct: 0.2, after_hours_pl: null, after_hours_pct: null,
        spy_regular_pct: 1.0, spy_after_hours_pct: null,
        for_date: "2026-11-13", day_label: "Fri", is_today: false,
      },
      positions: [{ symbol: "Cash", qty: null, side: null, market_value: 100200, pct_of_book: 100, unrealized_pl: null, idea: null }],
    }));
    page(<Portfolio />);
    expect(await screen.findByText(/Fri \+\$200/)).toBeInTheDocument();
    expect(screen.queryByText("After hours", { selector: "span" })).toBeNull();
  });

  it("keeps idea information out of the Positions table -- it lives in By idea", async () => {
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 100000 },
      positions: [
        { symbol: "MU", qty: 10, side: "long", market_value: 3000, pct_of_book: 3, unrealized_pl: 10, idea: "Chips" },
        { symbol: "Cash", qty: null, side: null, market_value: 97000, pct_of_book: 97, unrealized_pl: null, idea: null },
      ],
    }));
    page(<Portfolio />);
    const positions = within(await screen.findByRole("region", { name: "Positions" }));
    expect(positions.getByText("MU")).toBeInTheDocument();
    expect(positions.queryByText("Chips")).toBeNull();
    expect(screen.getByText("Chips")).toBeInTheDocument(); // the By-idea row carries it
  });

  it("expands a manual holding's slices under its per-symbol card key", async () => {
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 100000 },
      positions: [
        { symbol: "GLD", qty: 10, side: "long", avg_price: 300, last_price: 300, change_pct: 0, day_pl: 0, cost_basis: 3000, market_value: 3000, pct_of_book: 3, unrealized_pl: 0, idea: "No idea yet (manual)" },
        { symbol: "Cash", qty: null, side: null, market_value: 97000, pct_of_book: 97, unrealized_pl: null, idea: null },
      ],
    }));
    page(<Portfolio />);
    expect(await screen.findByText("GLD (manual)")).toBeInTheDocument();
    openCard("By idea");
    fireEvent.click(screen.getByRole("button", { name: "Slices of GLD (manual)" }));
    // The card is keyed "GLD (manual)" while the row carries the backend's
    // manual label; the slice lookup must still find the holding.
    expect(screen.queryByText("Nothing held under this idea right now.")).toBeNull();
    expect(screen.getByText(/10 sh/)).toBeInTheDocument();
  });

  it("reads 'All within limits' on the warnings strip when nothing needs attention", async () => {
    session.token = "jwt";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/portfolio/portfolio-check")) {
        return new Response(JSON.stringify({
          book: "main", as_of: "2026-11-09T19:00:00Z", equity: 100000, cash: 100000, cash_pct: 100, invested: 0,
          sleeves: [], unassigned: [], clusters: {},
          recent_checks: [{ at: "2026-11-09T18:00:00Z", source: "manual", symbol: null, outcome: "pass", detail: "portfolio check passes" }],
          targets_updated_at: null, series_refreshed_at: null, unpriced: [],
        }), { status: 200 });
      }
      return new Response(JSON.stringify(payload({
        scoreboard: { ...EMPTY_SCORE, equity: 100000 },
        positions: [{ symbol: "Cash", qty: null, side: null, market_value: 100000, pct_of_book: 100, unrealized_pl: null, idea: null }],
      })), { status: 200 });
    }));
    page(<Portfolio />);
    expect(await screen.findByText(/All within limits/)).toBeInTheDocument();
    expect(screen.getByText("pass")).toBeInTheDocument();
  });
});

describe("checkChips unresolved inputs", () => {
  const base = {
    book: "main", as_of: "2026-11-09T19:00:00Z", equity: 100000, cash: 0, cash_pct: 0, invested: 100000,
    sleeves: [], clusters: {}, recent_checks: [], targets_updated_at: null, series_refreshed_at: null,
  };
  it("chips an unassigned holding over the 5% cap instead of reading all-clear", () => {
    const chips = checkChips({ ...base, unassigned: [{ symbol: "XYZ", weight_pct: 7.5 }], unpriced: [] });
    expect(chips).toEqual(["XYZ unassigned 7.5% / 5%"]);
  });
  it("chips unpriced holdings -- the check never priced them", () => {
    const chips = checkChips({ ...base, unassigned: [], unpriced: ["ABC"] });
    expect(chips).toEqual(["ABC unpriced — not checked"]);
  });
  it("stays quiet when everything resolved within limits", () => {
    expect(checkChips({ ...base, unassigned: [{ symbol: "XYZ", weight_pct: 3 }], unpriced: [] })).toEqual([]);
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
    session.token = "jwt";
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
      if (url.includes("/api/portfolio")) return new Response(JSON.stringify(payload({ book: "big" })), { status: 200 });
      return new Response("{}", { status: 200 });
    }));
    // Manual actions live at the top of the Trade tab now.
    render(<MemoryRouter initialEntries={["/portfolio?book=big&tab=trade"]}><Portfolio /></MemoryRouter>);
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
    session.token = "jwt";
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
    // The card is a warnings strip now: resting state is the over-cap chip,
    // and the detail stays shut until the strip is opened.
    expect(await screen.findByText("GLD over cap 13.0% / 12%")).toBeInTheDocument();
    const strip = within(screen.getByRole("region", { name: "Warnings" }));
    expect(strip.queryByText(/over GLD's cap of 12%/)).not.toBeInTheDocument();
    expect(strip.queryByText(/0\.83/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Portfolio check").closest("button") as HTMLElement);
    // Inside the drawer: GLD (over its cap) and XLP (capped) earn bars with
    // floor / target / cap ticks; NVDA (ok, uncapped) earns no bar, though
    // it does sit in the member table. GLD reads twice: its bar and its
    // member-table row.
    expect(strip.getAllByText("GLD")).toHaveLength(2);
    // GLD's bar value and the gold chip carry the same 13.0% (same position).
    expect(strip.getAllByText("13.0%")).toHaveLength(2);
    expect(strip.getAllByTitle("floor 2%")).toHaveLength(2);
    expect(strip.getByTitle("target 11%")).toBeInTheDocument();
    expect(strip.getByTitle("cap 12%")).toBeInTheDocument();
    expect(strip.getByTitle("cap 8%")).toBeInTheDocument();
    // Sleeve bars, the cash bar, the exit-only note and the cluster chips.
    // (Sleeve labels read twice in the drawer: the bar and the member table.)
    expect(strip.getAllByText("T4 ballast (W18 core)")).toHaveLength(2);
    expect(strip.getAllByText(/exit-only/)).toHaveLength(2);
    expect(strip.getByText("Cash")).toBeInTheDocument();
    expect(strip.getByText("14.3%")).toBeInTheDocument();
    expect(strip.getByText("Rates factor")).toBeInTheDocument();
    expect(strip.getByText("16.7%")).toBeInTheDocument();
    expect(strip.getByText(/29.7% incl. GLD/)).toBeInTheDocument();
    // Every recent outcome, the member table and the correlation readout.
    expect(strip.getByText(/over GLD's cap of 12%/)).toBeInTheDocument();
    expect(strip.getByText("0.83")).toBeInTheDocument();
    expect(strip.getByText("portfolio check passes")).toBeInTheDocument();
  });
});

describe("Portfolio per-ticker aggregate (2026-11-12 review bugs)", () => {
  const slice = (symbol: string, idea: string, over: Partial<PositionRow> = {}): PositionRow => ({
    symbol, qty: 26, side: "long", market_value: 9500, pct_of_book: 9.5, unrealized_pl: 250,
    idea, sector: "Commodities (Gold)", last_price: 365.4, change_pct: -0.84, day_pl: -44,
    avg_price: 355, cost_basis: 9230, ...over,
  });

  it("counts, lists and moves by ticker, not by idea slice", async () => {
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 100000 },
      positions: [
        slice("GLD", "Gold"), slice("GLD", "Rates hedge"),
        slice("SPY", "Core", { sector: "Broad Market", day_pl: 120 }),
        { symbol: "Cash", qty: null, side: null, market_value: 62000, pct_of_book: 62, unrealized_pl: null, idea: null },
      ],
      positions_aggregate: [
        { symbol: "GLD", asset: "stock", qty: 52, market_value: 19000, pct_of_equity: 19, pct_of_book: 19,
          avg_entry: 355, tags: [], sector: "Commodities (Gold)", side: "long", last_price: 365.4,
          change_pct: -0.84, day_pl: -88, cost_basis: 18460, unrealized_pl: 500 },
        { symbol: "SPY", asset: "stock", qty: 10, market_value: 7500, pct_of_equity: 7.5, pct_of_book: 7.5,
          avg_entry: 740, tags: [], sector: "Broad Market", side: "long", last_price: 750,
          change_pct: 0.4, day_pl: 120, cost_basis: 7400, unrealized_pl: 100 },
      ],
    }));
    page(<Portfolio />);
    // 3 slices, 2 tickers: the Positions card counts tickers.
    await screen.findByRole("region", { name: "Positions" });
    expect(region("Positions").getByText("2")).toBeInTheDocument();
    // GLD appears once as a mover (its two lots' day P&L summed) and once in
    // the positions summary -- not once per idea that holds it.
    expect(screen.getAllByText("GLD")).toHaveLength(2);
    // The summed -$88 (two lots at -$44) is what both the mover and the
    // positions row carry. (The per-slice -$44 still shows inside the
    // By-idea cards, where per-idea attribution is the point.)
    expect(region("Today's movers").getByText("−$88")).toBeInTheDocument();
    expect(openCard("Positions").getByText("−$88")).toBeInTheDocument();
  });

  it("holds the Sharpe back until 20 trading days, however many snapshots", async () => {
    const curve = Array.from({ length: 65 }, (_, i) => {
      const day = `2026-11-${String(2 + Math.floor(i / 9)).padStart(2, "0")}`;
      return { t: `${day}T${String(14 + (i % 9)).padStart(2, "0")}:30:00Z`, portfolio_pct: 0.1 * i, spy_pct: 0.05 * i };
    });
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 100000, sharpe: -10.01, win_rate: 58 }, curve,
      positions: [{ symbol: "Cash", qty: null, side: null, market_value: 100000, pct_of_book: 100, unrealized_pl: null, idea: null }],
    }));
    pageAt("/portfolio?tab=performance");
    // Both day-count guards hold at 8 trading days: Sharpe and beta to SPY.
    expect(await screen.findAllByText("after 1 mo")).toHaveLength(2);
    expect(screen.queryByText("-10.01")).toBeNull();
    expect(screen.getByText("58%")).toBeInTheDocument();
  });

  it("keys position rows by symbol and idea, so duplicate tickers warn about nothing", async () => {
    const errors: unknown[][] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => { errors.push(args); });
    try {
      // No aggregate on this payload: the fallback slice path feeds the
      // tables, and the same ticker appears once per holding idea. (The
      // two slices move opposite ways so Today's movers lists each in a
      // different list — this test is about the positions rows' keys.)
      serve(payload({
        scoreboard: { ...EMPTY_SCORE, equity: 100000 },
        positions: [
          slice("GLD", "Gold"), slice("GLD", "Rates hedge", { day_pl: 44 }),
          { symbol: "Cash", qty: null, side: null, market_value: 81000, pct_of_book: 81, unrealized_pl: null, idea: null },
        ],
      }));
      page(<Portfolio />);
      await screen.findByRole("region", { name: "Positions" });
      expect(region("Positions").getByText("2")).toBeInTheDocument();
      expect(region("Positions").getAllByText("GLD")).toHaveLength(2);
      expect(openCard("Positions").getAllByText("GLD")).toHaveLength(2);
      const keyWarnings = errors.filter((a) => String(a[0]).includes("same key"));
      expect(keyWarnings).toEqual([]);
    } finally {
      spy.mockRestore();
    }
  });

  it("names each leg's side and quantity in the full orders table", async () => {
    const activity = {
      state: "live", as_of: "2026-11-11T20:00:00Z", book: "main", open: [],
      recent: [{
        symbol: "", side: "buy", qty: 1, filled_qty: 1, type: "limit", time_in_force: "day",
        status: "filled", limit_price: 0.31, stop_price: null, filled_avg_price: 0.31,
        submitted_at: "2026-11-11T15:00:00Z", filled_at: "2026-11-11T15:01:00Z",
        asset: "option", source: "Machine order",
        legs: [
          { symbol: "SPY261111P00750000", side: "buy_to_open", ratio_qty: 1, qty: 1, filled_qty: 1 },
          { symbol: "SPY261111P00749000", side: "sell_to_open", ratio_qty: 1, qty: 1, filled_qty: 1 },
        ],
      }],
      trades: [],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/portfolio/activity")) return new Response(JSON.stringify(activity), { status: 200 });
      return new Response(JSON.stringify(payload({
        scoreboard: { ...EMPTY_SCORE, equity: 100000 },
        positions: [{ symbol: "Cash", qty: null, side: null, market_value: 100000, pct_of_book: 100, unrealized_pl: null, idea: null }],
      })), { status: 200 });
    }));
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText("Recent orders")).toBeInTheDocument();
    // The full orders table is the tab's own content now -- no pop-up.
    expect(await screen.findByText(/buy 1 SPY Nov 11 2026 \$750 put \/ sell 1 SPY Nov 11 2026 \$749 put/)).toBeInTheDocument();
  });

  it("counts every rendered row in the By-idea header, manual ones included", async () => {
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 100000 },
      positions: [
        slice("GLD", "No idea yet (manual)"), slice("SPY", "No idea yet (manual)"),
        { symbol: "Cash", qty: null, side: null, market_value: 81000, pct_of_book: 81, unrealized_pl: null, idea: null },
      ],
    }));
    page(<Portfolio />);
    await screen.findByRole("region", { name: "By idea" });
    expect(region("By idea").getByText("2")).toBeInTheDocument();
    expect(openCard("By idea").getAllByRole("button", { name: /^Slices of/ })).toHaveLength(2);
  });
});

describe("Portfolio performance tab deepening (2026-11-12 redesign PR 2)", () => {
  const closedTrade = (over: Record<string, unknown>) => ({
    symbol: "NVDA", sector: "Technology", qty: 10, entry_price: 100, exit_price: 110,
    entered_at: "2026-11-08T15:00:00Z", exited_at: "2026-11-10T20:00:00Z",
    pnl: 100, return_pct: 10, held_days: 2, idea: "Idea One", ...over,
  });

  function servePerf() {
    const main = payload({
      scoreboard: { ...EMPTY_SCORE, equity: 100000, max_drawdown_pct: -1, win_rate: 50 },
      curve: [
        { t: "2026-11-09T20:00:00Z", portfolio_pct: 1, spy_pct: 0.5 },
        { t: "2026-11-10T20:00:00Z", portfolio_pct: 0, spy_pct: 0 },
        { t: "2026-11-11T20:00:00Z", portfolio_pct: 2.02, spy_pct: 1 },
      ],
      composition: [{ idea: "Idea One", pct_of_book: 10, unrealized_pl: 40 }],
      positions: [
        { symbol: "NVDA", sector: "Technology", qty: 10, side: "long", market_value: 5000, pct_of_book: 5, unrealized_pl: 25, idea: "Idea One" },
        { symbol: "Cash", qty: null, side: null, market_value: 95000, pct_of_book: 95, unrealized_pl: null, idea: null },
      ],
    });
    const closed = {
      state: "live", as_of: "2026-11-12T15:00:00Z", book: "main",
      trades: [
        closedTrade({}),
        closedTrade({
          symbol: "XLE", sector: "Energy", exit_price: 95, exited_at: "2026-11-12T20:00:00Z",
          pnl: -50, return_pct: -5, held_days: 4, idea: "No idea yet (manual)",
        }),
      ],
      results_split: null,
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(
      JSON.stringify(String(url).includes("/api/portfolio/closed") ? closed : main), { status: 200 })));
  }

  it("renders every Performance card: curve, risk, daily, attribution, split, weeks and closed trades", async () => {
    servePerf();
    pageAt("/portfolio?tab=performance");
    expect(await screen.findByRole("region", { name: "Daily returns" })).toBeInTheDocument();
    for (const name of ["Return, All", "Risk", "Daily returns", "Where the return came from",
      "Tested vs discretionary", "Realized by week", "Closed trades, All"]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
    // Best and worst day from the curve's closes: Nov 11 +2.0%, Nov 10 -1.0%.
    expect(region("Daily returns").getByText(/Nov 11 \+2\.0%/)).toBeInTheDocument();
    expect(region("Daily returns").getByText(/Nov 10 −1\.0%/)).toBeInTheDocument();
    // Closed trades: count 2, net +$50, 50% wins, profit factor 2.
    expect(region("Closed trades, All").getByText("2")).toBeInTheDocument();
    expect(region("Closed trades, All").getByText("+$50")).toBeInTheDocument();
    expect(region("Closed trades, All").getByText(/Wins 50% · PF 2\.00/)).toBeInTheDocument();
    // No paragraphs on the page: the provisional-day note lives in the open view.
    expect(screen.queryByText(/provisional/)).toBeNull();
  });

  it("opens each Performance card to its detail", async () => {
    servePerf();
    pageAt("/portfolio?tab=performance");
    await screen.findByRole("region", { name: "Where the return came from" });
    // Attribution opens to both waterfalls and their tables.
    let full = openCard("Where the return came from");
    expect(full.getByText("By idea")).toBeInTheDocument();
    expect(full.getByText("By sector")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    // Stats open to every stat with its definition.
    full = openCard("Risk");
    expect(full.getByText("Volatility")).toBeInTheDocument();
    expect(full.getByText(/Standard deviation of daily returns/)).toBeInTheDocument();
    expect(full.getByText("Trading days")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    // The closed-trade list opens with its stats line.
    full = openCard("Closed trades, All");
    expect(full.getByText("Profit factor")).toBeInTheDocument();
    expect(full.getByText("2.00")).toBeInTheDocument();
    expect(full.getByText("3.0d")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    // Weeks open to a table, one row per week.
    full = openCard("Realized by week");
    expect(full.getByText("Week of")).toBeInTheDocument();
  });

  it("sorts the closed-trade list by the column clicked", async () => {
    servePerf();
    pageAt("/portfolio?tab=performance");
    await screen.findByRole("region", { name: "Closed trades, All" });
    const table = openCard("Closed trades, All").getByRole("table");
    const dataRows = () => within(table).getAllByRole("row").slice(1);
    // Default: newest exit first, so the Nov 12 XLE loss leads.
    expect(dataRows()[0]).toHaveTextContent("XLE");
    expect(dataRows()[1]).toHaveTextContent("NVDA");
    fireEvent.click(within(table).getByRole("button", { name: /Sort closed trades by Symbol/ }));
    expect(dataRows()[0]).toHaveTextContent("NVDA");
    expect(dataRows()[1]).toHaveTextContent("XLE");
  });
});

describe("Portfolio dashboard cards (Kevin, 2026-11-13)", () => {
  const pos = (symbol: string, value: number, over: Partial<PositionRow> = {}): PositionRow => ({
    symbol, qty: 10, side: "long", market_value: value, pct_of_book: 5, unrealized_pl: 10, day_pl: 5,
    change_pct: 0.5, idea: "Chips", sector: "Technology", ...over,
  });
  const EIGHT = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"];
  const trade = (symbol: string, i: number) => ({
    symbol, sector: "Technology", qty: 10, entry_price: 100, exit_price: 101,
    entered_at: "2026-11-02T15:00:00Z", exited_at: `2026-11-1${i % 3}T20:0${i}:00Z`,
    pnl: 10 + i, return_pct: 1, held_days: 2, idea: "Chips",
  });
  const order = (symbol: string, i: number) => ({
    symbol, side: "buy", qty: 1, filled_qty: 1, type: "market", time_in_force: "day", status: "filled",
    limit_price: null, stop_price: null, filled_avg_price: 10, submitted_at: `2026-11-12T15:0${i}:00Z`,
    filled_at: null, asset: "stock", source: "Machine order",
  });
  const staged = (symbol: string, i: number) => ({
    alpaca_order_id: `a${i}`, client_order_id: `c${i}`, symbol, side: "sell", type: "stop", time_in_force: "gtc",
    qty: 5, filled_qty: 0, limit_price: null, stop_price: 50 + i, status: "new", submitted_at: "2026-11-12T15:00:00Z",
  });
  const MAIN = payload({
    scoreboard: { ...EMPTY_SCORE, equity: 100000, return_pct: 1, spy_return_pct: 0.5, ahead_pts: 0.5, max_drawdown_pct: -1, win_rate: 50 },
    curve: [
      { t: "2026-11-09T21:00:00Z", portfolio_pct: 0, spy_pct: 0 },
      { t: "2026-11-10T21:00:00Z", portfolio_pct: 1, spy_pct: 0.5 },
    ],
    composition: [{ idea: "Chips", pct_of_book: 40, unrealized_pl: 80 }],
    positions: [
      ...EIGHT.map((s, i) => pos(s, 1000 * (i + 1))),
      { symbol: "Cash", qty: null, side: null, market_value: 64000, pct_of_book: 64, unrealized_pl: null, idea: null },
    ],
  });
  const ADMIN = /\/api\/(admin\/|workshop\/ideas|portfolio\/(portfolio-check|open-orders|manual-actions|orders))/;

  function serveDash(urls: string[] = []) {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
      if (url.includes("/api/admin/me")) return json({ email: "k@example.com" });
      if (url.includes("/api/workshop/ideas")) return json([]);
      if (url.includes("/api/portfolio/open-orders")) return json({ orders: EIGHT.map(staged) });
      if (url.includes("/api/portfolio/manual-actions")) {
        return json({ book: "main", actions: [{ id: 1, idea_id: 5, idea_title: "Spread", kind: "option", state: "open",
          symbol: "SPY", created_at: "2026-11-12T12:00:00Z", detail: "size it by hand" }] });
      }
      if (url.includes("/api/portfolio/portfolio-check")) return new Response("{}", { status: 404 });
      if (url.includes("/api/portfolio/activity")) {
        return json({ state: "live", as_of: "2026-11-12T20:00:00Z", book: "main", open: [], recent: EIGHT.map(order), trades: [] });
      }
      if (url.includes("/api/portfolio/closed")) {
        return json({ state: "live", as_of: "2026-11-12T20:00:00Z", book: "main", trades: EIGHT.map(trade), results_split: null });
      }
      if (url.includes("/api/portfolio/books")) return json({ books: [] });
      return json(MAIN);
    }));
    return urls;
  }

  /** Every card on the tab opens its view; Esc closes it and focus returns to the card. */
  async function eachCardOpensAndCloses(expected: string[]) {
    for (const name of expected) {
      // Keyboard path: focus the card, then activate it.
      const opener = screen.getByRole("button", { name: `Open ${name}` });
      opener.focus();
      fireEvent.click(opener);
      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();
      expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Close" }));
      fireEvent.keyDown(document, { key: "Escape" });
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(document.activeElement).toBe(opener);
    }
  }

  it("renders every Book card and opens each one", async () => {
    serveDash();
    pageAt("/portfolio?tab=book");
    await screen.findByRole("region", { name: "Positions" });
    const cards = ["Composition", "Account", "Today's movers", "Positions", "By idea"];
    for (const name of cards) expect(screen.getByRole("region", { name })).toBeInTheDocument();
    await eachCardOpensAndCloses(cards);
  });

  it("renders every Trade card signed in, with the ticket open on the page, and opens each list", async () => {
    session.token = "jwt";
    serveDash();
    pageAt("/portfolio?tab=trade");
    expect(await screen.findByText("size it by hand")).toBeInTheDocument();
    await screen.findByText("Staged orders");
    // The ticket is on the page, not behind a click.
    expect(screen.getByLabelText("Symbol")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Place an order by hand" })).toBeNull();
    await waitFor(() => expect(region("Recent orders").getByText("8")).toBeInTheDocument());
    await eachCardOpensAndCloses(["Needs your hand", "Staged orders", "Recent orders", "Closed trades"]);
  });

  it("renders every Performance card and opens each one", async () => {
    serveDash();
    pageAt("/portfolio?tab=performance");
    await screen.findByRole("region", { name: "Risk" });
    await waitFor(() => expect(region("Closed trades, All").getByText("8")).toBeInTheDocument());
    await eachCardOpensAndCloses(["Return, All", "Risk", "Daily returns", "Where the return came from",
      "Tested vs discretionary", "Realized by week", "Closed trades, All"]);
  });

  it("shows at most 5 rows of a long list on the page and every row in the open view", async () => {
    session.token = "jwt";
    serveDash();
    pageAt("/portfolio?tab=book");
    await screen.findByRole("region", { name: "Positions" });
    const peek = (name: string) => screen.getByRole("region", { name }).querySelectorAll("[data-peek] li");
    expect(peek("Positions")).toHaveLength(5);
    expect(openCard("Positions").getAllByRole("row")).toHaveLength(1 + 8);
    fireEvent.keyDown(document, { key: "Escape" });
    cleanup();
    pageAt("/portfolio?tab=trade");
    await screen.findByText("Staged orders");
    await waitFor(() => expect(region("Recent orders").getByText("8")).toBeInTheDocument());
    await waitFor(() => expect(region("Closed trades").getByText("8")).toBeInTheDocument());
    for (const name of ["Staged orders", "Recent orders", "Closed trades"]) {
      expect(peek(name)).toHaveLength(5);
      expect(openCard(name).getAllByRole("row")).toHaveLength(1 + 8);
      fireEvent.keyDown(document, { key: "Escape" });
    }
  });

  it("filters the open view's list", async () => {
    serveDash();
    pageAt("/portfolio?tab=book");
    await screen.findByRole("region", { name: "Positions" });
    const full = openCard("Positions");
    fireEvent.change(full.getByLabelText("Filter positions"), { target: { value: "ccc" } });
    expect(full.getAllByRole("row")).toHaveLength(2);
  });

  it("sends no admin call on any tab for a signed-out visitor", async () => {
    for (const tab of ["book", "performance", "trade"]) {
      const urls = serveDash();
      pageAt(`/portfolio?tab=${tab}`);
      await screen.findByRole("region", { name: tab === "performance" ? "Risk" : tab === "trade" ? "Closed trades" : "Positions" });
      await new Promise((r) => setTimeout(r, 50));
      expect(urls.filter((u) => ADMIN.test(u))).toEqual([]);
      expect(screen.queryByText("Place an order by hand")).toBeNull();
      expect(screen.queryByText("Staged orders")).toBeNull();
      expect(screen.queryByText("Needs your hand")).toBeNull();
      cleanup();
      vi.unstubAllGlobals();
    }
  });

  it("shows unknown values as a dash, never 0", async () => {
    serve(payload({
      scoreboard: { ...EMPTY_SCORE, equity: 100000 },
      positions: [pos("AAA", 1000, { unrealized_pl: null, day_pl: null, change_pct: null })],
    }));
    page(<Portfolio />);
    await screen.findByRole("region", { name: "Account" });
    // Buying power, short value and the open P&L are unknown on this payload.
    expect(region("Account").getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(region("Positions").getByText(/Open/).textContent).toContain("—");
    expect(region("Composition").getAllByText("—").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("$0")).toBeNull();
    expect(screen.queryByText("+$0")).toBeNull();
    cleanup();
    serve(payload({ scoreboard: { ...EMPTY_SCORE, equity: 100000 } }));
    pageAt("/portfolio?tab=performance");
    await screen.findByRole("region", { name: "Risk" });
    expect(region("Return, All").getAllByText("—").length).toBeGreaterThanOrEqual(1);
    expect(region("Daily returns").getAllByText("—").length).toBeGreaterThanOrEqual(1);
    expect(region("Where the return came from").getAllByText("—").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("+0.0%")).toBeNull();
  });
});
