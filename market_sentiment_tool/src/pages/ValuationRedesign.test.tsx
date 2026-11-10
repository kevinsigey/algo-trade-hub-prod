import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Valuation from "@/pages/Valuation";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const AMGN = {
  ticker: "AMGN", tier: "watch", status: "banded", band_basis: "eps",
  price: "460.42", price_as_of: "2026-11-06", peer_group: "biotechnology",
  peer_multiple: "16.49", peer_count: 7, peer_basis: "industry_group",
  anchor: { metric: "eps_gaap", period: "full year 2026", period_key: "FY2026",
    low: 18.34, high: 19.28, mid: 18.81, point_guide: false, consensus: null,
    recorded_at: "2026-11-03T21:05:44+00:00", accession: "0000318154-26-000153" },
  bands: { bear: 272.18, base: 310.17, bull: 317.92 },
  implied_eps: "27.92", implied_revenue: null, gap_range_widths: "9.69",
  guidance_percentile: null, baseline_verdict: "short_zone_strong", stale: false,
  falsifier: "Falsified if AMGN guides FY2026 EPS below 18.34 at the next print.",
  directions: { eps_gaap: { period: "full year 2026", mid: 18.81, prev_mid: 16.36,
    direction: "raised", recorded_at: "2026-11-03T21:05:44+00:00" } },
  fundamentals: {}, inputs: { guidance_records: [] },
  computed_at: "2026-11-09T18:00:00Z",
};

const CVS = {
  ...AMGN, ticker: "CVS", peer_group: "health_care_services",
  peer_multiple: "11.13", peer_count: 5, price: "85.17",
  anchor: { metric: "eps_adjusted", period: "full year 2026", period_key: "FY2026",
    low: 8.2, high: 8.2, mid: 8.2, point_guide: true, consensus: null,
    recorded_at: "2026-11-05T12:00:00+00:00", accession: "0000950103-26-000001" },
  bands: { bear: 82.11, base: 91.23, bull: 91.23 }, implied_eps: "7.65",
  gap_range_widths: null, baseline_verdict: "buy_zone",
  directions: {}, falsifier: "Falsified if CVS guides FY2026 EPS below 8.20.",
};

const LLY = {
  ...AMGN, ticker: "LLY", band_basis: "revenue", peer_group: "pharmaceuticals",
  peer_multiple: "3.81", peer_count: 7, price: "1395.48",
  anchor: { metric: "revenue", period: "full year 2026", period_key: "FY2026",
    low: 91000000000, high: 92000000000, mid: 91500000000, point_guide: false,
    consensus: null, recorded_at: "2026-11-04T12:00:00+00:00",
    accession: "0000059478-26-000101" },
  bands: { bear: 347.35, base: 388.07, bull: 390.19 }, implied_eps: null,
  implied_revenue: "366000000000", gap_range_widths: "237.53",
  baseline_verdict: "short_zone_strong", directions: {},
  falsifier: "Falsified if LLY guides FY2026 revenue below the recorded low end.",
};

const AAPL = {
  ...AMGN, ticker: "AAPL", status: "no_full_year_guide", bands: null,
  anchor: null, baseline_verdict: "no_bands", peer_group: null,
  peer_multiple: null, peer_count: null, peer_basis: null,
  falsifier: "No band to falsify: AAPL has no usable full-year guide on record.",
  directions: {}, inputs: { guidance_records: [] },
};

const SHEETS = [AMGN, CVS, LLY, AAPL];

const SUMMARY = {
  snapshot_id: 3, previous_snapshot_id: 2,
  counts: { banded: 3, buy_zones: 1, strong_short_zones: 2,
    crossings_since_last_snapshot: 1, pending_debates: 2,
    classified_prints: 1 },
  feed_state: "ok",
  // Served order is the backend's: conjunctions pinned first, then
  // crossings, then the snapshot diff (zone changes, guide revisions).
  feed: [
    { kind: "conjunction", ticker: "AMGN", zone: "short_zone_strong",
      classification: "improved", as_of: "2026-11-09",
      screens: ["Buffett quality"],
      bands: { bear: 272.18, base: 310.17, bull: 317.92 }, price: 460.42 },
    { kind: "crossing", ticker: "CVS", book: "main", zone: "buy_zone",
      action: "starter", created_at: "2026-11-10T05:00:00Z",
      bands: { bear: 82.11, base: 91.23, bull: 91.23 }, price: 85.17 },
    { kind: "zone_change", ticker: "CVS", from_zone: "neutral",
      to_zone: "buy_zone", bands: { bear: 82.11, base: 91.23, bull: 91.23 },
      price: 85.17 },
  ],
  classified_names: [{ ticker: "AMGN", classification: "improved",
    as_of: "2026-11-09" }],
  crossings: [{ ticker: "CVS", book: "main", zone: "buy_zone",
    action: "starter", created_at: "2026-11-10T05:00:00Z" }],
  held: { CVS: { books: ["big"], qty: 120, sleeves: ["T8 AI winners core"] } },
  held_positions_unavailable: false,
};

