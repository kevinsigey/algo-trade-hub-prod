import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import Oil from "@/pages/Oil";
import type { JournalFeed, JournalResponse, JournalScore } from "@/lib/journal";
import { copyWords } from "@/test/copyWords";

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "oil_wti", forecaster_version: "wti-v1", cadence: "daily", baseline: "market", n_targets: 0,
    n_settled: 0, brier: null, brier_baseline: null, bss: null, reliability: [], murphy: {}, calibration_ready: false,
    gate_status: "SHADOW", gate_reasons: [], computed_at: "2026-10-01T13:00:00+00:00", ...over,
  };
}

function serve(forecasters: JournalScore[], feed: Partial<JournalFeed> = {}, live?: unknown) {
  const journal: JournalResponse = {
    as_of: "x", forecasters, headline: { forecasters: forecasters.length, calibrated: 0, frozen_calibrated: 0, settled_calibrated: 0, promoted: 0, market_skill: null },
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const u = String(url);
    const body = u.includes("/api/oil/hourly-live")
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
    const { container } = render(<Oil />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Commodities — WTI crude oil", level: 1 })).toBeTruthy());
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
    render(<Oil />);
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
    render(<Oil />);
    // Both records are dropdowns now; the hourly rows live under their own.
    await waitFor(() => expect(screen.getByRole("button", { name: /Hourly settlements/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Hourly settlements/ }));
    fireEvent.click(screen.getByRole("button", { name: /Daily settlement/ }));
    expect(screen.getByRole("heading", { name: "WTI crude oil (hourly settlement)" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "WTI crude oil (daily settlement)" })).toBeTruthy();
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
    render(<Oil />);
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
    render(<Oil />);
    await waitFor(() => expect(screen.getByText(/Oil forecasts unavailable: down/)).toBeTruthy());
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
    render(<Oil />);
    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(screen.getByText("$101.35")).toBeInTheDocument();
    expect(screen.getByText("$101.10")).toBeInTheDocument();
    expect(screen.getByText(/Hormuz stress 2/)).toBeInTheDocument();
    expect(screen.getByText(/closes in ~40 min/)).toBeInTheDocument();
    // Direction reads off the chart + banner now, not the strike list: our
    // curve gives ~58% to settling above Kalshi's level on this ladder.
    expect(screen.getByText(/we lean higher than Kalshi/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Chance of settling above each price/ })).toBeInTheDocument();
  });

  it("shows the ITM line stat and tags its ladder row when a pick qualifies", async () => {
    serve([score()], {}, {
      state: "live", event: "KXWTIH-26NOV0212", minutes_to_close: 40, as_of: "2026-11-02T16:20:00Z",
      live_price: 101.2, our_level: 101.35, market_level: 101.1,
      itm: { strike: 101, ours: 0.62, market: 0.55, gap_pts: 7.0, clear_bars: 10 },
      rows: [
        { strike: 100, ours: 0.97, market: 0.95 },
        { strike: 101, ours: 0.62, market: 0.55 },
        { strike: 102, ours: 0.18, market: 0.22 },
      ],
    });
    render(<Oil />);
    expect(await screen.findByText("In-the-money line")).toBeInTheDocument();
    expect(screen.getByText(/clear of the tape 10 min/)).toBeInTheDocument();
    // The ladder itself sits behind the All strikes dropdown now.
    fireEvent.click(screen.getByRole("button", { name: /All strikes/ }));
    expect(screen.getByText("ITM line")).toBeInTheDocument();
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
      price_age_minutes: 13, our_level: 95.79, market_level: 95.69, geo: null, itm: null, rows,
    };
  };

  it("keeps clustered level labels in separate lanes and stamps the print's age", async () => {
    serve([score()], {}, livePayload());
    const { container } = render(<Oil />);
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
    render(<Oil />);
    await screen.findByText("Us $95.79");
    fireEvent.click(screen.getByRole("button", { name: /How to read this graph/ }));
    expect(screen.getByText(/settles above that price/)).toBeTruthy();
    expect(screen.getByText(/white line is the live WTI print/)).toBeTruthy();
  });
});
