import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import SportsRecord from "@/components/SportsRecord";

const SPORTS_BODY = {
  as_of: "2026-10-27T00:00:00+00:00",
  sports: [{ sport: "nfl", status: "ok", rows: [{ sport: "nfl", market: "moneyline", label: "Winner", n: 94, hit_rate: 0.585, n_pre: 61, hit_rate_pre: 0.59, vs_market: null, note: null }] }],
};

afterEach(() => vi.unstubAllGlobals());

describe("SportsRecord retry", () => {
  it("shows Retry after a failure and recovers", async () => {
    let sportsCalls = 0;
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (String(url).includes("/api/sports-record")) {
        sportsCalls += 1;
        if (sportsCalls === 1) return Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: "boom" }) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(SPORTS_BODY) });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ forecasters: [] }) });
    }));
    render(<SportsRecord />);
    await waitFor(() => expect(screen.queryByText(/Sports records unavailable/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(screen.queryByText("59%")).toBeTruthy());
  });
});