function serve(summary: unknown = SUMMARY, sheets: unknown[] = SHEETS) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/valuation-bands")) {
      return new Response(JSON.stringify({
        snapshot: { id: 3, computed_at: "2026-11-10T03:44:00Z",
          completed_at: "2026-11-10T03:50:00Z", sheet_count: sheets.length,
          banded_count: 3, source: "valuation_run" },
        sheets, summary,
      }), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Guidance re-presentation", () => {
  it("renders the verdict strip stamped with its snapshot, counts reconciling with the board", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const strip = await screen.findByTestId("verdict-strip");
    expect(strip).toHaveTextContent("Snapshot #3");
    expect(strip).toHaveTextContent("Banded");
    expect(within(strip).getByTestId("tile-banded")).toHaveTextContent("3");
    expect(within(strip).getByTestId("tile-buy-zones")).toHaveTextContent("1");
    expect(within(strip).getByTestId("tile-strong-short")).toHaveTextContent("2");
    expect(within(strip).getByTestId("tile-crossings")).toHaveTextContent("1");
    expect(within(strip).getByTestId("tile-pending-debates")).toHaveTextContent("2");
    expect(within(strip).getByTestId("tile-classified")).toHaveTextContent("1");
    // Board reconciliation: exactly the banded names, each exactly once.
    const board = screen.getByTestId("zone-board");
    for (const t of ["AMGN", "CVS", "LLY"]) {
      expect(within(board).getAllByTestId(`board-chip-${t}`)).toHaveLength(1);
    }
    expect(within(board).queryByTestId("board-chip-AAPL")).toBeNull();
  });

  it("pins conjunctions at the top of the attention feed", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const feed = await screen.findByTestId("attention-feed");
    const items = within(feed).getAllByTestId(/feed-item-/);
    expect(items[0]).toHaveTextContent("AMGN");
    expect(items[0]).toHaveTextContent(/conjunction/i);
    expect(items[0]).toHaveTextContent(/improved/);
    expect(feed).toHaveTextContent("CVS");
  });

  it("renders the honest empty state when nothing changed", async () => {
    serve({ ...SUMMARY, feed: [] });
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const feed = await screen.findByTestId("attention-feed");
    expect(feed).toHaveTextContent(/nothing changed/i);
  });

  it("says plainly when there is no previous snapshot to diff against", async () => {
    serve({ ...SUMMARY, feed: [], feed_state: "no_previous_snapshot",
      previous_snapshot_id: null });
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const feed = await screen.findByTestId("attention-feed");
    expect(feed).toHaveTextContent(/no previous completed snapshot/i);
    expect(feed).not.toHaveTextContent(/nothing changed/i);
  });

  it("draws the band track on board chips with the numbers in the title", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const board = await screen.findByTestId("zone-board");
    const chip = within(board).getByTestId("board-chip-AMGN");
    const track = within(chip).getByTestId("band-track-AMGN");
    expect(track).toBeInTheDocument();
    // AMGN's price ($460.42) sits past the bull band ($317.92): the dot
    // clamps at the right end instead of running off the track.
    const dot = track.querySelector("[data-price-dot]");
    expect(dot?.getAttribute("style")).toContain("100%");
    expect(chip.getAttribute("title")).toContain("Bear $272.18");
    expect(chip.getAttribute("title")).toContain("Bull $317.92");
    expect(chip.getAttribute("title")).toContain("Price $460.42");
  });

  it("marks held names on the board and the Held filter shows only them", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const board = await screen.findByTestId("zone-board");
    expect(within(board).getByTestId("board-chip-CVS")).toHaveTextContent(/held/i);
    expect(within(board).getByTestId("board-chip-AMGN")).not.toHaveTextContent(/held/i);
    fireEvent.click(screen.getByTestId("filter-held"));
    expect(within(board).getByTestId("board-chip-CVS")).toBeInTheDocument();
    expect(within(board).queryByTestId("board-chip-AMGN")).toBeNull();
    expect(within(board).queryByTestId("board-chip-LLY")).toBeNull();
  });

  it("filter chips actually filter: strong zones, crossings, classified prints", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const board = await screen.findByTestId("zone-board");
    fireEvent.click(screen.getByTestId("filter-strong-zones"));
    expect(within(board).getByTestId("board-chip-AMGN")).toBeInTheDocument();
    expect(within(board).getByTestId("board-chip-LLY")).toBeInTheDocument();
    expect(within(board).queryByTestId("board-chip-CVS")).toBeNull();
    fireEvent.click(screen.getByTestId("filter-crossings"));
    expect(within(board).getByTestId("board-chip-CVS")).toBeInTheDocument();
    expect(within(board).queryByTestId("board-chip-AMGN")).toBeNull();
    fireEvent.click(screen.getByTestId("filter-classified"));
    expect(within(board).getByTestId("board-chip-AMGN")).toBeInTheDocument();
    expect(within(board).queryByTestId("board-chip-CVS")).toBeNull();
    fireEvent.click(screen.getByTestId("filter-all"));
    expect(within(board).getByTestId("board-chip-CVS")).toBeInTheDocument();
  });

  it("verdict strip tiles click through to their filtered board view", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const board = await screen.findByTestId("zone-board");
    fireEvent.click(screen.getByTestId("tile-crossings"));
    expect(within(board).getByTestId("board-chip-CVS")).toBeInTheDocument();
    expect(within(board).queryByTestId("board-chip-AMGN")).toBeNull();
    fireEvent.click(screen.getByTestId("tile-classified"));
    expect(within(board).getByTestId("board-chip-AMGN")).toBeInTheDocument();
    expect(within(board).queryByTestId("board-chip-CVS")).toBeNull();
    fireEvent.click(screen.getByTestId("tile-banded"));
    expect(within(board).getByTestId("board-chip-CVS")).toBeInTheDocument();
    expect(within(board).getByTestId("board-chip-LLY")).toBeInTheDocument();
  });

  it("keeps the full reference table intact inside a disclosure, rows == served banded sheets", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const ref = await screen.findByTestId("reference-table");
    const eps = within(ref).getByTestId("basis-eps");
    const rev = within(ref).getByTestId("basis-revenue");
    expect(within(eps).getByText("AMGN")).toBeInTheDocument();
    expect(within(eps).getByText("CVS")).toBeInTheDocument();
    expect(within(rev).getByText("LLY")).toBeInTheDocument();
    expect(within(ref).getByTestId("unbanded")).toHaveTextContent("AAPL");
  });

  it("stacks the board in one column at phone width with no fixed min-width", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const board = await screen.findByTestId("zone-board");
    // Base (phone) layout is a single column; wider breakpoints add
    // columns. No element of the board carries a fixed min-width that
    // could push past a ~390px viewport.
    expect(board.className).toContain("grid-cols-1");
    expect(board.innerHTML).not.toMatch(/min-w-\[/);
    expect(board.innerHTML).not.toMatch(/min-width/);
  });

  it("shows an honest no-match state for a filter with no names", async () => {
    serve({ ...SUMMARY, held: {} });
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const board = await screen.findByTestId("zone-board");
    fireEvent.click(screen.getByTestId("filter-held"));
    expect(within(board).getByText(/no names match this view/i)).toBeInTheDocument();
  });
});

