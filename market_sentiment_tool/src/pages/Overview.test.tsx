import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Overview from "@/pages/Overview";
import { cents, dayRange, gasRecord, gasTrend, metalsPerTrade, modelsBeating, oilPerTrade, testedVsManual, type FifteenLite } from "@/lib/overview";
import { viewRows } from "@/lib/journalView";
import { beatingCount, league } from "@/lib/league";
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
    score("gas", 0.05, 0.01),                 // behind
    score("vix_direction", -0.02, 0.005, "climatology"),  // beating its climatology baseline
  ],
  headline: { settled_calibrated: 185_526 },
  retired_models: 24,
};

const daily = (rows: [string, number, number][]) => rows.map(([day, n, total]) => ({ day, n, total }));

function withGasDays(rows: [string, number, number][]): FifteenLite {
  return { gate: { daily: { "Natural gas": daily(rows) } } };
}

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
  it("is exactly the Model Tracker's count, and passes the retired count through", () => {
    const tracker = beatingCount(league(viewRows(journal.forecasters)));
    expect(modelsBeating(journal)).toEqual({ ...tracker, retired: 24, scored: 185_526 });
    expect(tracker).toEqual({ beating: 2, measured: 4 });
    expect(modelsBeating({ ...journal, retired_models: null })?.retired).toBeNull();
    expect(modelsBeating({ forecasters: journal.forecasters })?.retired).toBeNull();  // an older server
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

  it("calls the gas edge fading only when recent is lower and both spans hold 10 trades", () => {
    const t = gasTrend(fifteen)!;
    expect(t.verdict).toBe("fading");
    expect(dayRange(t.earlier.from, t.earlier.to)).toBe("Nov 6–9");
    expect(t.earlier).toMatchObject({ n: 30 });
    expect(t.earlier.perTrade).toBeCloseTo(5.22 / 30);
    expect(dayRange(t.recent.from, t.recent.to)).toBe("Nov 10–12");
    expect(t.recent).toMatchObject({ n: 30 });
    expect(t.recent.perTrade).toBeCloseTo(0.75 / 30);
  });

  it("calls it holding when recent is at or above earlier", () => {
    const up = withGasDays([["2026-11-07", 12, 0.6], ["2026-11-10", 4, 0.4], ["2026-11-11", 4, 0.4], ["2026-11-12", 4, 0.4]]);
    expect(gasTrend(up)?.verdict).toBe("holding");
  });

  it("says nothing when either span is under 10 trades", () => {
    expect(gasTrend(withGasDays([["2026-11-07", 9, 1.8], ["2026-11-10", 10, 0.1], ["2026-11-11", 1, 0], ["2026-11-12", 1, 0]]))).toBeNull();
    expect(gasTrend(withGasDays([["2026-11-07", 30, 3], ["2026-11-10", 3, 0], ["2026-11-11", 3, 0], ["2026-11-12", 3, 0]]))).toBeNull();
    expect(gasTrend(withGasDays([["2026-11-10", 20, 0.1]]))).toBeNull();
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

const book = (equity: number, ret: number, ahead: number) =>
  ({ state: "live", as_of: "2026-11-25T15:00:00Z", scoreboard: { equity, return_pct: ret, ahead_pts: ahead, spy_return_pct: 1 }, curve: [] });

const ALL = {
  "/api/journal": journal, "/api/oil/fifteen-rule": fifteen, "/api/portfolio/closed": closed,
  "/api/portfolio?book=main": book(101_234, 1.2, 0.4), "/api/portfolio?book=big": book(1_002_000, 0.2, -0.8),
  "/api/ideas": [{ live_books: ["main"] }, { live_books: [] }], "/api/ideas/summary": { tested: 12, passed: 5 },
  "/api/kalshi-demo": { state: "x", live_pilot: { admin_only: true } },
};

describe("Overview page", () => {
  it("renders every card from public reads only, and the Kalshi card hides dollars for a visitor", async () => {
    const urls = stubFetch(ALL);
    render(<MemoryRouter><Overview /></MemoryRouter>);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Algo Trade Hub");
    const numbers = screen.getByRole("region", { name: "Headline numbers" });
    expect(await within(numbers).findByText("2 of 4")).toBeInTheDocument();
    expect((await within(numbers).findAllByText("$101,234")).length).toBeGreaterThan(0);
    expect(within(numbers).getByText("+1.2% · +0.4 pts")).toBeInTheDocument();
    expect(await within(numbers).findByText("5 of 12 tests passing")).toBeInTheDocument();
    expect(within(numbers).getByText("+$177")).toBeInTheDocument();
    expect(within(numbers).getByText("−$1,768")).toBeInTheDocument();
    expect(within(numbers).getByText("+12.3¢")).toBeInTheDocument();  // gas, 15-minute card
    const kalshi = within(numbers).getByRole("region", { name: "Kalshi live" });
    expect(await within(kalshi).findByText("Admin only")).toBeInTheDocument();
    expect(kalshi).toHaveTextContent("REAL MONEY");
    expect(kalshi).not.toHaveTextContent("$");
    expect(within(numbers).getByRole("link", { name: /Live book/ })).toHaveAttribute("href", "/portfolio?book=kalshi");
    expect(within(numbers).getByRole("link", { name: /Closed trades/ })).toHaveAttribute("href", "/portfolio?tab=trade");
    expect(screen.queryByRole("navigation", { name: "Start here" })).toBeNull();
    expect(urls.some((u) => u.includes("/api/admin"))).toBe(false);
  });

  it("shows the verdict as one-liners and the long text in its open view", async () => {
    stubFetch(ALL);
    render(<MemoryRouter><Overview /></MemoryRouter>);
    const verdictCard = screen.getByRole("region", { name: "Verdict" });
    expect(await within(verdictCard).findByText(/185,526 forecasts graded in public; gas \+12\.3¢/)).toBeInTheDocument();
    expect(verdictCard).toHaveTextContent("24 models retired; oil +0.1¢, metals −6.1¢");
    fireEvent.click(within(verdictCard).getByRole("button", { name: "Open Verdict" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(
      "The 15-minute gas edge is fading: +2.5¢ a paper trade over the last 3 days with trades (Nov 10–12, 30 trades), down from +17.4¢ before (Nov 6–9, 30 trades).");
    expect(dialog).toHaveTextContent("Oil is flat at +0.1¢ a paper trade and metals negative at −6.1¢");
  });

  it("opens how it's built with the corrected money line", () => {
    stubFetch({});
    render(<MemoryRouter><Overview /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "How it\u2019s built" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("All trading is paper, except one small real-money Kalshi pilot.");
  });

  it("shows a dash, never a zero, for every number a read could not supply", async () => {
    const urls = stubFetch({});  // every read fails
    render(<MemoryRouter><Overview /></MemoryRouter>);
    const numbers = screen.getByRole("region", { name: "Headline numbers" });
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });  // let the failed reads settle
    expect(urls.length).toBeGreaterThanOrEqual(8);
    expect(await within(numbers).findAllByText("—")).not.toHaveLength(0);
    expect(numbers).not.toHaveTextContent(/\b0 of|\+0\.0¢|\$0|…/);
  });
});
