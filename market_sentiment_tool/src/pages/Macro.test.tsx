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
    vi.mocked(api.getJson).mockResolvedValue({ as_of: "2026-11-01", quick: [], cards: [CARD] });
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

describe("Macro jobs card U3 fold", () => {
  it("renders the unemployment block inside the jobs card when present", async () => {
    const jobs = {
      key: "jobs", title: "Jobs nowcast", predicts: "Next nonfarm payrolls print", detail_href: "/jobs",
      display_only: false,
      call: { label: "Nov 2026 payrolls", ours: 165.0, market: 158.0, last_actual: 150.0, as_of: "2026-12-03" },
      record: { source: "scoreboard", n_settled: 40, brier_ours: 0.18, brier_market: 0.17,
        gate_status: "SHADOW", promotion_status: "SHADOW", diagnostics_flags: [] },
      trail: [], trail_kind: "value", next_release: "2026-12-04",
      u3: {
        call: { label: "KXU3-26NOV-T4.5", ours: 0.31, market: 0.36, last_actual: null, as_of: "2026-11-30T13:00:00Z" },
        record: { source: "journal", n_settled: 3, brier_ours: 0.2, brier_market: 0.18,
          gate_status: null, promotion_status: null, diagnostics_flags: [] },
      },
    } as const;
    vi.mocked(api.getJson).mockResolvedValue({ as_of: "2026-11-01", quick: [], cards: [jobs] });
    render(<MemoryRouter><Macro /></MemoryRouter>);
    expect(await screen.findByText(/Unemployment \(KXU3\)/)).toBeInTheDocument();
    expect(screen.getByText(/KXU3-26NOV-T4\.5/)).toBeInTheDocument();
    expect(screen.getByText(/31%/)).toBeInTheDocument();
  });
});

describe("Macro quick strip", () => {
  it("renders display-only CPI as a one-line strip item, not a card", async () => {
    const quick = [{
      key: "cpi", title: "CPI", detail_href: "/cpi", display_only: true,
      note: "Cleveland Fed nowcast, wrapped -- display only",
      call: { label: "KXCPI-26NOV", ours: 0.62, market: 0.58, last_actual: null, as_of: "2026-10-30T13:00:00Z" },
      record: null,
    }];
    vi.mocked(api.getJson).mockResolvedValue({ as_of: "2026-11-01", quick, cards: [] });
    render(<MemoryRouter><Macro /></MemoryRouter>);
    expect(await screen.findByText("Quick")).toBeInTheDocument();
    expect(screen.getByText(/Cleveland Fed nowcast/)).toBeInTheDocument();
  });
});
