import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Overview from "@/pages/Overview";
import { cents, dayRange, gasRecord, gasTrend, metalsPerTrade, modelsBeating, oilPerTrade, testedVsManual } from "@/lib/overview";
import type { JournalScore } from "@/lib/journal";

// Nothing on this page may need a session; stub the client so an accidental import can't reach the network.
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

function score(forecaster: string, gap: number, se: number, baseline: JournalScore["baseline"] = "market"): JournalScore {
  return {
    forecaster, forecaster_version: "v1", cadence: "daily", baseline, n_targets: 300, n_settled: 300,
    brier: 0.2, brier_baseline: 0.21, bss: 0.05, gap, gap_se: se, reliability: [], murphy: {},
    calibration_ready: true, gate_status: "SHADOW", gate_reasons: [], computed_at: "2026-11-12T00:00:00+00:00",
  };
}

const journal = {
  forecasters: [
    score("cpi_nowcast", -0.02, 0.005),       // beating its market
    score("labor_nowcast", 0.001, 0.004),     // level
    score("gas", 0.05, 0.01),                 // behind, and retired
    score("vix_direction", -0.02, 0.005, "climatology"),  // beating, but not a market
  ],
  headline: { settled_calibrated: 185_526 },
  retired: [{ forecaster: "gas", version: "v1" }, { forecaster: "oil", version: "v1" }],
};

const daily = (rows: [string, number, number][]) => rows.map(([day, n, total]) => ({ day, n, total }));

const fifteen = {
  gate: {
    by_series: {
      WTI: { n: 31, net_per_contract: -0.0191, total: -0.59, low95: -0.15 },
      Brent: { n: 31, net_per_contract: 0.0205, total: 0.64, low95: -0.12 },
      "Natural gas": { n: 66, net_per_contract: 0.1233, total: 8.14, low95: 0.0112 },
    },
    daily: {
      "Natural gas": daily([["2026-11-06", 10, 1.9], ["2026-11-07", 10, 1.6], ["2026-11-08", 0, 0],
                            ["2026-11-09", 10, 1.72], ["2026-11-10", 10, 0.3], ["2026-11-11", 10, 0.2], ["2026-11-12", 10, 0.25]]),
    },
  },
  metals: { gate: { forward: { n: 167, net_per_contract: -0.061, total: -10.18, low95: -0.12 } } },
};

const closed = {
  results_split: {
    tested: { trades: 31, pnl: 177.28, wins: 20 },
    discretionary: { trades: 33, pnl: -1767.55, wins: 3, reasons: [] },
  },
};

function stubFetch(bodies: Record<string, unknown>) {
  const urls: string[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    urls.push(url);
    const key = Object.keys(bodies).find((k) => url.endsWith(k));
    if (!key) return Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: "down" }) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(bodies[key]) });
  }));
  return urls;
}

afterEach(() => vi.unstubAllGlobals());

describe("headline numbers from fixture payloads", () => {
  it("counts live predictors beating their market, leaving retired and non-market rows out", () => {
    expect(modelsBeating(journal)).toEqual({ beating: 1, measured: 2, retired: 2, scored: 185_526 });
    // Without the retired list the count still works, over every row, and the retired figure is unknown.
    expect(modelsBeating({ ...journal, retired: null })).toMatchObject({ beating: 1, measured: 3, retired: null });
    expect(modelsBeating(null)).toBeNull();
  });

  it("reads gas's gated record and its 95% range", () => {
    const g = gasRecord(fifteen)!;
    expect(g.perTrade).toBeCloseTo(0.1233);
    expect(g.low).toBeCloseTo(0.0112);
    expect(g.high).toBeCloseTo(0.2354);
    expect(g.n).toBe(66);
    expect(gasRecord({})).toBeNull();
  });

  it("splits gas's last three trading days from the days before them", () => {
    const t = gasTrend(fifteen)!;
    expect(dayRange(t.earlier.from, t.earlier.to)).toBe("Nov 6–9");
    expect(t.earlier.perTrade).toBeCloseTo(5.22 / 30);
    expect(dayRange(t.recent.from, t.recent.to)).toBe("Nov 10–12");
    expect(t.recent.perTrade).toBeCloseTo(0.75 / 30);
    expect(gasTrend({ gate: { daily: { "Natural gas": daily([["2026-11-10", 1, 0.1]]) } } })).toBeNull();
  });

  it("pools oil across WTI and Brent and reads metals' gated forward record", () => {
    expect(oilPerTrade(fifteen)).toBeCloseTo(0.05 / 62);
    expect(metalsPerTrade(fifteen)).toBeCloseTo(-0.061);
    expect(oilPerTrade({})).toBeNull();
  });

  it("reads tested ideas against manual trades, and words cents", () => {
    expect(testedVsManual(closed)?.tested.pnl).toBeCloseTo(177.28);
    expect(testedVsManual({})).toBeNull();
    expect(cents(0.1233)).toBe("+12.3¢");
    expect(cents(-0.061)).toBe("−6.1¢");
    expect(cents(null)).toBe("—");
  });
});

describe("Overview page", () => {
  it("renders the whole page for a signed-out visitor from public reads only", async () => {
    const urls = stubFetch({ "/api/journal": journal, "/api/oil/fifteen-rule": fifteen, "/api/portfolio/closed": closed });
    render(<MemoryRouter><Overview /></MemoryRouter>);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/solo research desk/);
    const numbers = screen.getByRole("region", { name: "Headline numbers" });
    expect(await within(numbers).findByText("1 of 2")).toBeInTheDocument();
    expect(await within(numbers).findByText("+12.3¢")).toBeInTheDocument();
    expect(within(numbers).getByText(/\+1\.1¢ to \+23\.5¢, clear of zero/)).toBeInTheDocument();
    expect(await within(numbers).findByText("+$177")).toBeInTheDocument();
    expect(within(numbers).getByText("−$1,768")).toBeInTheDocument();
    const record = screen.getByRole("region", { name: "The record so far" });
    expect(record).toHaveTextContent("Retired for trailing their markets: 2 models.");
    expect(record).toHaveTextContent("gas went from +17.4¢ a trade on Nov 6–9 to +2.5¢ on Nov 10–12");
    expect(record).toHaveTextContent("Oil is flat at +0.1¢ a trade and metals negative at −6.1¢");
    const start = screen.getByRole("navigation", { name: "Start here" });
    expect(within(start).getByRole("link", { name: "The 15-minute rules" })).toHaveAttribute("href", "/strategies");
    expect(within(start).getByRole("link", { name: "The stock book" })).toHaveAttribute("href", "/portfolio");
    expect(within(start).getByRole("link", { name: "Kalshi demo" })).toHaveAttribute("href", "/portfolio?book=kalshi");
    expect(urls.some((u) => u.includes("/api/admin"))).toBe(false);
  });

  it("shows a dash, never a zero, for every number a read could not supply", async () => {
    const urls = stubFetch({});  // every read fails
    render(<MemoryRouter><Overview /></MemoryRouter>);
    const numbers = screen.getByRole("region", { name: "Headline numbers" });
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });  // let the failed reads settle
    expect(urls).toHaveLength(3);
    expect(await within(numbers).findAllByText("—")).toHaveLength(6);  // models, gas, tested and manual with their win lines
    expect(numbers).not.toHaveTextContent(/\b0 of|\+0\.0¢|\$0/);
    const record = screen.getByRole("region", { name: "The record so far" });
    expect(record).toHaveTextContent("Retired for trailing their markets: — models.");
    expect(record).not.toHaveTextContent(/\b0 models|\+0\.0¢/);
  });
});
