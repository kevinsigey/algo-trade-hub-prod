import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Screening from "@/pages/Screening";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const CARDS = [
  { id: "mom6", fn: "momentum", params: { months: 6 }, label: "Momentum 6M", group: "Momentum & trend",
    blurb: "Six-month momentum.", unit: "%", divisor: 1, source: "yfinance prices",
    ops: ["ge", "gt", "le", "lt", "pct_gte", "pct_lte"], preset: { op: "pct_gte", value: 75 } },
  { id: "surprise", fn: "last_print_surprise_pct", params: {}, label: "Last earnings surprise", group: "Earnings",
    blurb: "How far the last EPS landed from expectations.", unit: "%", divisor: 1, source: "earnings panel",
    ops: ["ge", "gt", "le", "lt", "pct_gte", "pct_lte"], preset: { op: "gt", value: 0 } },
  { id: "reaction", fn: "last_print_reaction_pct", params: {}, label: "Reaction to the last print", group: "Earnings",
    blurb: "How the stock moved on its last earnings.", unit: "%", divisor: 1, source: "earnings panel",
    ops: ["ge", "gt", "le", "lt", "pct_gte", "pct_lte"], preset: { op: "gt", value: 0 } },
  { id: "pe", fn: "pe_ratio", params: {}, label: "P/E ratio", group: "Valuation",
    blurb: "Price over trailing earnings.", unit: "x", divisor: 1, source: "yfinance.info",
    ops: ["ge", "gt", "le", "lt", "pct_gte", "pct_lte"], preset: { op: "lt", value: 15 } },
];

const CATALOG = {
  functions: [{ name: "pe_ratio", category: "value", kind: "field", params: {}, returns: "x", doc: "Price / EPS.", source: "yfinance.info" }],
  universe_builders: [], ops: [], cards: CARDS,
};

const RUN = {
  columns: ["ticker", "pe_ratio", "score"],
  rows: [
    { ticker: "AAA", pe_ratio: 9, score: 88 },
    { ticker: "BBB", pe_ratio: 11, score: 95 },
    { ticker: "CCC", pe_ratio: null, score: 40 },
  ],
  footer: { spec_name: "demo", run_at: "2026-11-02T20:00:00Z", universe_size: 50, survivors: 3,
            columns: { pe_ratio: { fn: "pe_ratio", source: "EDGAR XBRL", as_of: "2026-10-30" },
                       score: { fn: "score", source: "blend" } } },
};

const QUOTE = {
  ticker: "AAA", price: 121, prev_close: 110, change_pct: 10, volume: 3000,
  as_of: "2026-11-03",
  closes: [{ date: "2026-10-30", close: 100 }, { date: "2026-11-02", close: 110 },
           { date: "2026-11-03", close: 121 }],
};

const RUN_MISSING = {
  ...RUN,
  footer: { ...RUN.footer, missing: [
    { ticker: "AAA", field: "pe_ratio", reason: "info field absent" },
    { ticker: "AAA", field: "roe", reason: "info field absent" },
    { ticker: "BBB", field: "pe_ratio", reason: "info field absent" },
  ] },
};

const CATALOG_PCT = {
  ...CATALOG,
  functions: [...CATALOG.functions,
    { name: "roe", category: "quality", kind: "field", params: {}, returns: "pct", doc: "Return on equity.", source: "yfinance.info" }],
  computed_at: "2026-11-10T04:30:00Z",
};

const RUN_ROE = {
  columns: ["ticker", "roe"],
  rows: [{ ticker: "AAA", roe: 18.741 }],
  footer: { spec_name: "quality", run_at: "2026-11-10T04:00:00Z", universe_size: 3, survivors: 1,
            columns: { roe: { fn: "roe", source: "yfinance.info" } } },
};

