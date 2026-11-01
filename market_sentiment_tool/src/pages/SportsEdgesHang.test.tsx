import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import SportsEdges from "@/pages/SportsEdges";

const ROW = {
  market_id: "M", title: "Recovered game", our_prob: 0.7, market_prob: 0.5, edge_pct: 0.2,
  market_url: "https://k", source_url: "https://p", sport: "nfl", kind: "winner", side: "yes",
  entry_price: 0.4, maker: true, home: "A", away: "B", start_utc: "2026-10-03T16:00:00+00:00",
  game_id: "g1", tier: "flagged", candidate: true, reject_reasons: [], review: null,
  engine: "sports_nfl", engine_version: null, gate_status: "SHADOW",
};

afterEach(() => vi.unstubAllGlobals());

describe("sports board, paged fetch", () => {
  it("does not skip rows when the API caps the page below 200", async () => {
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(() => {
      calls += 1;
      const offset = (calls - 1) * 100;
      const remaining = 402 - offset;
      const size = Math.min(100, remaining);
      const edges = Array.from({ length: Math.max(0, size) }, (_, i) => ({ ...ROW, market_id: `m${offset + i}` }));
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ edges, total: 402, limit: 100, offset }) });
    }));
    render(<SportsEdges />);
    await waitFor(() => expect(screen.queryByText(/Loading sports picks/)).toBeNull(), { timeout: 5000 });
    // 402 rows fetched across 5 pages, not stuck.
    expect(calls).toBe(5);
  });

  it("shows an error and Retry on failure", async () => {
    let call = 0;
    vi.stubGlobal("fetch", vi.fn(() => {
      call += 1;
      if (call === 1) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "boom" }) });
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ edges: [ROW], total: 1, limit: 100, offset: 0 }) });
    }));
    render(<SportsEdges />);
    await waitFor(() => expect(screen.queryByText(/boom/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /retry|try again/i }));
    await waitFor(() => expect(screen.queryByText(/Recovered game/)).toBeTruthy());
  });
});
