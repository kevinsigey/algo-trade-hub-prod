import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import Oil, { StrikeBoard, TradeVerdict } from "@/pages/Oil";
import type { JournalFeed, JournalResponse, JournalScore } from "@/lib/journal";
import { copyWords } from "@/test/copyWords";

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "oil_wti", forecaster_version: "wti-v1", cadence: "daily", baseline: "market", n_targets: 0,
    n_settled: 0, brier: null, brier_baseline: null, bss: null, reliability: [], murphy: {}, calibration_ready: false,
    gate_status: "SHADOW", gate_reasons: [], computed_at: "2026-10-01T13:00:00+00:00", ...over,
  };
}

function serve(forecasters: JournalScore[], feed: Partial<JournalFeed> = {}, live?: unknown, fifteen?: unknown) {
  const journal: JournalResponse = {
    as_of: "x", forecasters, headline: { forecasters: forecasters.length, calibrated: 0, frozen_calibrated: 0, settled_calibrated: 0, promoted: 0, market_skill: null },
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const u = String(url);
    const body = u.includes("/api/oil/fifteen-live")
      ? (fifteen ?? { state: "live", markets: [] })
      : u.includes("/api/oil/hourly-live")
      ? (live ?? { state: "unavailable", reason: "no live ladder in this test" })
      : u.includes("/api/journal/feed")
        ? { forecaster: "oil_wti", forecaster_version: "wti-v1", generated_at: "x", forecasts: [], calibration: [], gate_status: "SHADOW", provisional: true, ...feed }
        : journal;
    return { ok: true, json: async () => body } as Response;
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("/oil", () => {
  it("shows only the CPI forecasters, plainly named, and says when nothing is locked in", async () => {
    serve([
      score(), score({ forecaster: "kalshi_implied_oil", forecaster_version: "v1" }),
      score({ forecaster: "spy_quant", forecaster_version: "spy-wf-v1", cadence: "daily" }),
    ]);
    const { container } = render(<MemoryRouter><Oil /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Track record" })).toBeTruthy());
    // The record sits behind the Daily dropdown now (2026-11-02 dashboard pass).
    fireEvent.click(screen.getByRole("button", { name: /Daily settlement/ }));
    expect(screen.getByRole("heading", { name: "WTI crude oil (daily settlement)" })).toBeTruthy();
    expect(screen.queryByText(/S&P/)).toBeNull();
    expect(screen.getByText(/Nothing locked in yet/)).toBeTruthy();
    // The budget grows with the page: the 2026-11-03 Commodities redesign adds the
    // live hero and its labels -- still headings and labels, never essays.
    expect(copyWords(container)).toBeLessThanOrEqual(60);
  });

  it("shows a scored forecast as a number with a verdict, and a missing score as a dash, never zero", async () => {
    serve([score({ n_targets: 30, n_settled: 30, brier: 0.09, brier_baseline: 0.07, bss: -0.2 }),
           score({ forecaster: "baseline_persistence_oil", n_targets: 2 })]);
    render(<MemoryRouter><Oil /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("button", { name: /Daily settlement/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Daily settlement/ }));
    expect(screen.getByRole("heading", { name: "WTI crude oil (daily settlement)" })).toBeTruthy();
    expect(screen.getAllByText("Behind").length).toBeGreaterThan(0);
    expect(screen.getByText("-0.20")).toBeTruthy();
  });

  it("shows hourly rows under their own heading, apart from the daily rows", async () => {
    serve([
      score(),
      score({ forecaster: "oil_wti_hourly", forecaster_version: "wti-hourly-v1", cadence: "hourly", n_targets: 40 }),
      score({ forecaster: "kalshi_implied_oil_hourly", forecaster_version: "v1", cadence: "hourly" }),
    ]);
    render(<MemoryRouter><Oil /></MemoryRouter>);
    // Both records are dropdowns now; the hourly rows live under their own.
    await waitFor(() => expect(screen.getByRole("button", { name: /Hourly settlements/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Hourly settlements/ }));
    fireEvent.click(screen.getByRole("button", { name: /Daily settlement/ }));
    expect(screen.getByRole("heading", { name: "WTI crude oil (hourly, old delayed feed)" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "WTI crude oil (daily settlement)" })).toBeTruthy();
  });

  it("the frozen record reads the live-feed model when both hourly models are there", async () => {
    serve([
      score({ forecaster: "oil_wti_hourly", forecaster_version: "wti-hourly-v1", cadence: "hourly", n_targets: 40 }),
      score({ forecaster: "oil_wti_hourly", forecaster_version: "wti-hourly-v4-hl-shadow", cadence: "hourly", n_targets: 20 }),
    ]);
    render(<MemoryRouter><Oil /></MemoryRouter>);
    await waitFor(() => {
      const urls = vi.mocked(fetch).mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes("forecaster=oil_wti_hourly&version=wti-hourly-v4-hl-shadow"))).toBe(true);
      expect(urls.some((u) => u.includes("version=wti-hourly-v1"))).toBe(false);
    });
  });

  it("the frozen record opens from its dropdown: the 50% level and the strikes", async () => {
    const ladder = [100, 101, 102].map((strike, i) => ({
      target: `kalshi:KXWTIH-26NOV0214-T${strike}.00`, probability: [0.9, 0.5, 0.1][i], market_prob: null,
      frozen_at: "2026-11-02T17:55:00+00:00", rebuilt: false, source_hash: "x",
    }));
    serve(
      [score({ forecaster: "oil_wti_hourly", forecaster_version: "wti-hourly-v1", cadence: "hourly", n_targets: 40 })],
      { forecaster: "oil_wti_hourly", forecaster_version: "wti-hourly-v1", forecasts: ladder },
    );
    render(<MemoryRouter><Oil /></MemoryRouter>);
    // The frozen record hides behind its dropdown (Kevin, 2026-11-03): the
    // page leads with the live prediction; the locked-in ladder opens on click.
    fireEvent.click(await screen.findByRole("button", { name: /Frozen record/ }));
    expect(await screen.findByText(/Our 50% level:/)).toBeTruthy();
    // Twice: once in the call, once as the ladder's strike row.
    expect(screen.getAllByText("$101.00").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("$100.00")).toBeTruthy();
    expect(screen.getByText(/2 PM ET/)).toBeTruthy();
  });

  it("says the page is unavailable when the journal cannot be read", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 503, json: async () => ({ detail: "down" }) }) as Response));
    render(<MemoryRouter><Oil /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/Oil forecasts unavailable: down/)).toBeTruthy());
  });
});

