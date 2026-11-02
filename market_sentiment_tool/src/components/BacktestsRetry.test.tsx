import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import BacktestsTab from "@/components/BacktestsTab";

afterEach(() => vi.unstubAllGlobals());

describe("Backtests retry", () => {
  it("shows Retry after a failure and recovers", async () => {
    let sbCalls = 0;
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (String(url).includes("/api/scoreboard")) {
        sbCalls += 1;
        if (sbCalls === 1) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "boom" }) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
          // A complete, valid empty board: the recovery path renders the board, not a crash.
          rows: [], runs_read: 0, engines: 0, rows_total: 0, rows_behind_market: 0, rows_ahead_of_market: 0,
          rows_level_with_market: 0, rows_not_comparable: 0, headline: "No backtest runs are recorded yet.",
          headline_kind: "no_runs", caveat: null,
          catalogue: { entries: [], engines_not_measured: 0 }, promotion_lookup_failed: false }) });
      }
      // SportsRecord fetch
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ sports: [] }) });
    }));
    render(<BacktestsTab />);
    await waitFor(() => expect(screen.queryByText(/boom/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(screen.queryByText(/Backtests unavailable/)).toBeNull());
  });
});
