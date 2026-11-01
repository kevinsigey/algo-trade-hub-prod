import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import JournalSports from "@/components/JournalSports";

const PAYLOAD = {
  as_of: "2026-11-01T00:00:00Z",
  sports: [
    {
      sport: "nfl", status: "ok",
      rows: [
        { sport: "nfl", market: "spread", label: "Spread", n: 300, hit_rate: 0.51, n_pre: null, hit_rate_pre: null, vs_market: null, note: null },
        { sport: "nfl", market: "moneyline", label: "Moneyline", n: 500, hit_rate: 0.56, n_pre: 480, hit_rate_pre: 0.55, vs_market: null, note: null },
        { sport: "nfl", market: "total", label: "Totals", n: 280, hit_rate: 0.49, n_pre: null, hit_rate_pre: null, vs_market: null, note: null },
      ],
    },
    { sport: "nba", status: "unavailable", error: "site down", rows: [] },
  ],
};

describe("JournalSports (journal sports tab)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true, status: 200, headers: { get: () => "application/json" },
      json: async () => PAYLOAD,
    })));
  });

  it("leads each sport with its headline market and folds the rest", async () => {
    render(<JournalSports scores={null} />);
    // Headline = moneyline even though it is not the first row in the payload.
    expect(await screen.findByText("56%")).toBeTruthy();
    expect(screen.getByText("Moneyline")).toBeTruthy();
    expect(screen.getByText(/Before the event: 55% of 480/)).toBeTruthy();
    // The other markets sit under one dropdown summary.
    expect(screen.getByText("All markets (3)")).toBeTruthy();
    expect(screen.getByText("Spread")).toBeTruthy();
    expect(screen.getByText("Totals")).toBeTruthy();
    // An unavailable site says so on its own card, never silently missing.
    expect(screen.getByText("NBA")).toBeTruthy();
    expect(screen.getByText("Unavailable right now")).toBeTruthy();
  });
});