describe("/oil 15-minute panel", () => {
  const market = {
    series: "KXWTI15M", label: "WTI", state: "live", close_time: "2026-11-05T05:30:00+00:00", minutes_left: 10,
    open_price: 86.88, price: 87.03, official_open: 86.92, prob_up: 0.71, market: 0.62, yes_bid: 0.6, yes_ask: 0.62,
    best: { strike: 0, side: "yes", prob: 0.71, cost: 0.62, edge_pts: 9, net_pts: 7.4 },
  };

  it("puts both live predictions on one page and leaves Hormuz to its own tab", async () => {
    serve([score()], {}, undefined, { state: "live", markets: [market] });
    render(<MemoryRouter><Oil /></MemoryRouter>);
    expect(await screen.findByRole("region", { name: "Next 15 minutes" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Live next hour" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Chokepoints monitor" })).toBeNull();
  });

  it("stacks the Next hour module underneath Next 15 minutes, not beside it in a split grid", async () => {
    serve([score()], {}, undefined, { state: "live", markets: [market] });
    render(<MemoryRouter><Oil /></MemoryRouter>);
    const fifteen = await screen.findByRole("region", { name: "Next 15 minutes" });
    const hour = await screen.findByRole("region", { name: "Live next hour" });
    // Reading order: the 15-minute module first, the hour module after it.
    expect(fifteen.compareDocumentPosition(hour) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Stacked at every width: neither module sits in a col-span split placement
    // (the old xl 12-column grid squeezed the 15-minute calls into a narrow column).
    expect(fifteen.closest("div[class*='col-span']")).toBeNull();
    expect(hour.closest("div[class*='col-span']")).toBeNull();
  });

  it("states the direction, Kalshi's number and the most to pay", async () => {
    serve([score()], {}, undefined, { state: "live", markets: [market] });
    render(<MemoryRouter><Oil /></MemoryRouter>);
    expect(await screen.findByText(/71% up/)).toBeInTheDocument();
    expect(screen.getByText("Kalshi 62% up")).toBeInTheDocument();
    expect(screen.getByText(/Buy YES below/)).toBeInTheDocument();
    expect(screen.getByText(/\+\$0\.15 since the open/)).toBeInTheDocument();
  });

  it("reads a fall as down, says No trade without an edge, and names a gap instead of inventing a number", async () => {
    serve([score()], {}, undefined, { state: "live", markets: [
      { ...market, price: 86.7, prob_up: 0.3, market: 0.31, best: null },
      { series: "KXNATGAS15M", label: "Natural gas", state: "unavailable", reason: "no window open right now" },
    ] });
    render(<MemoryRouter><Oil /></MemoryRouter>);
    expect(await screen.findByText(/70% down/)).toBeInTheDocument();
    expect(screen.getByText("No trade")).toBeInTheDocument();
    expect(screen.getByText("no window open right now")).toBeInTheDocument();
  });
});

describe("/oil live hero (2026-11-03 Commodities redesign)", () => {
  it("leads with the live ladder: our 50% level big, Kalshi's beside it, LIVE chip on", async () => {
    serve([score()], {}, {
      state: "live", event: "KXWTIH-26NOV0212", minutes_to_close: 40, as_of: "2026-11-02T16:20:00Z",
      live_price: 101.2, our_level: 101.35, market_level: 101.1,
      geo: { stress_score: 2, k: 1.5, partial: false },
      rows: [
        { strike: 100, ours: 0.97, market: 0.95 },
        { strike: 101, ours: 0.62, market: 0.55 },
        { strike: 102, ours: 0.18, market: 0.22 },
      ],
    });
    render(<MemoryRouter><Oil /></MemoryRouter>);
    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(screen.getByText("$101.35")).toBeInTheDocument();
    expect(screen.getByText("$101.10")).toBeInTheDocument();
    expect(screen.getByText(/Hormuz stress 2/)).toBeInTheDocument();
    expect(screen.getByText(/closes in ~40 min/)).toBeInTheDocument();
    // The top leads with the range now (Kevin, 2026-11-04): our 80% range
    // off this ladder starts at the 90% crossing, $100.20, and direction is
    // a No call -- the model centres on the live print.
    expect(screen.getByText(/Our 80% range/)).toBeInTheDocument();
    expect(screen.getByText(/\$100\.20/)).toBeInTheDocument();
    expect(screen.getByText(/Kalshi's 80% range/)).toBeInTheDocument();
    expect(screen.getByText(/No call/)).toBeInTheDocument();
    expect(screen.queryByText(/we lean higher than Kalshi/)).toBeNull();
    expect(screen.getByRole("img", { name: /Chance of settling above each price/ })).toBeInTheDocument();
  });

  const quotedRows = [
    { strike: 100, ours: 0.97, market: 0.95, yes_bid: 0.94, yes_ask: 0.96 },
    { strike: 101, ours: 0.62, market: 0.55, yes_bid: 0.54, yes_ask: 0.56 },
    { strike: 102, ours: 0.18, market: 0.22, yes_bid: 0.2, yes_ask: 0.24 },
  ];
  const base = {
    state: "live", event: "KXWTIH-26NOV0212", minutes_to_close: 40, as_of: "2026-11-02T16:20:00Z",
    live_price: 101.2, our_level: 101.35, market_level: 101.1, rows: quotedRows,
  };

  it("names the best strike big, as a buy-below limit, and marks it on the board", async () => {
    serve([score()], {}, { ...base, best: { strike: 101, side: "yes", prob: 0.62, cost: 0.56, edge_pts: 6, net_pts: 4.3 }, price_age_minutes: 0 });
    render(<MemoryRouter><Oil /></MemoryRouter>);
    expect(await screen.findByText(/▲ Above \$101\.00/)).toBeInTheDocument();
    // Buy-below for a 62% model price under the quadratic fee is 60.3c.
    expect(screen.getByText(/Buy YES below 60\.3c/)).toBeInTheDocument();
    expect(screen.getByText(/now 56c · model says 62% · \+4\.3 pts after fee at the ask/)).toBeInTheDocument();
    expect(screen.getByText("best")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "NO costs" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Buy below" })).toBeInTheDocument();
    expect(screen.getByText("46c")).toBeInTheDocument(); // the 101 strike's NO: one minus the 54c bid
    expect(screen.queryByText(/old, and Kalshi settles/)).toBeNull();
  });

  it("can favor the below side", async () => {
    serve([score()], {}, { ...base, best: { strike: 102, side: "no", prob: 0.82, cost: 0.8, edge_pts: 5, net_pts: 3.9 } });
    render(<MemoryRouter><Oil /></MemoryRouter>);
    expect(await screen.findByText(/▼ Below \$102\.00/)).toBeInTheDocument();
    expect(screen.getByText(/Buy NO below 80\.9c/)).toBeInTheDocument();
    expect(screen.getByText(/now 80c/)).toBeInTheDocument();
  });

  it("says No trade when no strike qualifies, and how close the nearest came", async () => {
    serve([score()], {}, { ...base, best: null, closest: { strike: 101, side: "yes", prob: 0.58, cost: 0.56, edge_pts: 2, net_pts: 0.3 } });
    render(<MemoryRouter><Oil /></MemoryRouter>);
    expect(await screen.findByText("No trade")).toBeInTheDocument();
    expect(screen.getByText(/Closest: Above \$101\.00, YES at 56c, model 58%/)).toBeInTheDocument();
  });

  it("names the live perp as a stand-in for the feed Kalshi settles on", async () => {
    serve([score()], {}, { ...base, best: null, closest: null, price_source: "hyperliquid", price_age_minutes: 0 });
    render(<MemoryRouter><Oil /></MemoryRouter>);
    expect(await screen.findByText(/Hyperliquid oil perp, live but not what Kalshi settles on/)).toBeInTheDocument();
  });

  it("warns that a stale price can be the whole gap", async () => {
    serve([score()], {}, { ...base, best: null, closest: null, price_age_minutes: 11 });
    render(<MemoryRouter><Oil /></MemoryRouter>);
    expect(await screen.findByText(/WTI price is 11 min old/)).toBeInTheDocument();
  });

  it("shows no price for a side Kalshi isn't quoting", async () => {
    serve([score()], {}, { ...base, rows: [{ strike: 101, ours: 0.6, market: null, yes_bid: null, yes_ask: null }] });
    render(<MemoryRouter><Oil /></MemoryRouter>);
    expect(await screen.findByText(/All 1 strikes/)).toBeInTheDocument();
    const row = screen.getByText(/\$101\.00/).closest("tr")!;
    expect(row.textContent).toContain("60%");
    expect((row.textContent!.match(/—/g) ?? []).length).toBe(3); // YES, NO and edge: unknown, never zero
  });
});


describe("/oil live hero", () => {
  const livePayload = () => {
    const rows = [];
    for (let i = 0; i <= 30; i++) {
      const strike = 94.19 + i * 0.1;
      const ours = 1 / (1 + Math.exp((strike - 95.79) / 0.28));
      const quoted = strike >= 95.39 && strike <= 96.19;
      rows.push({ strike: Math.round(strike * 100) / 100, ours: Math.round(ours * 10000) / 10000,
                  market: quoted ? Math.round((1 / (1 + Math.exp((strike - 95.69) / 0.3))) * 10000) / 10000 : null });
    }
    return {
      state: "live", event: "KXWTIH-26NOV0312", minutes_to_close: 40,
      as_of: "2026-11-03T16:00:00+00:00", live_price: 95.8, price_at: "2026-11-03T15:47:00+00:00",
      price_age_minutes: 13, our_level: 95.79, market_level: 95.69, geo: null, best: null, rows,
    };
  };

  it("keeps clustered level labels in separate lanes and stamps the print's age", async () => {
    serve([score()], {}, livePayload());
    const { container } = render(<MemoryRouter><Oil /></MemoryRouter>);
    const us = await screen.findByText("Us $95.79");
    const kalshi = screen.getByText("Kalshi $95.69");
    const wti = screen.getByText("WTI $95.80");
    // The three levels sit within 11 cents: on one line their labels would
    // sit on top of each other, so the lanes must differ.
    const ys = new Set([us.getAttribute("y"), kalshi.getAttribute("y"), wti.getAttribute("y")]);
    expect(ys.size).toBe(3);
    expect(screen.getByText(/print 13 min old/)).toBeTruthy();
    expect(container.querySelectorAll("circle").length).toBeGreaterThan(0); // Kalshi's quoted points
  });

  it("explains the graph behind its toggle", async () => {
    serve([score()], {}, livePayload());
    render(<MemoryRouter><Oil /></MemoryRouter>);
    await screen.findByText("Us $95.79");
    fireEvent.click(screen.getByRole("button", { name: /How to read this graph/ }));
    expect(screen.getByText(/settles above that price/)).toBeTruthy();
    expect(screen.getByText(/white line is the live WTI print/)).toBeTruthy();
  });
});

describe("strike board", () => {
  it("keeps the 50% strike in view when the pick sits far from it", async () => {
    const rows = Array.from({ length: 40 }, (_, i) => ({
      strike: 90 + i * 0.1, ours: 0.9 - i * 0.02, market: null, yes_bid: 0.4, yes_ask: 0.42 }));
    render(<StrikeBoard rows={rows} best={{ strike: 90.1, side: "yes", prob: 0.88, cost: 0.42, edge_pts: 46, net_pts: 44 }} ourLevel={92} />);
    expect(screen.getAllByRole("row").length).toBe(10);
    expect(screen.getByText(/\$92\.00/)).toBeInTheDocument();
  });

  it("keeps the pick on screen when many strikes qualify", async () => {
    const rows = Array.from({ length: 40 }, (_, i) => ({
      strike: 90 + i * 0.1, ours: 0.9 - i * 0.02, market: null, yes_bid: 0.4, yes_ask: 0.42 }));
    render(<StrikeBoard rows={rows} best={{ strike: 90.1, side: "yes", prob: 0.88, cost: 0.42, edge_pts: 46, net_pts: 44 }} ourLevel={92} />);
    expect(screen.getByText("best")).toBeInTheDocument();
    expect(screen.getAllByRole("row").length).toBe(10); // the header and 9 strikes (one screen, 2026-11-06)
  });
});

describe("best strike record", () => {
  it("shows a losing record beside the pick in plain terms", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      frozen: 3, settled: 2, hits: 1, hit_rate: 0.5, net_per_contract: -0.04,
      backtest: { events: 40, picks: 30, hits: 10, avg_model: 0.585, avg_cost: 0.415, net_per_contract: -0.0967 },
    }), { status: 200 })));
    render(<TradeVerdict best={null} closest={null} priceAge={null} />);
    expect(await screen.findByText(/This signal hasn't made money so far/)).toBeInTheDocument();
    expect(screen.getByText(/−9\.7c per contract after fees/)).toBeInTheDocument();
    expect(screen.getByText(/−4c per contract/)).toBeInTheDocument();
  });
});
