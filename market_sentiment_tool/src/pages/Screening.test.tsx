import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function serve() {
  const f = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = url.includes("/api/screening/catalog")
      ? { functions: [{ name: "pe_ratio", category: "value", kind: "field", params: {}, returns: "ratio", doc: "Price / EPS.", source: "EDGAR XBRL" }], universe_builders: [], ops: [] }
      : url.includes("/api/screening/screens") && init?.method !== "POST"
        ? []
        : url.includes("/api/screening/run")
          ? RUN
          : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Screening page", () => {
  it("runs a spec, sorts by any column, flags best fits, and shows provenance", async () => {
    serve();
    render(<MemoryRouter><Screening /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Run the screen" }));
    expect(await screen.findByText("3 survivors")).toBeInTheDocument();
    // best fit = highest score (BBB 95, AAA 88, CCC 40 -> top 3 all fit here), badge present
    expect(screen.getAllByText("Best fit").length).toBeGreaterThan(0);
    // missing reads as a dash, never zero
    expect(screen.getByText("—")).toBeInTheDocument();
    // sort by pe_ratio ascending: AAA(9) before BBB(11), CCC(null) last
    fireEvent.click(screen.getByRole("button", { name: /pe_ratio/ }));
    fireEvent.click(screen.getByRole("button", { name: /pe_ratio/ }));
    const cells = screen.getAllByRole("cell");
    const tickers = cells.filter((_, i) => i % 3 === 0).map((c) => c.textContent);
    expect(tickers[0]).toContain("AAA");
    expect(tickers[2]).toContain("CCC");
    // provenance on row click
    fireEvent.click(screen.getByText("AAA"));
    expect(await screen.findByText(/EDGAR XBRL · as of 2026-10-30/)).toBeInTheDocument();
  });

  it("labels each filter row with its catalog source", async () => {
    serve();
    render(<MemoryRouter><Screening /></MemoryRouter>);
    // the default starter spec carries a momentum filter; the catalog stub only
    // knows pe_ratio, so swap in a pe filter through the editor
    const editor = screen.getByLabelText("The spec (editable JSON)");
    fireEvent.change(editor, { target: { value: JSON.stringify({
      name: "x", universe: { type: "list", tickers: ["AAA"] },
      filters: [{ fn: "pe_ratio", op: "lt", value: 12 }] }) } });
    await waitFor(() => expect(screen.getAllByText("EDGAR XBRL").length).toBeGreaterThan(0));
  });
});