// ── Round 6: filtered views reconcile with their counts ──────────────────
// The classified tile promises 3 names; only AMGN is banded. KKR has no
// fact sheet in the snapshot and TTWO's sheet carries no full-year guide:
// both must be accounted under the board, with the reason, not dropped.
// The held set has banded and non-banded members alike.
const NO_SHEET = "not in the guidance universe / no fact sheet in this snapshot";
const NO_GUIDE = "no full-year guide on file — no bands computed";

const R6_SUMMARY = {
  ...SUMMARY,
  counts: { ...SUMMARY.counts, classified_prints: 3 },
  classified_names: [
    { ticker: "AMGN", classification: "improved", as_of: "2026-11-09",
      banded: true, sheet_status: "banded", reason: null },
    { ticker: "KKR", classification: "intact", as_of: "2026-11-09",
      banded: false, sheet_status: null, reason: NO_SHEET },
    { ticker: "TTWO", classification: "improved", as_of: "2026-11-09",
      banded: false, sheet_status: "no_full_year_guide", reason: NO_GUIDE },
  ],
  held: {
    CVS: { books: ["big"], qty: 120, sleeves: ["T8 AI winners core"] },
    AAPL: { books: ["main"], qty: 26, sleeves: [] },
    GLD: { books: ["big"], qty: 349, sleeves: [] },
  },
  held_names: [
    { ticker: "AAPL", books: ["main"], qty: 26, sleeves: [],
      banded: false, sheet_status: "no_full_year_guide", reason: NO_GUIDE },
    { ticker: "CVS", books: ["big"], qty: 120,
      sleeves: ["T8 AI winners core"], banded: true,
      sheet_status: "banded", reason: null },
    { ticker: "GLD", books: ["big"], qty: 349, sleeves: [],
      banded: false, sheet_status: null, reason: NO_SHEET },
  ],
};

