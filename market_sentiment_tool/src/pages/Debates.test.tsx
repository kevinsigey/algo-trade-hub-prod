import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Debates from "@/pages/Debates";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const FEED = {
  chip: "LLM agent debate — not a model signal",
  cards: [{ source: "agent_debate", chip: "LLM agent debate — not a model signal", run_id: "pltr-1", ticker: "PLTR",
    decision: "Buy", run_at_ct: "2026-11-01T09:00:00-05:00", as_of_date: "2026-10-20", historical: false,
    historical_label: null, framework_version: "0.2.3", framework_short: "0.2.3", llm_provider: "anthropic",
    llm_model: "claude-sonnet-4-5", status: "complete", error: null, stale: true, cost_usd: "not recorded",
    inputs_note: "framework defaults", analyst_summaries: { fundamentals: "not recorded" },
    bull_case: "Growth.", bear_case: "Valuation.", trader_rationale: "Starter.", risk_verdict: "Small.",
    has_report: true, grades: { "+5d": { ret_pct: 3.2, outcome: "hit" }, "+20d": "pending" } }],
  record: { h5: { graded: 1, hits: 1, hit_rate: 1, no_calls: 0 }, h20: { graded: 0, hits: 0, hit_rate: null, no_calls: 0 }, banner: false },
  banner: null,
};

function serve(routes: Record<string, { status?: number; body: unknown }>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => url.includes(k));
    const hit = key ? routes[key] : { status: 200, body: {} };
    return new Response(JSON.stringify(hit.body), { status: hit.status ?? 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Agent debates page", () => {
  it("explains itself and renders cards with the fence labels and the separate record", async () => {
    serve({ "/api/agent-debates": { body: FEED } });
    render(<MemoryRouter><Debates /></MemoryRouter>);
    expect(screen.getByText(/It is not a model/)).toBeInTheDocument();
    expect(screen.getByText(/about one full debate a day/)).toBeInTheDocument();
    expect(await screen.findByText("LLM agent debate — not a model signal")).toBeInTheDocument();
    expect(screen.getByText("PLTR")).toBeInTheDocument();
    expect(screen.getByText("stale")).toBeInTheDocument();
    expect(screen.getByText(/\+5d hit \(\+3\.2%\)/)).toBeInTheDocument();
    expect(screen.getAllByText(/kept separate from every model statistic/).length).toBeGreaterThan(0);
  });

  it("starts a debate from the form and says it is running", async () => {
    const f = serve({
      "/api/agent-debates": { body: { ...FEED, cards: [] } },
      "/api/agent-debates/run": { status: 202, body: { started: "NVDA" } },
    });
    render(<MemoryRouter><Debates /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Run a debate on a ticker"), { target: { value: "nvda" } });
    fireEvent.click(screen.getByRole("button", { name: "Start the debate" }));
    expect(await screen.findByText(/Debating NVDA/)).toBeInTheDocument();
    const posts = f.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    await waitFor(() => expect(posts.length).toBe(1));
    expect(String(posts[0][0])).toContain("/api/agent-debates/run");
    expect((posts[0][1] as RequestInit).body).toBe(JSON.stringify({ ticker: "NVDA" }));
  });
});
