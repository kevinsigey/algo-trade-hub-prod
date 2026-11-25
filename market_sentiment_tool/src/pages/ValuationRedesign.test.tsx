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
    as_of: "2026-11-09", banded: true, sheet_status: "banded", reason: null }],
  crossings: [{ ticker: "CVS", book: "main", zone: "buy_zone",
    action: "starter", created_at: "2026-11-10T05:00:00Z" }],
  held: { CVS: { books: ["big"], qty: 120, sleeves: ["T8 AI winners core"] } },
  held_positions_unavailable: false,
};

/** The rebuild board block, computed by the server from snapshots #2
 * and #3: CVS (held) revised its capex guide up and migrated into the
 * buy zone; AMGN's anchor guide and FCF guide were cut; AAPL is held
 * with no band. Grid distances: CVS -7.11 (inside the zone), AMGN
 * +32.64, LLY +72.19, XYZ +5.0. */
const BOARD = {
  snapshot_id: 3, previous_snapshot_id: 2,
  freshness: { snapshot_id: 3, computed_at: "2026-11-10T03:44:00Z",
    completed_at: "2026-11-10T03:50:00Z", age_hours: 5.2, stale: false,
    cadence: "Snapshots recompute hourly while the market is open, weekdays (valuation watch run)",
    previous_snapshot_id: 2, previous_computed_at: "2026-11-09T18:00:00Z" },
  movers: {
    guide_revisions: [
      { ticker: "CVS", metric: "capex", guide_metric: "capex",
        change_pct: 12.5, from: null, to: null, direction: null, held: true },
      { ticker: "AMGN", metric: "anchor", guide_metric: "eps_gaap",
        change_pct: -5.1, from: [18.34, 19.28], to: [17.4, 18.3],
        direction: "cut", held: false },
      { ticker: "AMGN", metric: "fcf", guide_metric: "fcf",
        change_pct: -20.0, from: null, to: null, direction: null, held: false },
    ],
    band_migrations: [
      { ticker: "CVS", from_zone: "neutral", to_zone: "buy_zone",
        price: 85.17, bands: { bear: 82.11, base: 91.23, bull: 91.23 },
        held: true },
    ],
    held_status: [
      { ticker: "CVS", zone: "buy_zone", status: "buy_zone",
        distance_pct: -7.11, price: 85.17,
        bands: { bear: 82.11, base: 91.23, bull: 91.23 } },
    ],
    snapshot_pair: true,
  },
  grid: [
    { ticker: "CVS", bands: { bear: 82.11, base: 91.23, bull: 91.23 },
      price: 85.17, price_as_of: "2026-11-06", status: "buy_zone",
      distance_pct: -7.11, held: true, books: ["big"],
      market_cap: 107400000000, zone: "buy_zone" },
    { ticker: "AMGN", bands: { bear: 272.18, base: 310.17, bull: 317.92 },
      price: 460.42, price_as_of: "2026-11-06", status: "above_bull",
      distance_pct: 32.64, held: false, books: [],
      market_cap: 250900000000, zone: "short_zone_strong" },
    { ticker: "LLY", bands: { bear: 347.35, base: 388.07, bull: 390.19 },
      price: 1395.48, price_as_of: "2026-11-06", status: "above_bull",
      distance_pct: 72.19, held: false, books: [],
      market_cap: 1245000000000, zone: "short_zone_strong" },
    { ticker: "XYZ", bands: { bear: 40, base: 47.5, bull: 55 },
      price: 50, price_as_of: "2026-11-06", status: "between",
      distance_pct: 5.0, held: false, books: [],
      market_cap: 50000000000, zone: "neutral" },
  ],
  missing_band: [
    { ticker: "AAPL", held: true, watched: false, books: ["main"],
      sheet_status: "no_full_year_guide",
      reason: "no full-year guide on file — no bands computed" },
  ],
};