const CLASSIC_ROW = {
  id: 5, name: "Graham value (classic)",
  spec: { name: "graham_value_classic", universe: { type: "list", tickers: ["AAA"] } },
  last_run: {
    run_at: "2026-11-10T04:02:00Z", survivors: 2,
    near_misses: [{ ticker: "LEN", fn: "pe_ratio", column: "pe_ratio", value: 7.4, op: "lt", threshold: 7 }],
    near_miss_count: 1,
  },
  membership: { tracked_since: "2026-11-10", as_of: "2026-11-10",
                members: { AAA: "2026-11-10", BBB: "2026-11-10" } },
  membership_events: [
    { ticker: "AAA", kind: "exited", date: "2026-11-11", since: "2026-11-10" },
    { ticker: "BBB", kind: "entered", date: "2026-11-11" },
  ],
  promoted_idea_id: null,
};

function serve(translateBody?: unknown,
               extra?: { screens?: unknown; run?: unknown; catalog?: unknown }) {
  const f = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = url.includes("/api/screening/catalog") ? (extra?.catalog ?? CATALOG)
      : url.includes("/api/screening/translate") ? translateBody
      : url.includes("/api/screening/quote/") ? QUOTE
      : url.includes("/api/screening/screens") && init?.method !== "POST" ? (extra?.screens ?? [])
      : url.includes("/api/screening/run") ? (extra?.run ?? RUN)
      : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", f);
  return f;
}

const SAVED_ONE = [{
  id: 7, name: "oversold_quality",
  spec: { name: "oversold_quality", universe: { type: "index", index: "sp500" },
          filters: [], limit: 10 },
  last_run: { run_at: "2026-11-09T15:30:00Z", survivors: 1,
              data_as_of: "2026-11-08", sources: ["EDGAR XBRL", "yfinance prices"] },
  promoted_idea_id: null,
}];

