import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import StrategyHqStrip from "@/components/StrategyHqStrip";
import type { HealthReport } from "@/lib/health";
import type { ScoreboardResponse } from "@/lib/scoreboard";

const IDEAS = { tested: 9, passed: 1, failed: 8, not_enough_data: 0, published: 1 };

const SCOREBOARD: ScoreboardResponse = {
  as_of: "2026-11-01T12:00:00Z",
  runs_read: 5,
  rows: [],
  engines: 3,
  promotion_lookup_failed: false,
  rows_total: 3,
  rows_behind_market: 3,
  rows_ahead_of_market: 0,
  rows_level_with_market: 0,
  rows_not_comparable: 0,
  any_beats_market: false,
  headline: "No engine beats the market on Brier.",
  headline_kind: "behind",
  caveat: null,
};

function healthReport(status: HealthReport["status"]): HealthReport {
  return {
    status,
    generated_at: "2026-11-01T12:00:00Z",
    frozen_window_hours: 24,
    stale_after_hours: 6,
    timers: {
      scan: { last_success: "2026-11-01T11:00:00Z", age_seconds: 3600, status: "ok", tracked: true },
      settle: {
        last_success: "2026-10-31T11:00:00Z",
        age_seconds: 90000,
        status: status === "degraded" ? "stale" : "ok",
        tracked: true,
      },
      journal: { last_success: null, age_seconds: null, status: "not_tracked", tracked: false },
    },
    untracked_timers: ["journal"],
    tracked_timer_count: 2,
    families: {
      cpi: { frozen_24h: 3, cadence: "monthly", expected_daily: false, silent: status === "degraded" },
    },
    orderbook: { newest_file_age_seconds: 300, status: "ok" },
    problems: status === "degraded" ? ["settle is stale"] : [],
  };
}

function serve(status: HealthReport["status"]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes("/api/ideas/summary")
        ? IDEAS
        : url.includes("/api/scoreboard")
          ? SCOREBOARD
          : url.includes("/api/health")
            ? { report: healthReport(status) }
            : {};
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Strategy HQ strip", () => {
  it("shows the ideas record, the server's scoreboard headline, and Degraded health", async () => {
    serve("degraded");
    render(
      <MemoryRouter>
        <StrategyHqStrip />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Strategy HQ")).toBeInTheDocument();
    expect(screen.getByText(/9 tested · 1 passed · 8 failed · 0 not enough data/)).toBeInTheDocument();
    expect(screen.getByText("1 published on the public record")).toBeInTheDocument();
    expect(screen.getByText("No engine beats the market on Brier.")).toBeInTheDocument();
    expect(screen.getByText("Health: Degraded")).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 tracked timers fresh · 1 problem · 1 silent family/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open Health/ })).toHaveAttribute("href", "/health");
  });

  it("shows Healthy plainly when the Health report is ok", async () => {
    serve("ok");
    render(
      <MemoryRouter>
        <StrategyHqStrip />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Health: Healthy")).toBeInTheDocument();
    expect(screen.queryByText("Health: Degraded")).not.toBeInTheDocument();
    expect(screen.getByText(/2 of 2 tracked timers fresh · 0 problems · 0 silent families/)).toBeInTheDocument();
  });
});
