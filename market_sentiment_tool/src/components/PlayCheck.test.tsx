import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: null } }), onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }) } },
}));

import { PlayCheckButton } from "@/components/PlayCheck";

const RESULT = {
  available: true, state: "in", exit_reason: null, otherwise: "SPY", size_pct: 10,
  equity: 100_000, cash: 55_000, buys: 10_000, sells: 5_000, verdict: "affordable", shortfall: 0,
  cap_breaches: [], verdict_line: "Runnable at 10% size — $10,000 of buys, $5,000 of it funded by sells",
  as_of: "2026-11-02T15:00:00+00:00", options_legs: [],
  rows: [
    { ticker: "GLD", weight: 1, price: 250, target_value: 10_000, target_shares: 40, held_shares: 0,
      held_value: 0, delta_value: 10_000, delta_shares: 40, overlap_ideas: [], cap_breach: false },
    { ticker: "SPY", weight: null, price: 500, target_value: 0, target_shares: 0, held_shares: 10,
      held_value: 5_000, delta_value: -5_000, delta_shares: -10, overlap_ideas: [], cap_breach: false },
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