describe("Guidance filtered-view reconciliation (Round 6)", () => {
  it("classified view: tile count == boarded chips + accounted names, each with its reason", async () => {
    serve(R6_SUMMARY);
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const board = await screen.findByTestId("zone-board");
    expect(within(screen.getByTestId("verdict-strip")).getByTestId("tile-classified"))
      .toHaveTextContent("3");
    fireEvent.click(screen.getByTestId("filter-classified"));
    const chips = within(board).getAllByTestId(/^board-chip-/);
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveTextContent("AMGN");
    const acct = screen.getByTestId("classified-accounting");
    expect(acct).toHaveTextContent("3 classified prints");
    expect(acct).toHaveTextContent("1 on the board");
    expect(acct).toHaveTextContent("2 accounted");
    // 3 (the tile) == 1 boarded + 2 accounted: nothing silently dropped.
    expect(acct).toHaveTextContent("KKR");
    expect(acct).toHaveTextContent(/intact/);
    expect(acct).toHaveTextContent("2026-11-09");
    expect(acct).toHaveTextContent(NO_SHEET);
    expect(acct).toHaveTextContent("TTWO");
    expect(acct).toHaveTextContent(/improved/);
    expect(acct).toHaveTextContent(NO_GUIDE);
  });

  it("held view: boarded held names carry the marker; non-banded held names are accounted with status", async () => {
    serve(R6_SUMMARY);
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const board = await screen.findByTestId("zone-board");
    fireEvent.click(screen.getByTestId("filter-held"));
    const chips = within(board).getAllByTestId(/^board-chip-/);
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveTextContent("CVS");
    expect(chips[0]).toHaveTextContent(/held/i);
    const acct = screen.getByTestId("held-accounting");
    expect(acct).toHaveTextContent("3 held names");
    expect(acct).toHaveTextContent("1 on the board");
    expect(acct).toHaveTextContent("2 not currently banded");
    expect(acct).toHaveTextContent("AAPL");
    expect(acct).toHaveTextContent(NO_GUIDE);
    expect(acct).toHaveTextContent("GLD");
    expect(acct).toHaveTextContent(NO_SHEET);
  });

  it("held view with a genuinely empty intersection says so with the full accounting", async () => {
    serve({
      ...R6_SUMMARY,
      held: { AAPL: R6_SUMMARY.held.AAPL, GLD: R6_SUMMARY.held.GLD },
      held_names: R6_SUMMARY.held_names.filter((h) => !h.banded),
    });
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const board = await screen.findByTestId("zone-board");
    fireEvent.click(screen.getByTestId("filter-held"));
    expect(within(board).queryAllByTestId(/^board-chip-/)).toHaveLength(0);
    const acct = screen.getByTestId("held-accounting");
    expect(acct).toHaveTextContent("2 held names, none currently banded");
    expect(acct).toHaveTextContent("AAPL");
    expect(acct).toHaveTextContent("GLD");
  });
});
