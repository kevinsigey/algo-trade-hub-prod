import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import App from "@/App";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

afterEach(() => vi.unstubAllGlobals());

describe("crypto route", () => {
  it("renders the crypto shadow timeline at /crypto", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ domain: "crypto", hours: 24, generated_at: "x", thresholds: {}, summary: { evaluated_count: 0, considered_count: 0, dead_zone_count: 0, hit_rate: null, brier_score: null, virtual_pnl_pct: 0 }, freshness: {}, series: [] }) })));
    window.history.pushState({}, "", "/crypto");
    await (async () => {
      const { act } = await import("@testing-library/react");
      await act(async () => { render(<App />); });
    })();
    await waitFor(() => expect(screen.getByRole("heading", { name: /Crypto Shadow Timeline/i })).toBeInTheDocument());
  });
});
