import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

import SportsRecord from "@/components/SportsRecord";

const SPORTS_BODY = {
  as_of: "2026-10-27T00:00:00+00:00",
  sports: [
    {
      sport: "nfl",
      status: "ok",
      rows: [
        { sport: "nfl", market: "moneyline", label: "Winner", n: 94, hit_rate: 0.5851063829787234, n_pre: 61, hit_rate_pre: 0.5901639344262295, vs_market: null, note: null },
        { sport: "nfl", market: "spread", label: "Spread", n: 94, hit_rate: 0.5106382978723404, n_pre: 61, hit_rate_pre: 0.5081967213114754, vs_market: null, note: null },
      ],
    },
    {
      sport: "cfb",
      status: "ok",
      rows: [
        { sport: "cfb", market: "moneyline", label: "Winner", n: 517, hit_rate: 0.7562862669245648, n_pre: 256, hit_rate_pre: 0.6796875, vs_market: null, note: null },
      ],
    },
    {
      sport: "nba",
      status: "ok",
      rows: [
        { sport: "nba", market: "h2h", label: "Winner", n: 43, hit_rate: 0.535, n_pre: 42, hit_rate_pre: 0.548, vs_market: null, note: null },
      ],
    },
    {
      sport: "pl",
      status: "ok",
      rows: [
        { sport: "pl", market: "match_result", label: "Result", n: 70, hit_rate: 0.5142857142857142, n_pre: 20, hit_rate_pre: 0.5, vs_market: null, note: null },
      ],
    },
    {
      sport: "f1",
      status: "ok",
      rows: [
        { sport: "f1", market: "all", label: "All markets", n: 2420, hit_rate: null, n_pre: 1364, hit_rate_pre: null, vs_market: null, note: "F1 scores probabilities (Brier), not picks: see the F1 site" },
      ],
    },
  ],
};

const JOURNAL_BODY = {
  as_of: "2026-10-27T00:00:00+00:00",
  forecasters: [
    { forecaster: "sports_nfl", forecaster_version: "feed-v1", cadence: "daily", baseline: "market", n_targets: 50, n_settled: 50, brier: 0.2, brier_baseline: 0.2, bss: 0, reliability: [], murphy: {}, calibration_ready: false, gate_status: "SHADOW", gate_reasons: [], computed_at: "x", gap: -0.01, gap_se: 0.004 },
    { forecaster: "sports_cfb", forecaster_version: "feed-v1", cadence: "daily", baseline: "market", n_targets: 50, n_settled: 50, brier: 0.2, brier_baseline: 0.2, bss: 0, reliability: [], murphy: {}, calibration_ready: false, gate_status: "SHADOW", gate_reasons: [], computed_at: "x", gap: 0.05, gap_se: 0.01 },
  ],
  headline: { forecasters: 2, calibrated: 0, frozen_calibrated: 0, settled_calibrated: 0, promoted: 0, market_skill: null },
};

