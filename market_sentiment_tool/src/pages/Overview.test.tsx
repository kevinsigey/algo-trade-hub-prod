import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Overview from "@/pages/Overview";
import { biggestMovers } from "@/lib/overview";
import type { SeriesEntry } from "@/lib/journal";

// The signed-in staged-orders probe loads the Supabase client: stub it (no session).
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const journal = {
  as_of: "2026-11-02T06:00:00+00:00",
  forecasters: [],
  headline: { forecasters: 0, calibrated: 0, frozen_calibrated: 1420, settled_calibrated: 1210, promoted: 0, market_skill: null },
};

const series: SeriesEntry[] = [
  {
    forecaster: "oil_wti_hourly", version: "wti-hourly-v1",
    points: [
      { date: "2026-10-27", gap: -0.01, se: 0.004, n: 40 },
      { date: "2026-10-28", gap: -0.012, se: 0.004, n: 55 },
      { date: "2026-10-29", gap: -0.011, se: 0.004, n: 70 },
      { date: "2026-10-30", gap: -0.014, se: 0.004, n: 88 },
      { date: "2026-10-31", gap: -0.016, se: 0.004, n: 99 },
      { date: "2026-11-01", gap: -0.03, se: 0.005, n: 120 },
    ],
  },
  {
    forecaster: "labor_nowcast", version: "jobs-v1",
    points: [
      { date: "2026-10-01", gap: 0.004, se: 0.003, n: 30 },
      { date: "2026-11-01", gap: 0.006, se: 0.003, n: 42 },
    ],
  },
];

const portfolio = {
  state: "live",
  as_of: "2026-11-02T06:00:00+00:00",
  account_number: "PA123",
  scoreboard: { start_at: null, equity: 100_450, return_pct: 0.45, spy_return_pct: 0.3, ahead_pts: 0.15, max_drawdown_pct: null, sharpe: null, win_rate: null },
  curve: [],
  composition: [],
  positions: [{ symbol: "XLE", qty: 100, side: "long", market_value: 6900, pct_of_book: 6.9, unrealized_pl: 40, idea: null }],
};

function stubFetch() {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const body = url.includes("/api/journal/series")
      ? { series }
      : url.includes("/api/journal/previews")
        ? { previews: [] }
        : url.includes("/api/portfolio")
          ? portfolio
          : url.includes("/api/admin/me")
            ? Promise.reject(new Error("not signed in"))
            : journal;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("biggestMovers", () => {
  it("ranks by absolute edge change with the sign flipped to edge", () => {
    const movers = biggestMovers(series);
    expect(movers[0].label).toContain("WTI");
    expect(movers[0].delta).toBeCloseTo(0.02);
    expect(movers[1].delta).toBeCloseTo(-0.002);
  });

  it("needs at least two measured points", () => {
    expect(biggestMovers([{ forecaster: "x", version: "v", points: [{ date: "2026-11-01", gap: -0.01, se: null, n: 1 }] }])).toEqual([]);
  });
});

describe("Overview page", () => {
  it("leads with the live book, then movers, then what is next", async () => {
    stubFetch();
    render(
      <MemoryRouter>
        <Overview />
      </MemoryRouter>,
    );
    expect(await screen.findByText("$100,450")).toBeInTheDocument();
    expect(screen.getByText("open positions")).toBeInTheDocument();
    expect(await screen.findByText(/improving/)).toBeInTheDocument();
    expect(screen.getByText(/1,420 forecasts locked in/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the Model Tracker/ })).toHaveAttribute("href", "/journal");
  });

  it("shows no Coming up heading when nothing is coming up", async () => {
    stubFetch();  // previews: []
    render(<MemoryRouter><Overview /></MemoryRouter>);
    expect(await screen.findByText("$100,450")).toBeInTheDocument();
    expect(screen.queryByText("Coming up")).not.toBeInTheDocument();
  });
});
