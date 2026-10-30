import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import App from "@/App";
import { claimLabel, conditionText } from "@/lib/workshop";
import Workshop from "@/pages/Workshop";
import WorkshopIdea from "@/pages/WorkshopIdea";

const session = vi.hoisted(() => ({ token: "jwt" as string | null }));
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: session.token ? { access_token: session.token } : null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const SPEC = {
  title: "Gold when rates rise", hold: ["GLD"], otherwise: "SPY", claim: "beats_benchmark_when", benchmark: "SPY",
  cost_bps: 10, start: "2006-01-03", unseen_fraction: 0.3, assumptions: ["rates rising = 10-year yield up 0.25 over 3 months"],
  when: { source: "fred", series: "DGS10", measure: "change", lookback_days: 63, op: ">", threshold: 0.25 },
};
const RUN = {
  id: 1, variation: 4, spec: SPEC, draft_model: "claude-opus-5-5", verdict: "FAIL", created_at: "2026-10-30T00:00:00Z",
  result: {
    verdict: "FAIL", headline: "Worked on the years it was built on, not after.", reason: null, split_date: "2019-01-02",
    data_start: "2006-01-04", data_end: "2026-10-29", variations: 4,
    claim: { built: { holds: true, value: 3.1, label: "+3.1 pts/yr" }, unseen: { holds: false, value: -1.4, label: "-1.4 pts/yr" } },
    shuffle: { beats_pct: 71, p: 0.29, bar: 0.0125, permutations: 1000, seed: 4, method: "random timing" },
    t_test: { mean_daily_diff: 0.02, t: 1.7, p: 0.08 }, periods: { held: 3, of: 5 },
    context: [{ name: "Idea", built_cagr: 9, unseen_cagr: 7, unseen_max_dd: -20 }, { name: "SPY", built_cagr: 8, unseen_cagr: 12, unseen_max_dd: -25 }],
    curve: [{ t: "2006-01-04", idea: 0, benchmark: 0 }, { t: "2026-10-29", idea: 200, benchmark: 300 }],
  },
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
  session.token = "jwt";
  window.history.pushState({}, "", "/");
});

describe("workshop copy", () => {
  it("says each claim in plain words", () => {
    expect(claimLabel("ballast")).toMatch(/loses less than SPY/);
    expect(conditionText(SPEC.when as never)).toBe("DGS10 change over 63 trading days > 0.25");
    expect(conditionText(null)).toBe("always");
  });
});

describe("Workshop pages", () => {
  it("lists ideas with their latest verdict and sends the bearer token", async () => {
    const f = serve({ "/api/workshop/ideas": { body: [{ id: 1, title: "Gold when rates rise", created_at: "", runs: 4, latest_verdict: "FAIL" }] } });
    render(<MemoryRouter><Workshop /></MemoryRouter>);
    expect(await screen.findByText("Gold when rates rise")).toBeInTheDocument();
    expect(screen.getByLabelText("Type an idea in plain words")).toBeInTheDocument();
    expect(screen.getByText("4 runs")).toBeInTheDocument();
    expect((f.mock.calls[0][1] as RequestInit).headers).toMatchObject({ Authorization: "Bearer jwt" });
  });

  it("shows a verdict with the shuffle result and the variation count", async () => {
    serve({ "/api/workshop/ideas/1": { body: { idea: { id: 1, title: "Gold", plain_words: "Gold beats stocks when rates rise", created_at: "" }, runs: [RUN] } } });
    render(<MemoryRouter initialEntries={["/workshop/1"]}><Routes><Route path="/workshop/:id" element={<WorkshopIdea />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("Worked on the years it was built on, not after.")).toBeInTheDocument();
    expect(screen.getByText(/beats 71% of 1,000/)).toBeInTheDocument();
    expect(screen.getByText("4 · bar raised accordingly")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try a variation" })).toBeInTheDocument();
  });

  it("falls back to the hand-fill form when Claude can't draft", async () => {
    serve({
      "/api/workshop/ideas/2": { body: { idea: { id: 2, title: "Bonds", plain_words: "Bonds protect me", created_at: "" }, runs: [] } },
      "/api/workshop/draft": { status: 424, body: { detail: "ANTHROPIC_API_KEY is not set", reason: "no_key", template: { ...SPEC, title: "", hold: [], when: null, claim: "beats_benchmark", assumptions: [] } } },
    });
    render(<MemoryRouter initialEntries={["/workshop/2?draft=1"]}><Routes><Route path="/workshop/:id" element={<WorkshopIdea />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("Claude couldn't draft this — fill it in.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run it" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("Bonds")).toBeInTheDocument();
  });

  it("never sends the session to a path built from a non-numeric id", async () => {
    const f = serve({});
    render(<MemoryRouter initialEntries={["/workshop/..%2F..%2Fadmin%2Fme"]}><Routes><Route path="/workshop/:id" element={<WorkshopIdea />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("No such idea.")).toBeInTheDocument();
    expect(f).not.toHaveBeenCalled();
  });

  it("is admin only", async () => {
    session.token = null;
    serve({ "/api/portfolio": { body: { state: "not_connected", as_of: null, scoreboard: {}, curve: [], composition: [], positions: [] } } });
    window.history.pushState({}, "", "/workshop");
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByRole("heading", { name: "Admin only" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /workshop/i })).toHaveAttribute("href", "/workshop");
  });
});
