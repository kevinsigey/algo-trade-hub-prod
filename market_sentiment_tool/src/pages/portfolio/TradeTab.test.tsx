import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// The closed-trades box's read states (CodeRabbit, PR #514): useApi is
// driven directly so a failed first read, a stale last-good read, and a
// good empty read can be told apart. Everything admin-gated stays shut
// (the fetch stub 401s /api/admin/me, like a signed-out visitor).
const { closed, emptyApi } = vi.hoisted(() => ({
  closed: {
    current: { data: null, error: null, loading: false, stale: false } as {
      data: unknown; error: string | null; loading: boolean; stale: boolean;
    },
  },
  // Identity-stable: OrdersBox stores its read in an effect keyed on the
  // data object, so a fresh literal per call would loop renders forever.
  emptyApi: { data: { orders: [], recent: [] }, error: null, loading: false, stale: false },
}));

vi.mock("@/hooks/usePaperPortfolio", () => ({
  useApi: (path: string) => (path.includes("/api/portfolio/closed")
    ? closed.current
    : emptyApi),
}));
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: null } }) } },
}));
vi.stubGlobal("fetch", vi.fn(async () =>
  new Response(JSON.stringify({ detail: "admin only" }), { status: 401 })));

import TradeTab from "./TradeTab";

const TRADE = {
  symbol: "NVDA", sector: "Technology", qty: 10, entry_price: 0.45, exit_price: 0.49,
  entered_at: "2026-11-02T15:00:00Z", exited_at: "2026-11-10T20:00:00Z",
  pnl: 4, return_pct: 8.9, held_days: 8, idea: "Idea One",
};

describe("Trade tab closed-trades read states", () => {
  it("marks the last good read stale after a failed refresh", () => {
    closed.current = { data: { trades: [TRADE] }, error: null, loading: false, stale: true };
    render(<MemoryRouter><TradeTab book="main" /></MemoryRouter>);
    expect(screen.getByText(/Last good read/)).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    // Entry and exit prices keep their cents (the whole-dollar formatter
    // showed both as $0); they live in the card's full table.
    fireEvent.click(screen.getByRole("button", { name: "Open Closed trades" }));
    const full = within(screen.getByRole("dialog"));
    expect(full.getByText("$0.45")).toBeInTheDocument();
    expect(full.getByText("$0.49")).toBeInTheDocument();
  });

  it("shows a successful empty read as empty, not stale or unreadable", () => {
    closed.current = { data: { trades: [] }, error: null, loading: false, stale: false };
    render(<MemoryRouter><TradeTab book="main" /></MemoryRouter>);
    expect(screen.getByText("No closed trades yet.")).toBeInTheDocument();
    expect(screen.queryByText(/Last good read/)).toBeNull();
    expect(screen.queryByText(/Couldn't read closed trades/)).toBeNull();
  });

  it("shows a failed first read as unreadable, never as an empty list", () => {
    closed.current = { data: null, error: "boom", loading: false, stale: false };
    render(<MemoryRouter><TradeTab book="main" /></MemoryRouter>);
    expect(screen.getByText(/Couldn't read closed trades/)).toBeInTheDocument();
    expect(screen.queryByText("No closed trades yet.")).toBeNull();
    // The count is unknown, so it reads as a dash, not 0.
    const card = within(screen.getByRole("region", { name: "Closed trades" }));
    expect(card.queryByText("0")).toBeNull();
    expect(card.getByText("—")).toBeInTheDocument();
  });
});
