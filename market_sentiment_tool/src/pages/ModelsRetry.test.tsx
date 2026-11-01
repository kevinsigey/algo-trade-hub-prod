import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import Models from "@/pages/Models";

afterEach(() => vi.unstubAllGlobals());

describe("Models retry", () => {
  it("shows Retry after a failure and recovers", async () => {
    let sbCalls = 0;
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (String(url).includes("/api/scoreboard")) {
        sbCalls += 1;
        if (sbCalls === 1) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "boom" }) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ catalogue: { entries: [], engines_not_measured: 0 }, promotion_lookup_failed: false }) });
      }
      // SportsRecord fetch
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ sports: [] }) });
    }));
    render(<Models />);
    await waitFor(() => expect(screen.queryByText(/boom/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(screen.queryByText(/Models unavailable/)).toBeNull());
  });
});
