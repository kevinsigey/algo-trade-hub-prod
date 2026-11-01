import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Macro from "@/pages/Macro";
import { recordVerdict } from "@/lib/macro";
import * as api from "@/lib/getJson";

vi.mock("@/lib/getJson", () => ({ getJson: vi.fn() }));

const CARD = {
  key: "cpi", title: "CPI", predicts: "Next CPI release (headline)", detail_href: "/cpi",
  display_only: true,
  call: { label: "KXCPI-26NOV", ours: 0.62, market: 0.58, last_actual: null, as_of: "2026-10-30T13:00:00Z" },
  record: { source: "scoreboard", n_settled: 12, brier_ours: 0.21, brier_market: 0.19,
    gate_status: "SHADOW", promotion_status: "SHADOW", diagnostics_flags: [] },
  trail: [{ label: "KXCPI-26OCT", ours: 0.4, market: 0.44, actual: 0 }],
  trail_kind: "probability", next_release: null,
} as const;

describe("Macro page", () => {
  beforeEach(() => {
    vi.mocked(api.getJson).mockResolvedValue({ as_of: "2026-11-01", cards: [CARD] });
  });

  it("leads with the call, carries the display-only honesty line, and demotes at small samples", async () => {
    render(<MemoryRouter><Macro /></MemoryRouter>);
    expect(await screen.findByText("CPI")).toBeInTheDocument();
    expect(screen.getByText(/not a board of opportunities/)).toBeInTheDocument();
    expect(screen.getByText(/Too early to say — 12 settled/)).toBeInTheDocument();
    expect(screen.getByText(/62%/)).toBeInTheDocument();
    expect(screen.getByText(/resolved NO/)).toBeInTheDocument();
  });
});

describe("recordVerdict", () => {
  it("names a leader only at or above the floor", () => {
    const rec = { source: "journal" as const, n_settled: 40, brier_ours: 0.18, brier_market: 0.2,
      gate_status: null, promotion_status: null, diagnostics_flags: [] };
    expect(recordVerdict(rec)).toMatch(/Ahead of the market/);
    expect(recordVerdict({ ...rec, n_settled: 4 })).toMatch(/Too early/);
    expect(recordVerdict(null)).toBe("Record unavailable");
  });
});
