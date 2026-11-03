import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: null } }), onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }) } },
}));

import { PlayCheckButton } from "@/components/PlayCheck";

const RESULT = {
  available: true, state: "in", exit_reason: null, otherwise: "SPY", size_pct: 10,
  book: "main", book_label: "Main book", sleeve_usd: 10_000, already_in_place_usd: 2_000, in_place_pct: 20,
  equity: 100_000, cash: 55_000, buys: 8_000, sells: 0, verdict: "affordable", shortfall: 0,
  cap_breaches: [], verdict_line: "Runnable at 10% size — $8,000 of buys, covered by the $55,000 cash on hand",
  as_of: "2026-11-02T15:00:00+00:00", options_legs: [],
  rows: [
    { ticker: "GLD", weight: 0.8, price: 250, target_value: 8_000, target_shares: 32, held_shares: 0,
      held_value: 0, delta_value: 8_000, delta_shares: 32, coverage_pct: 0, overlap_ideas: [], cap_breach: false },
    { ticker: "ASML", weight: 0.2, price: 500, target_value: 2_000, target_shares: 4, held_shares: 4,
      held_value: 2_000, delta_value: 0, delta_shares: 0, coverage_pct: 100, overlap_ideas: [], cap_breach: false },
  ],
  notes: ["Prices are latest closes, not live quotes."],
};

afterEach(() => vi.unstubAllGlobals());

describe("the play check sheet", () => {
  it("opens, runs, and leads with the verdict", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => RESULT })));
    render(<PlayCheckButton ideaId={42} source="public" title="ASML gate" />);
    fireEvent.click(screen.getByRole("button", { name: /Can I run this/ }));
    expect(screen.getByRole("dialog", { name: /Play check for ASML gate/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(screen.getByText(/Runnable at 10% size/)).toBeInTheDocument());
    expect(screen.getByText(/The rule is IN today/)).toBeInTheDocument();
    expect(screen.getByText("GLD")).toBeInTheDocument();
    expect(screen.getByText(/already in place/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "$1M book" })).toBeInTheDocument();
    expect(screen.getByText(/Prices are latest closes/)).toBeInTheDocument();
  });

  it("says so plainly when there is no book to check against", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ available: false, size_pct: 10, note: "No paper account is connected, so there is no book to check the play against." }) })));
    render(<PlayCheckButton ideaId={42} source="public" title="ASML gate" />);
    fireEvent.click(screen.getByRole("button", { name: /Can I run this/ }));
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(screen.getByText(/No paper account is connected/)).toBeInTheDocument());
  });
});
