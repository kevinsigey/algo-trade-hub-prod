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

function serve(translateBody?: unknown) {
  const f = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = url.includes("/api/screening/catalog") ? CATALOG
      : url.includes("/api/screening/translate") ? translateBody
      : url.includes("/api/screening/screens") && init?.method !== "POST" ? []
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
    const blurb = (await screen.findAllByText("Price over trailing earnings."))[0];
    const cardEl = blurb.closest("div") as HTMLElement;
    fireEvent.click(within(cardEl).getByRole("button", { name: /Add/ }));
    const value = await screen.findByLabelText("P/E ratio value");
    expect((value as HTMLInputElement).value).toBe("15");
  });

  it("translate fills the cards, including on the rules fallback", async () => {
    serve({ spec: { name: "described_screen", universe: { type: "index", index: "sp500" }, limit: 10,
                    filters: [{ fn: "momentum", params: { months: 6 }, op: "pct_gte", value: 75 },
                              { fn: "last_print_surprise_pct", op: "gt", value: 0 }] },
            model: "rules (AI unavailable: HTTPError)" });
    render(<MemoryRouter><Screening /></MemoryRouter>);
    await screen.findAllByText("Price over trailing earnings."); // catalog loaded
    fireEvent.change(screen.getByLabelText("Describe the screen in plain English"),
      { target: { value: "stocks with strong momentum and beat earnings with positive guidance" } });
    fireEvent.click(screen.getByRole("button", { name: "Translate" }));
    expect(await screen.findByText(/built-in rules/)).toBeInTheDocument();
    expect(screen.getByLabelText("Momentum 6M value")).toBeInTheDocument();
    expect(screen.getByLabelText("Last earnings surprise value")).toBeInTheDocument();
  });
});