function serve(summary: unknown = SUMMARY, sheets: unknown[] = SHEETS,
               board: unknown = BOARD) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/valuation-bands")) {
      return new Response(JSON.stringify({
        snapshot: { id: 3, computed_at: "2026-11-10T03:44:00Z",
          completed_at: "2026-11-10T03:50:00Z", sheet_count: sheets.length,
          banded_count: 3, source: "valuation_run" },
        sheets, summary, board,
      }), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function openCard(name: string) {
  fireEvent.click(await screen.findByRole("button", { name: `Open ${name}` }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Guidance rebuild — freshness, movers, grid, queue", () => {
  it("badges freshness: snapshot stamp, age, cadence, and no stale badge when fresh", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const bar = await screen.findByTestId("freshness-bar");
    expect(bar).toHaveTextContent("Snapshot #3");
    expect(bar).toHaveTextContent(/snapshot age 5h/i);
    expect(bar).toHaveTextContent(/hourly while the market is open/i);
    expect(within(bar).queryByTestId("freshness-stale")).toBeNull();
  });

  it("badges a stale snapshot plainly", async () => {
    serve(SUMMARY, SHEETS, {
      ...BOARD,
      freshness: { ...BOARD.freshness, age_hours: 41.5, stale: true },
    });
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const bar = await screen.findByTestId("freshness-bar");
    expect(within(bar).getByTestId("freshness-stale")).toHaveTextContent(/stale/i);
  });

  it("leads with the movers: revisions ranked with held pinned, migrations, held status", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    // The Movers card leads the card grid, ahead of the football field.
    const moversCard = await screen.findByRole("region", { name: "Movers" });
    const fieldCard = screen.getByRole("region", { name: "Football field" });
    expect(moversCard.compareDocumentPosition(fieldCard)
      & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await openCard("Movers");
    const movers = await screen.findByTestId("movers");
    const capex = within(movers).getByTestId("mover-CVS-capex");
    expect(capex).toHaveTextContent("+12.5%");
    expect(capex).toHaveTextContent(/held/i);
    const anchor = within(movers).getByTestId("mover-AMGN-anchor");
    expect(anchor).toHaveTextContent("18.34");
    expect(anchor).toHaveTextContent("17.40");
    expect(within(movers).getByTestId("mover-AMGN-fcf")).toHaveTextContent("-20.0%");
    expect(within(movers).getByTestId("migration-CVS")).toHaveTextContent(/band migration/i);
    expect(within(movers).getByTestId("held-status")).toHaveTextContent("CVS");
  });

  it("says plainly when there is no previous snapshot for movers", async () => {
    serve(SUMMARY, SHEETS, { ...BOARD, movers: null });
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Movers");
    const movers = await screen.findByTestId("movers");
    expect(movers).toHaveTextContent(/no previous completed snapshot/i);
  });

  it("renders every banded name once on the grid with its distance headline", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Football field");
    const grid = await screen.findByTestId("band-grid");
    for (const t of ["AMGN", "CVS", "LLY", "XYZ"]) {
      expect(within(grid).getAllByTestId(`grid-row-${t}`)).toHaveLength(1);
    }
    expect(within(grid).queryByTestId("grid-row-AAPL")).toBeNull();
    expect(within(grid).getByTestId("distance-CVS")).toHaveTextContent("-7.1%");
    expect(within(grid).getByTestId("distance-AMGN")).toHaveTextContent("+32.6%");
    expect(within(grid).getByTestId("grid-row-CVS")).toHaveTextContent(/held/i);
    expect(within(grid).getByTestId("grid-row-CVS"))
      .toHaveTextContent(/snapshot price as of 2026-11-06/i);
    // Default order: held first, then classified, then the rest by distance.
    const order = within(grid).getAllByTestId(/^grid-row-/)
      .map((el) => el.getAttribute("data-testid"));
    expect(order).toEqual(["grid-row-CVS", "grid-row-AMGN",
      "grid-row-XYZ", "grid-row-LLY"]);
  });

  it("grid sorts by market cap within the pinned groups and filters by zone status", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Football field");
    const grid = await screen.findByTestId("band-grid");
    fireEvent.click(within(grid).getByTestId("grid-sort-cap"));
    const order = within(grid).getAllByTestId(/^grid-row-/)
      .map((el) => el.getAttribute("data-testid"));
    // Groups stay pinned (held, classified, rest); inside the rest
    // group the cap sort puts LLY ($1.25T) ahead of XYZ ($50B).
    expect(order).toEqual(["grid-row-CVS", "grid-row-AMGN",
      "grid-row-LLY", "grid-row-XYZ"]);
    fireEvent.click(within(grid).getByTestId("grid-filter-above-bull"));
    expect(within(grid).getByTestId("grid-row-AMGN")).toBeInTheDocument();
    expect(within(grid).getByTestId("grid-row-LLY")).toBeInTheDocument();
    expect(within(grid).queryByTestId("grid-row-CVS")).toBeNull();
    fireEvent.click(within(grid).getByTestId("grid-filter-buy"));
    expect(within(grid).getByTestId("grid-row-CVS")).toBeInTheDocument();
    expect(within(grid).queryByTestId("grid-row-AMGN")).toBeNull();
  });

  it("queues held names with no band, with the reason and the way into the sheet", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    // The card carries the count; the worklist sits behind it.
    expect(await screen.findByRole("region", { name: "Missing a band" })).toHaveTextContent("1");
    await openCard("Missing a band");
    const queue = await screen.findByTestId("missing-band-queue");
    // The summary line NAMES the held name and gives the count.
    const summary = within(queue).getByTestId("queue-summary");
    expect(summary).toHaveTextContent("AAPL");
    expect(summary).toHaveTextContent(/1 name has no band/i);
    const row = within(queue).getByTestId("queue-row-AAPL");
    expect(row).toHaveTextContent(/held/i);
    expect(row).toHaveTextContent(/no full-year guide on file/i);
    expect(within(row).getByTestId("queue-open-AAPL")).toBeInTheDocument();
  });

  it("opening a sheet from the queue is idempotent — a second click never closes it", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Missing a band");
    const queue = await screen.findByTestId("missing-band-queue");
    const open = within(queue).getByTestId("queue-open-AAPL");
    fireEvent.click(open);
    // The sheet opens in place under its row and carries the falsifier.
    const sheet = await screen.findByTestId("queue-sheet-AAPL");
    expect(within(sheet).getAllByText(/no band to falsify/i).length).toBe(1);
    fireEvent.click(open);
    expect(screen.getByTestId("queue-sheet-AAPL")).toBeInTheDocument();
    expect(within(screen.getByTestId("queue-sheet-AAPL")).getAllByText(/no band to falsify/i).length).toBe(1);
  });

  it("renders the sheets and tables when the board block does not ride the load", async () => {
    serve(SUMMARY, SHEETS, null);
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Fact sheets");
    expect(await screen.findByTestId("reference-table")).toBeInTheDocument();
    expect(screen.queryByTestId("band-grid")).toBeNull();
    expect(screen.getByText(/board block did not ride this load/i)).toBeInTheDocument();
  });
});