function serveSaved() {
  const f = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = url.includes("/api/screening/catalog")
        ? { ...CATALOG, universe_refresh: { sp500: { as_of: "2026-11-09T12:00:00Z",
              source: "wikipedia", count: 503 } } }
      : url.includes("/api/screening/screens") && init?.method !== "POST" ? SAVED_ONE
      : url.includes("/api/screening/run") ? RUN
      : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Screening page (cards)", () => {
  it("runs a preset-built screen, sorts, flags best fits, shows provenance", async () => {
    const f = serve();
    render(<MemoryRouter><Screening /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /Earnings momentum/ }));
    expect(await screen.findByLabelText("Last earnings surprise value")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run the screen" }));
    expect(await screen.findByText("3 survivors")).toBeInTheDocument();
    const runCall = f.mock.calls.find(([u]) => String(u).includes("/api/screening/run"));
    const sent = JSON.parse(String(runCall?.[1]?.body ?? "{}"));
    const fns = (sent.spec.filters as { fn: string }[]).map((x) => x.fn);
    expect(fns).toContain("momentum");
    expect(fns).toContain("last_print_surprise_pct");
    expect(screen.getAllByText("Best fit").length).toBeGreaterThan(0);
    expect(screen.getByText("—")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /pe_ratio/ }));
    fireEvent.click(screen.getByRole("button", { name: /pe_ratio/ }));
    const cells = screen.getAllByRole("cell");
    const tickers = cells.filter((_, i) => i % 3 === 0).map((c) => c.textContent);
    expect(tickers[0]).toContain("AAA");
    expect(tickers[2]).toContain("CCC");
    fireEvent.click(screen.getByText("AAA"));
    expect(await screen.findByText(/EDGAR XBRL · as of 2026-10-30/)).toBeInTheDocument();
  });

  it("adds a library card with its preset, and the JSON editor is gone", async () => {
    serve();
    render(<MemoryRouter><Screening /></MemoryRouter>);
    expect(screen.queryByLabelText("The spec (editable JSON)")).not.toBeInTheDocument();
    // The library hides behind group dropdowns (Kevin, 2026-11-03).
    fireEvent.click(await screen.findByRole("button", { name: /Valuation/ }));
    const blurb = (await screen.findAllByText("Price over trailing earnings."))[0];
    const cardEl = blurb.closest("div") as HTMLElement;
    fireEvent.click(within(cardEl).getByRole("button", { name: /Add/ }));
    const value = await screen.findByLabelText("P/E ratio value");
    expect((value as HTMLInputElement).value).toBe("15");
  });

  it("shows results directly under the search bar, above the library", async () => {
    serve();
    render(<MemoryRouter><Screening /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /Earnings momentum/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run the screen" }));
    expect(await screen.findByText("3 survivors")).toBeInTheDocument();
    const table = screen.getByRole("table");
    const library = screen.getByText(/Filter library/);
    // The results table must come first in the document.
    expect(table.compareDocumentPosition(library) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("clicking a row shows its last quote, day change, volume and a chart", async () => {
    serve();
    render(<MemoryRouter><Screening /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /Earnings momentum/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run the screen" }));
    expect(await screen.findByText("3 survivors")).toBeInTheDocument();
    fireEvent.click(screen.getByText("AAA"));
    expect(await screen.findByText(/Last \$121\.00/)).toBeInTheDocument();
    expect(screen.getByText(/\+10\.00% on the day/)).toBeInTheDocument();
    expect(screen.getByText(/volume 3,000/)).toBeInTheDocument();
    expect(screen.getByText(/Delayed data/)).toBeInTheDocument();
    expect(document.querySelector("polyline")).not.toBeNull();
  });

  it("shows membership entrances and exits on a saved classic screen card", async () => {
    serve(undefined, { screens: [CLASSIC_ROW] });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    expect(await screen.findByText("Graham value (classic)")).toBeInTheDocument();
    expect(screen.getByText(/membership tracked since Nov 10/)).toBeInTheDocument();
    expect(screen.getByText(/entered · Nov 11/)).toBeInTheDocument();
    expect(screen.getByText(/exited · was member since Nov 10/)).toBeInTheDocument();
  });

  it("shows near misses with units on the saved screen card", async () => {
    serve(undefined, { screens: [CLASSIC_ROW] });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    expect(await screen.findByText(/Near misses — one filter away \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/P\/E ratio 7\.4 × vs < 7/)).toBeInTheDocument();
    expect(screen.getByText("LEN")).toBeInTheDocument();
  });

  it("renders the missing-data record per ticker, with counts", async () => {
    serve(undefined, { run: RUN_MISSING });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /Earnings momentum/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run the screen" }));
    expect(await screen.findByText(/Missing data \(fails its filter, never zero\): 2 names · 3 field gaps/))
      .toBeInTheDocument();
    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toContain("AAA — pe_ratio, roe");
    expect(items).toContain("BBB — pe_ratio");
    // The old wall of bare repeated field names is gone.
    expect(screen.queryByText(/pe_ratio, roe, pe_ratio/)).not.toBeInTheDocument();
  });

  it("column headers carry units, and the catalog carries a computed-at stamp", async () => {
    serve(undefined, { run: RUN_ROE, catalog: CATALOG_PCT });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /Earnings momentum/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run the screen" }));
    expect(await screen.findByText("1 survivor")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /roe \(%\)/ })).toBeInTheDocument();
    expect(screen.getByText(/computed 2026-11-10 04:30 UTC/)).toBeInTheDocument();
  });

  it("stamps saved screens with time, source, and singular grammar; chips mark presets vs saved", async () => {
    serveSaved();
    render(<MemoryRouter><Screening /></MemoryRouter>);
    // The saved row: full-year timestamp, sources, and "1 survivor".
    expect(await screen.findByText(/last run .*2026/)).toBeInTheDocument();
    expect(screen.getByText(/sources: EDGAR XBRL, yfinance prices/)).toBeInTheDocument();
    expect(screen.getByText(/1 survivor(?!s)/)).toBeInTheDocument();
    // The collision is resolved visually: the preset and the saved screen
    // carry different chips.
    expect(screen.getAllByText("Preset").length).toBeGreaterThan(0);
    expect(screen.getByText("Saved")).toBeInTheDocument();
    // Universe refresh stamps come from the catalog.
    expect(screen.getByText(/refreshed .* · wikipedia · 503 names/)).toBeInTheDocument();
    expect(screen.getAllByText(/bundled proxy — not yet refreshed/).length).toBeGreaterThan(0);
  });

  it("translate fills the cards, including on the rules fallback", async () => {
    serve({ spec: { name: "described_screen", universe: { type: "index", index: "sp500" }, limit: 10,
                    filters: [{ fn: "momentum", params: { months: 6 }, op: "pct_gte", value: 75 },
                              { fn: "last_print_surprise_pct", op: "gt", value: 0 }] },
            model: "rules (AI unavailable: HTTPError)" });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    await screen.findByRole("button", { name: /Valuation/ }); // catalog loaded (library collapsed)
    fireEvent.change(screen.getByLabelText("Describe the screen in plain English"),
      { target: { value: "stocks with strong momentum and beat earnings with positive guidance" } });
    fireEvent.click(screen.getByRole("button", { name: "Translate" }));
    expect(await screen.findByText(/built-in rules/)).toBeInTheDocument();
    expect(screen.getByLabelText("Momentum 6M value")).toBeInTheDocument();
    expect(screen.getByLabelText("Last earnings surprise value")).toBeInTheDocument();
  });
});

describe("Screening page (Round 2)", () => {
  const UNION_ROW = {
    id: 6, name: "Buffett quality (classic)",
    spec: { name: "buffett_quality_classic",
      universe: { type: "common_equity",
                  base: { type: "index_union", indexes: ["sp500", "nasdaq100"] } },
      max_universe: 600, membership_diff: true,
      filters: [{ fn: "roe", op: "gt", value: 15 }], limit: 25 },
    last_run: { run_at: "2026-11-10T05:04:28Z", survivors: 40, survivor_issuers: 39,
                data_as_of: "2026-11-10T05:04:25Z", sources: ["yfinance.info"] },
    membership: null, membership_events: null, promoted_idea_id: null,
  };

  it("loads a saved classic screen with its union universe intact", async () => {
    serve(undefined, { screens: [UNION_ROW] });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    expect(await screen.findByText("Buffett quality (classic)")).toBeInTheDocument();
    // Rows and issuers both on the saved card.
    expect(screen.getByText(/40 survivors · 39 issuers/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load into cards" }));
    // The composed spec must BE the saved spec's universe -- the Round 1
    // defect silently rebuilt it as {index: sp500} under the 300 cap.
    const pre = document.querySelector("pre");
    expect(pre?.textContent).toContain("index_union");
    expect(pre?.textContent).toContain("common_equity");
    expect(pre?.textContent).toContain("600");
    expect(pre?.textContent).toContain("membership_diff");
    // ...and the page says in plain words which universe is loaded.
    expect(screen.getByText(/S&P 500 \+ Nasdaq-100 union/)).toBeInTheDocument();
  });

  it("labels a truncated near-miss list with the stored count and the true total", async () => {
    const stored = Array.from({ length: 8 }, (_, i) => ({
      ticker: `NM${i + 1}`, fn: "pe_ratio", column: "pe_ratio",
      value: 7.4, op: "lt", threshold: 7 }));
    const row = { ...CLASSIC_ROW, last_run: { run_at: "2026-11-10T04:02:00Z",
      survivors: 2, near_misses: stored, near_miss_count: 89 } };
    serve(undefined, { screens: [row] });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    expect(await screen.findByText(/Near misses — one filter away \(8 closest of 89\)/))
      .toBeInTheDocument();
    expect(screen.getByText(/all 8 stored near misses/)).toBeInTheDocument();
    expect(screen.queryByText(/all 89 near misses/)).not.toBeInTheDocument();
  });

  it("renders a dual-class membership event with both tickers", async () => {
    const row = { ...CLASSIC_ROW, membership_events: [
      { ticker: "BRK-A", tickers: ["BRK-A", "BRK-B"], kind: "entered", date: "2026-11-11" }] };
    serve(undefined, { screens: [row] });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    expect(await screen.findByText(/BRK-A \+ BRK-B/)).toBeInTheDocument();
    expect(screen.getByText(/entered · Nov 11/)).toBeInTheDocument();
  });

  it("shows rows + issuers and the selection rule on a run's header", async () => {
    const runUnion = {
      columns: ["ticker", "roe"],
      rows: [{ ticker: "GOOG", roe: 30 }, { ticker: "GOOGL", roe: 28 }],
      footer: { spec_name: "buffett_quality_classic", run_at: "2026-11-10T05:10:00Z",
        universe_size: 518, survivors: 2, survivor_issuers: 1,
        universe_selection: "all 518 names enriched — union universe, no enrichment cap",
        columns: { roe: { fn: "roe", source: "yfinance.info", as_of: "2026-11-10" } } },
    };
    serve(undefined, { run: runUnion });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /Earnings momentum/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run the screen" }));
    expect(await screen.findByText(/2 survivors/)).toBeInTheDocument();
    expect(screen.getByText(/· 1 issuer/)).toBeInTheDocument();
    expect(screen.getByText(/union universe, no enrichment cap/)).toBeInTheDocument();
  });
});

describe("Screening page (Round 3)", () => {
  const CLASSIC_NO_LIMIT = {
    id: 6, name: "Buffett quality (classic)",
    spec: { name: "buffett_quality_classic",
      universe: { type: "common_equity",
                  base: { type: "index_union", indexes: ["sp500", "nasdaq100"] } },
      max_universe: 600, membership_diff: true,
      filters: [{ fn: "roe", op: "gt", value: 15 }] },
    last_run: { run_at: "2026-11-10T05:43:10Z", survivors: 40, survivor_issuers: 39,
                data_as_of: "2026-11-10T05:43:08Z", sources: ["yfinance.info"] },
    membership: null, membership_events: null, promoted_idea_id: null,
  };

  it("a loaded saved screen with no limit composes NO limit (the builder's 25 must not leak in)", async () => {
    serve(undefined, { screens: [CLASSIC_NO_LIMIT] });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    expect(await screen.findByText("Buffett quality (classic)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load into cards" }));
    const pre = document.querySelector("pre");
    expect(pre?.textContent).toContain("index_union");
    expect(pre?.textContent).not.toContain('"limit"');
    // The page says the saved screen's own (absent) limit governs.
    expect(screen.getByText(/no result limit of its own/)).toBeInTheDocument();
  });

  it("a run header reports the TRUE count and labels the display cut", async () => {
    const truncated = {
      columns: ["ticker", "roe"],
      rows: [{ ticker: "AAA", roe: 50 }, { ticker: "BBB", roe: 40 }],
      footer: { spec_name: "buffett_quality_classic", run_at: "2026-11-10T05:47:00Z",
        universe_size: 518, survivors: 40, survivor_issuers: 39,
        displayed: 25, display_limit: 25,
        columns: { roe: { fn: "roe", source: "yfinance.info", as_of: "2026-11-10" } } },
    };
    serve(undefined, { run: truncated });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /Earnings momentum/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run the screen" }));
    expect(await screen.findByText(/40 survivors/)).toBeInTheDocument();
    expect(screen.getByText(/39 issuers/)).toBeInTheDocument();
    expect(screen.getByText(/showing 25 of 40/)).toBeInTheDocument();
    expect(screen.queryByText(/25 survivors/)).not.toBeInTheDocument();
  });

  it("saving a screen never attaches the builder's ad-hoc run as its record", async () => {
    const f = serve();
    render(<MemoryRouter><Screening /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /Earnings momentum/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run the screen" }));
    expect(await screen.findByText("3 survivors")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save screen" }));
    expect(await screen.findByText(/use Re-run on the saved screen to record a run/))
      .toBeInTheDocument();
    const saveCall = f.mock.calls.find(([u, init]) =>
      String(u).endsWith("/api/screening/screens") && init?.method === "POST");
    expect(saveCall).toBeTruthy();
    const body = JSON.parse(String(saveCall?.[1]?.body ?? "{}"));
    expect(body).not.toHaveProperty("last_run");
    expect(body.spec).toBeTruthy();
  });

  it("the saved card attributes each field's source per field", async () => {
    const row = { ...CLASSIC_NO_LIMIT,
      last_run: { run_at: "2026-11-10T05:43:10Z", survivors: 40, survivor_issuers: 39,
        data_as_of: "2026-11-10T05:43:08Z",
        sources: ["SEC EDGAR company facts", "yfinance.info"],
        column_sources: { roe: "yfinance.info",
                          eps_growth_5y: "SEC EDGAR company facts" } } };
    serve(undefined, { screens: [row] });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    expect(await screen.findByText(/roe \(yfinance\.info\)/)).toBeInTheDocument();
    expect(screen.getByText(/eps_growth_5y \(SEC EDGAR company facts\)/)).toBeInTheDocument();
  });
});
