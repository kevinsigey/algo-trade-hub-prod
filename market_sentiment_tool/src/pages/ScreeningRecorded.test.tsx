import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

const CATALOG = { functions: [], universe_builders: [], ops: [], cards: [] };

const SAVED = [{
  id: 6, name: "Buffett quality (classic)",
  spec: { name: "buffett_quality_classic",
          universe: { type: "index_union", indexes: ["sp500", "nasdaq100"] },
          membership_diff: true, filters: [] },
  last_run: { run_at: "2026-11-10T05:43:10Z", survivors: 2, survivor_issuers: 2,
              data_as_of: "2026-11-10T05:43:08Z", sources: ["yfinance.info"] },
  membership: null, membership_events: null, promoted_idea_id: null,
}];

const SINGLE_WITH_ROWS = {
  ...SAVED[0],
  last_run: {
    footer: { run_at: "2026-11-10T05:43:10Z", survivors: 2, survivor_issuers: 2,
              displayed: 2, display_limit: null, data_as_of: "2026-11-10" },
    columns: ["ticker", "roe"],
    rows: [{ ticker: "AAA", roe: 21.5 }, { ticker: "BBB", roe: 17.25 }],
    survivors: ["AAA", "BBB"],
  },
};

const SINGLE_LEGACY = { ...SAVED[0],
  last_run: { footer: SINGLE_WITH_ROWS.last_run.footer,
              columns: ["ticker", "roe"], survivors: ["AAA", "BBB"] } };

function serve(single: unknown) {
  const f = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = url.includes("/api/verdict-chips")
        ? { generated_at: "2026-11-10T12:00:00Z", chips: {} }
      : url.includes("/api/screening/catalog") ? CATALOG
      : /\/api\/screening\/screens\/\d+$/.test(url) && init?.method !== "POST" ? single
      : url.includes("/api/screening/screens") && init?.method !== "POST" ? SAVED
      : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Screening recorded results (Round 4)", () => {
  it("views the recorded rows from the record itself -- no re-run", async () => {
    const f = serve(SINGLE_WITH_ROWS);
    render(<MemoryRouter><Screening /></MemoryRouter>);
    expect(await screen.findByText("Buffett quality (classic)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Recorded results" }));
    expect(await screen.findByText("AAA")).toBeInTheDocument();
    expect(screen.getByText("BBB")).toBeInTheDocument();
    expect(screen.getByText("21.5")).toBeInTheDocument();
    expect(screen.getByText("17.25")).toBeInTheDocument();
    // Verdict chips ride along on the recorded rows, like the live table.
    expect(screen.getAllByText("No debate verdict yet").length).toBeGreaterThan(0);
    // Viewing never re-executes: no POST to the run endpoint, ever.
    const runCalls = f.mock.calls.filter(([u, init]) =>
      String(u).includes("/run") && init?.method === "POST");
    expect(runCalls).toHaveLength(0);
  });

  it("a legacy record without rows says so honestly instead of inventing them", async () => {
    serve(SINGLE_LEGACY);
    render(<MemoryRouter><Screening /></MemoryRouter>);
    expect(await screen.findByText("Buffett quality (classic)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Recorded results" }));
    expect(await screen.findByText(/row values were not kept/)).toBeInTheDocument();
    expect(screen.queryByText("AAA")).not.toBeInTheDocument();
  });
});