describe("Guidance rebuild — the attention feed (kept surface)", () => {
  it("pins conjunctions at the top of the attention feed", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Needs attention");
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
    await openCard("Needs attention");
    const feed = await screen.findByTestId("attention-feed");
    expect(feed).toHaveTextContent(/nothing changed/i);
  });

  it("says plainly when there is no previous snapshot to diff against", async () => {
    serve({ ...SUMMARY, feed: [], feed_state: "no_previous_snapshot",
      previous_snapshot_id: null });
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Needs attention");
    const feed = await screen.findByTestId("attention-feed");
    expect(feed).toHaveTextContent(/no previous completed snapshot/i);
    expect(feed).not.toHaveTextContent(/nothing changed/i);
  });

  it("keeps the full reference table intact inside a disclosure, rows == served banded sheets", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Fact sheets");
    const ref = await screen.findByTestId("reference-table");
    const eps = within(ref).getByTestId("basis-eps");
    const rev = within(ref).getByTestId("basis-revenue");
    expect(within(eps).getByText("AMGN")).toBeInTheDocument();
    expect(within(eps).getByText("CVS")).toBeInTheDocument();
    expect(within(rev).getByText("LLY")).toBeInTheDocument();
    expect(within(ref).getByTestId("unbanded")).toHaveTextContent("AAPL");
  });
});