function stub(sportsBody: unknown = SPORTS_BODY, journalBody: unknown = JOURNAL_BODY, ok = true) {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const body = String(url).includes("/api/journal") ? journalBody : sportsBody;
    return Promise.resolve({ ok, status: ok ? 200 : 503, json: () => Promise.resolve(body) });
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("SportsRecord", () => {
  it("renders percent and n from the fixture rows", async () => {
    stub();
    render(<SportsRecord />);
    expect(await screen.findByText("59%")).toBeInTheDocument();
    expect(screen.getAllByText(/n 94/).length).toBeGreaterThan(0);
  });

  it("shows too-early chip under 100 and not at 100+", async () => {
    stub();
    render(<SportsRecord />);
    await screen.findByText("59%");
    expect(screen.getAllByText("too early").length).toBeGreaterThan(0);
    const cfbCard = screen.getByText("College football").closest(".rounded-lg") as unknown as HTMLElement;
    expect(within(cfbCard).queryByText("too early")).toBeNull();
  });

  it("renders unavailable card", async () => {
    const body = { ...SPORTS_BODY, sports: [{ sport: "nba", status: "unavailable", rows: [] }] };
    stub(body);
    render(<SportsRecord />);
    expect(await screen.findByText("Unavailable right now")).toBeInTheDocument();
  });

  it("F1 shows no percent but shows the note", async () => {
    stub();
    render(<SportsRecord />);
    await screen.findByText("All markets");
    const f1Card = screen.getByText("F1").closest(".rounded-lg") as unknown as HTMLElement;
    expect(within(f1Card).queryByText(/\d+%/)).toBeNull();
    expect(screen.getByText(/F1 scores probabilities/)).toBeInTheDocument();
  });

  it("nfl card shows the Kalshi line and nba shows No market comparison yet", async () => {
    stub();
    render(<SportsRecord />);
    await screen.findByText("59%");
    expect(screen.getAllByText(/vs Kalshi price:/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("No market comparison yet").length).toBeGreaterThan(0);
  });
});

describe("SportsRecord Kalshi comparison per row", () => {
  it("grades each NFL row from its own journal scorecard, and says so when one is missing", async () => {
    stub();
    render(<SportsRecord />);
    await screen.findByText("59%");
    const nflCard = screen.getByText("NFL").closest(".rounded-lg") as unknown as HTMLElement;
    const lines = within(nflCard).getAllByText(/vs Kalshi price:/).map((e) => e.textContent);
    expect(lines).toHaveLength(2); // Winner and Spread rows; the fixture journal has only the winner scorecard
    expect(lines.filter((l) => l?.includes("not scored yet"))).toHaveLength(1);
    expect(lines.filter((l) => /\(.*(Ahead|Behind|No signal)\)/.test(l ?? ""))).toHaveLength(1);
  });

  it("never shows a Kalshi number for NBA, Premier League or F1", async () => {
    stub();
    render(<SportsRecord />);
    await screen.findByText("59%");
    for (const title of ["NBA", "Premier League", "F1"]) {
      const card = screen.getByText(title).closest(".rounded-lg") as unknown as HTMLElement;
      expect(within(card).queryByText(/vs Kalshi price:/)).toBeNull();
      expect(within(card).getByText("No market comparison yet")).toBeInTheDocument();
    }
  });

  it("a null count shows a dash and no too-early chip", async () => {
    const body = { ...SPORTS_BODY, sports: [{ sport: "nba", status: "ok", rows: [
      { sport: "nba", market: "h2h", label: "Winner", n: null, hit_rate: 0.5, n_pre: null, hit_rate_pre: null, vs_market: null, note: null },
    ] }] };
    stub(body);
    render(<SportsRecord />);
    expect(await screen.findByText("50%")).toBeInTheDocument();
    expect(screen.getByText("n —")).toBeInTheDocument();
    expect(screen.queryByText("too early")).toBeNull();
  });
});

describe("SportsRecord loading and labels", () => {
  it("shows the records without waiting for a journal request that never answers", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) =>
      String(url).includes("/api/journal")
        ? new Promise(() => {}) // never resolves
        : Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(SPORTS_BODY) })));
    render(<SportsRecord />);
    expect(await screen.findByText("59%")).toBeInTheDocument();
  });

  it("names each sport's own pre-event moment", async () => {
    stub();
    render(<SportsRecord />);
    await screen.findByText("59%");
    const nba = screen.getByText("NBA").closest(".rounded-lg") as unknown as HTMLElement;
    expect(within(nba).getByText(/before tip-off/)).toBeInTheDocument();
    const f1 = screen.getByText("F1").closest(".rounded-lg") as unknown as HTMLElement;
    expect(within(f1).getByText(/before the session/)).toBeInTheDocument();
    const nfl = screen.getByText("NFL").closest(".rounded-lg") as unknown as HTMLElement;
    expect(within(nfl).getAllByText(/before kickoff/).length).toBeGreaterThan(0);
  });
});
