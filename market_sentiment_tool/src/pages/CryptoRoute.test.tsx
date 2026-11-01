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

const BOARD = {
  generated_at: "2026-11-01T21:00:00Z",
  note: "Kalshi market data, not a prediction.",
  spots: { BTC: 77844.4, ETH: 2263.05 },
  hourly: {
    BTC: { closes_at: "2026-11-01T22:00:00Z", shape: "step", bracket: [77749.99, 77999.99], strikes_quoted: 80 },
    ETH: { closes_at: "2026-11-01T22:00:00Z", shape: "coin_flip", coin_flip_strike: 2262.0, implied_pct: 50.5, one_sided: false, strikes_quoted: 40 },
  },
  quarter: {
    BTC: { closes_at: "2026-11-01T21:15:00Z", floor: 77843.02, implied_pct: 47.5, one_sided: false },
    ETH: null,
  },
};

const VERDICT = {
  record: "sniper_closed_record",
  graded_on: "2026-11-01",
  worker: { first_row: "x", last_row: "y", stopped: "2026-06-02", venue: "Kalshi demo API" },
  population: { archived_rows: 84197, by_status: {}, grading_population: 56498, considered: 18602, dead_zone: 37896, dead_zone_share: 0.6707, graded: 18602 },
  overall: { count: 18602, hit_rate: 0.548, virtual_pnl_pct: 526.1, brier_score: 0.2513 },
  by_asset: {
    BTC: { count: 17547, hit_rate: 0.5443, virtual_pnl_pct: 612.0, brier_score: 0.2519 },
    ETH: { count: 1055, hit_rate: 0.6085, virtual_pnl_pct: -85.9, brier_score: 0.2407 },
  },
  buckets: {},
  price_source: "BTC: coinbase, ETH: coinbase",
  method: "Graded once with the hub's existing shadow evaluator.",
};

function stubFetch() {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const body = String(url).includes("/api/crypto/board") ? BOARD
      : String(url).includes("/api/crypto/sniper-verdict") ? VERDICT
      : String(url).includes("/api/onchain") ? { chains: [] }
      : {};
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }));
}

async function renderAt(path: string) {
  window.history.pushState({}, "", path);
  const { act } = await import("@testing-library/react");
  await act(async () => { render(<App />); });
}

describe("crypto route", () => {
  it("renders the research desk at /crypto with the board and the closed record", async () => {
    stubFetch();
    await renderAt("/crypto");
    await waitFor(() => expect(screen.getByRole("heading", { name: /Crypto research/i })).toBeInTheDocument());
    expect(await screen.findByText(/18,602/)).toBeInTheDocument();
    expect(screen.getByText(/The book quotes a step, not a curve/)).toBeInTheDocument();
    expect(screen.getByText(/Venue lead-lag/)).toBeInTheDocument();
  });

  it("redirects /shadow to the research desk", async () => {
    stubFetch();
    await renderAt("/shadow");
    await waitFor(() => expect(screen.getByRole("heading", { name: /Crypto research/i })).toBeInTheDocument());
    expect(window.location.pathname).toBe("/crypto");
  });
});