describe("Guidance presentation fix — one-screen default (2026-11-16)", () => {
  const extraRow = (ticker: string, distance: number, cap: number) => ({
    ticker, bands: { bear: 90, base: 100, bull: 110 }, price: 95,
    price_as_of: "2026-11-06", status: "between", distance_pct: distance,
    held: false, books: [], market_cap: cap, zone: "neutral",
  });
  const BOARD10 = {
    ...BOARD,
    grid: [...BOARD.grid,
      extraRow("R1", 10, 40e9), extraRow("R2", 20, 30e9),
      extraRow("R3", 30, 20e9), extraRow("R4", 40, 10e9),
      extraRow("R5", 50, 5e9), extraRow("R6", 60, 2e12)],
  };

  it("renders only the first eight rows full; the rest ride compact and expand in place", async () => {
    serve(SUMMARY, SHEETS, BOARD10);
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Football field");
    const grid = await screen.findByTestId("band-grid");
    // Every banded name is present — nothing dropped, nothing paged.
    expect(within(grid).getAllByTestId(/^grid-row-/)).toHaveLength(10);
    const compact = (t: string) =>
      within(grid).getByTestId(`grid-row-${t}`).getAttribute("data-compact");
    // Default sort (distance, groups pinned): CVS, AMGN, XYZ, R1..R5 full.
    expect(compact("CVS")).toBeNull();
    expect(compact("R5")).toBeNull();
    expect(compact("R6")).toBe("true");
    expect(compact("LLY")).toBe("true");
    // A compact row still carries its distance headline and mini bar.
    expect(within(grid).getByTestId("distance-LLY")).toHaveTextContent("+72.2%");
    expect(within(grid).getByTestId("band-track-LLY")).toBeInTheDocument();
    // One click expands it in place to the full football field.
    fireEvent.click(within(grid).getByTestId("grid-row-LLY"));
    expect(compact("LLY")).toBeNull();
    expect(within(grid).getByTestId("grid-row-LLY"))
      .toHaveTextContent(/Bear \$347\.35/);
  });

  it("changing the sort re-selects which eight rows render full", async () => {
    serve(SUMMARY, SHEETS, BOARD10);
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Football field");
    const grid = await screen.findByTestId("band-grid");
    fireEvent.click(within(grid).getByTestId("grid-sort-cap"));
    const compact = (t: string) =>
      within(grid).getByTestId(`grid-row-${t}`).getAttribute("data-compact");
    // Cap sort inside the rest group: R6 ($2T) and LLY ($1.25T) lead,
    // so both render full and R4/R5 fall to compact.
    expect(compact("R6")).toBeNull();
    expect(compact("LLY")).toBeNull();
    expect(compact("R4")).toBe("true");
    expect(compact("R5")).toBe("true");
  });

  it("keeps the attention feed and reference table behind their cards", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await screen.findByTestId("valuation-summary");
    expect(screen.queryByTestId("attention-feed")).toBeNull();
    expect(screen.queryByTestId("reference-table")).toBeNull();
    await openCard("Needs attention");
    expect(await screen.findByTestId("attention-feed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await openCard("Fact sheets");
    expect(await screen.findByTestId("reference-table")).toBeInTheDocument();
  });

  it("caps the names list at five rows with a Show all control that opens every sheet", async () => {
    serve(SUMMARY, SHEETS, BOARD10);
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    const list = await screen.findByTestId("names-list");
    // Ten banded names on the board; the page shows five.
    expect(within(list).getAllByTestId(/^name-row-/)).toHaveLength(5);
    // Held first, then classified, then the most below guidance value.
    expect(within(list).getAllByTestId(/^name-row-/)[0]).toHaveAttribute("data-testid", "name-row-CVS");
    expect(within(list).getByTestId("name-distance-CVS")).toHaveTextContent("-7.1%");
    fireEvent.click(within(list).getByTestId("names-show-all"));
    const ref = await screen.findByTestId("reference-table");
    expect(within(ref).getByTestId("basis-eps")).toHaveTextContent("AMGN");
  });
});

describe("Guidance tiles — the in-place ribbon (2026-11-16)", () => {
  it("opens the full fact sheet in a ribbon under the tile, not at the bottom tables", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Football field");
    const grid = await screen.findByTestId("band-grid");
    fireEvent.click(within(grid).getByTestId("grid-row-AMGN"));
    const ribbon = await screen.findByTestId("ribbon-AMGN");
    // The same full information the reference expansion carries: the
    // band chart and the guide provenance block.
    expect(within(ribbon).getByTestId("band-chart-AMGN"))
      .toHaveTextContent("Bear $272.18");
    expect(ribbon).toHaveTextContent("The guide behind the bands");
    expect(ribbon).toHaveTextContent("0000318154-26-000153");
    // Nothing navigated to the bottom: the reference section never
    // had to open for the sheet to be readable.
    expect(screen.queryByTestId("reference-table")).toBeNull();
  });

  it("moves with the selection and closes from its own control", async () => {
    serve();
    render(<MemoryRouter><Valuation /></MemoryRouter>);
    await openCard("Football field");
    const grid = await screen.findByTestId("band-grid");
    fireEvent.click(within(grid).getByTestId("grid-row-AMGN"));
    expect(await screen.findByTestId("ribbon-AMGN")).toBeInTheDocument();
    fireEvent.click(within(grid).getByTestId("grid-row-CVS"));
    expect(await screen.findByTestId("ribbon-CVS")).toBeInTheDocument();
    expect(screen.queryByTestId("ribbon-AMGN")).toBeNull();
    fireEvent.click(screen.getByTestId("ribbon-close-CVS"));
    expect(screen.queryByTestId("ribbon-CVS")).toBeNull();
  });
});
