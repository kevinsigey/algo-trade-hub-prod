import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Crypto from "@/pages/Crypto";

vi.mock("@/lib/supabase", () => ({ supabase: { auth: { getSession: async () => ({ data: { session: null } }) } } }));

const sig = (key: string, label: string, value: number | null, stress: number | null, reading: string) =>
  ({ key, label, value, unit: "% a year", percentile: null, normal: null, stress, weight: 2, reading, why: `Why ${label}` });

const WATCH = {
  as_of: "2026-11-06T02:00:00Z",
  stress: { stress: 0.35, label: "Watch", speaking: 9, of: 9 },
  coins: {
    BTC: { price: 76050, change_24h_pct: -5.6, signals: [
      sig("funding", "Funding rate", 10.95, 0.4, "BTC longs pay shorts 10.9% a year."),
      sig("realized_vol", "Realized volatility", 68, 0.48, "BTC moved like 68% a year."),
    ] },
    ETH: { price: 2238, change_24h_pct: -7.9, signals: [
      sig("funding", "Funding rate", 10.95, 0.56, "ETH longs pay shorts 10.9% a year."),
      sig("realized_vol", "Realized volatility", null, null, "Hyperliquid's candles is unavailable right now."),
    ] },
  },
  market: [sig("stablecoins", "Stablecoin supply", 293.7, 0.67, "$293.7bn in stablecoins, −2.01% in a week: money leaving.")],
};

function serve(watch: unknown) {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url);
    const body = u.includes("/api/crypto/watch") ? watch : u.includes("/api/journal") ? { forecasters: [], headline: {} } : {};
    return new Response(JSON.stringify(body), { status: 200 });
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("Crypto watcher", () => {
  it("leads with the stress read and the prices, then one tile per signal with both coins", async () => {
    serve(WATCH);
    render(<MemoryRouter><Crypto /></MemoryRouter>);
    expect(await screen.findByText("Watch")).toBeInTheDocument();
    expect(screen.getByText("$76,050")).toBeInTheDocument();
    expect(screen.getByText("−5.6%")).toBeInTheDocument();
    const funding = screen.getByRole("region", { name: "Funding rate" });
    expect(within(funding).getByText("BTC")).toBeInTheDocument();
    expect(within(funding).getByText("ETH")).toBeInTheDocument();
    // The tile's sentence is the coin under the most stress.
    expect(within(funding).getByText("ETH longs pay shorts 10.9% a year.")).toBeInTheDocument();
    const realized = screen.getByRole("region", { name: "Realized volatility" });
    expect(within(realized).getByText("—")).toBeInTheDocument();  // unknown is a dash, never zero
    fireEvent.click(within(funding).getByText("Why it matters"));
    expect(within(funding).getByText("Why Funding rate")).toBeVisible();
    expect(screen.getByRole("region", { name: "Stablecoin supply" })).toHaveTextContent("money leaving");
  });

  it("says so when the watch is unavailable", async () => {
    serve({ state: "unavailable" });
    render(<MemoryRouter><Crypto /></MemoryRouter>);
    expect(await screen.findByText(/market signals are unavailable right now/i)).toBeInTheDocument();
  });
});
