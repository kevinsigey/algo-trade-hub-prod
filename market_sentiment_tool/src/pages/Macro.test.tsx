import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Macro from "@/pages/Macro";
import { recordVerdict } from "@/lib/macro";
import * as api from "@/lib/getJson";

vi.mock("@/lib/getJson", () => ({ getJson: vi.fn() }));
vi.mock("@/components/RequireAdmin", () => ({ sessionToken: async () => null }));
vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => [] })));
/** /api/macro answers with the board; the CPI card's /api/journal read gets an empty journal. */
const board = (payload: unknown) =>
  vi.mocked(api.getJson).mockImplementation((async (url: string) =>
    url.includes("journal") ? { forecasters: [] } : payload) as never);

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
    board({ as_of: "2026-11-01", quick: [], cards: [CARD] });
  });

  it("leads with the call, carries the display-only honesty line, and demotes at small samples", async () => {
    render(<MemoryRouter><Macro /></MemoryRouter>);
    expect((await screen.findAllByText("CPI")).length).toBeGreaterThan(0);
    expect(screen.getByText(/not a board of opportunities/)).toBeInTheDocument();
    expect(screen.getByText(/Too early to say — 12 settled/)).toBeInTheDocument();
    expect(screen.getByText(/62%/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Recent calls: our probability/ })).toBeInTheDocument();
  });

  it("draws the jobs trail as grouped bars and the U3 call as a split bar", async () => {
    const jobs = {
      key: "jobs", title: "Jobs nowcast", predicts: "Next nonfarm payrolls print", detail_href: "/jobs",
      display_only: false,
      call: { label: "Nov 2026 payrolls", ours: 165.0, market: 158.0, last_actual: 150.0, as_of: "2026-12-03" },
      record: { source: "scoreboard", n_settled: 40, brier_ours: 0.18, brier_market: 0.17,
        gate_status: "SHADOW", promotion_status: "SHADOW", diagnostics_flags: [] },
      trail: [
        { label: "Sep 2026", ours: 120.0, market: 118.0, actual: 119.0 },
        { label: "Oct 2026", ours: 150.0, market: 140.0, actual: 143.0 },
      ],
      trail_kind: "value", next_release: "2026-12-04",
      u3: {
        call: { label: "KXU3-26NOV-T4.5", ours: 0.31, market: 0.36, last_actual: null, as_of: "2026-11-30T13:00:00Z" },
        record: null,
      },
    } as const;
    board({ as_of: "2026-11-01", quick: [], cards: [jobs] });
    render(<MemoryRouter><Macro /></MemoryRouter>);
    expect(await screen.findByRole("img", { name: /Recent prints: our nowcast/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Ours 31% versus Kalshi 36%/ })).toBeInTheDocument();
    expect(screen.getByText("Sep 2026")).toBeInTheDocument();
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
    board({ as_of: "2026-11-01", quick: [], cards: [jobs] });
    render(<MemoryRouter><Macro /></MemoryRouter>);
    expect(await screen.findByText(/Unemployment \(KXU3\)/)).toBeInTheDocument();
    expect(screen.getByText(/KXU3-26NOV-T4\.5/)).toBeInTheDocument();
    expect(screen.getAllByText(/31%/).length).toBeGreaterThan(0);
  });
});

describe("Macro card grid (2026-11-03 redesign)", () => {
  it("renders Jobs, CPI and PPI as co-equal cards and no quick strip", async () => {
    const jobs = { ...CARD, key: "jobs", title: "Jobs nowcast", detail_href: "/jobs", display_only: false,
      trail_kind: "value", trail: [] } as const;
    const ppi = { ...CARD, key: "ppi", title: "PPI", detail_href: "/journal", display_only: false,
      record: { ...CARD.record, source: "journal" } } as const;
    board({ as_of: "2026-11-01", quick: [], cards: [jobs, CARD, ppi] });
    render(<MemoryRouter><Macro /></MemoryRouter>);
    // Jobs nowcast and CPI each appear twice: the summary DashCard above and the engine card below.
    expect(await screen.findByText("PPI")).toBeInTheDocument();
    expect(screen.getAllByText("Jobs nowcast")).toHaveLength(2);
    expect(screen.getAllByText("CPI")).toHaveLength(2);
    expect(screen.getByText("PPI")).toBeInTheDocument();
    expect(screen.queryByText("Quick")).not.toBeInTheDocument();
  });
});

describe("Macro Jobs and CPI cards", () => {
  it("open the jobs and CPI pages in a full view", async () => {
    board({ as_of: "2026-11-01", quick: [], cards: [] });
    render(<MemoryRouter><Macro /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Open Jobs nowcast" }));
    expect(await screen.findByRole("heading", { name: "Jobs nowcast vs Kalshi", level: 1 })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(await screen.findByRole("button", { name: "Open CPI" }));
    expect(await screen.findByRole("heading", { name: "Inflation (CPI)", level: 1 })).toBeInTheDocument();
  });
});
