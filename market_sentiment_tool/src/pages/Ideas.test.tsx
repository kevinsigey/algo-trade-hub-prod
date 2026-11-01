import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import IdeaRecord from "@/pages/IdeaRecord";
import Ideas from "@/pages/Ideas";

// The pages share helpers with the Workshop, which imports the Supabase client; CI has no Supabase env.
vi.mock("@/lib/supabase", () => ({ supabase: { auth: { getSession: async () => ({ data: { session: null } }) } } }));

const LIVE = {
  days: 70, since: "2026-11-03", as_of: "2027-02-12", state: "live", return_pct: 4.2, bench_return_pct: 6.1,
  claim: { holds: false, label: "-3.1 pts/yr vs benchmark", days: 63 }, failing: true,
};
const ROWS = [
  { id: 3, title: "Bonds as ballast", published_at: "2026-11-02", claim: "ballast", latest_verdict: "FAIL", variations: 1,
    status: "backtest", live_at: null, killed_at: null, live: null },
  { id: 1, title: "Gold beats SPY", published_at: "2026-11-01", claim: "beats_benchmark", latest_verdict: "PASS", variations: 2,
    status: "live", live_at: "2026-11-02", killed_at: null, live: LIVE },
];

function serve(body: unknown, status = 200) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Ideas record", () => {
  it("lists every published idea, fails included, with its live record", async () => {
    serve(ROWS);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findByText("Bonds as ballast")).toBeInTheDocument();
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    expect(screen.getByText("Backtest only")).toBeInTheDocument();
    expect(screen.getByText("Claim failing on paper")).toBeInTheDocument();
    expect(screen.getByText("+4.2%")).toBeInTheDocument();
    expect(screen.getByText(/as of 2027-02-12/)).toBeInTheDocument();
  });

  it("labels a paper record too early below 30 days instead of calling its claim failing", async () => {
    serve([{ ...ROWS[1], live: { ...LIVE, days: 12, return_pct: -2.4, bench_return_pct: 1.1, claim: null, failing: true } }]);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findByText("Too early to say")).toBeInTheDocument();
    expect(screen.getByText("−2.4%")).toBeInTheDocument();
    expect(screen.getByText(/12 days/)).toBeInTheDocument();
    expect(screen.queryByText("Claim failing on paper")).not.toBeInTheDocument();
  });

  it("shows an idea's verdicts, paper record and tagged trades", async () => {
    serve({
      ...ROWS[1], plain_words: "Gold does better than stocks.",
      shadow: { ...LIVE, curve: [{ t: "2026-11-03", idea: 0.1, bench: 0.2 }], exits: [{ day: "2026-11-05", why: "stop-loss" }] },
      runs: [{ variation: 1, verdict: "FAIL", created_at: "2026-10-30T00:00:00Z", headline: "Did not do what it claims.", p: 0.3, bar: 0.05, claim: "beats_benchmark" },
             { variation: 2, verdict: "PASS", created_at: "2026-10-31T00:00:00Z", headline: "Did what it claims on the years it hadn't seen.", p: 0.01, bar: 0.025, claim: "beats_benchmark" }],
      trades: [{ symbol: "GLD", qty: 10, entry_price: 300, exit_price: 310, pnl: 100, return_pct: 3.3, exited_at: "2026-11-10T15:00:00Z", held_days: 8, idea: "Gold beats SPY" }],
    });
    render(<MemoryRouter initialEntries={["/ideas/1"]}><Routes><Route path="/ideas/:id" element={<IdeaRecord />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("Did not do what it claims.")).toBeInTheDocument();
    expect(screen.getByText("Did what it claims on the years it hadn't seen.")).toBeInTheDocument();
    expect(screen.getByText("GLD")).toBeInTheDocument();
    expect(screen.getByText("Claim failing on paper")).toBeInTheDocument();
    expect(screen.getByText("stop-loss · 2026-11-05")).toBeInTheDocument();
  });

  it("says a live idea with no paper days is stale, not about to start", async () => {
    serve([{ ...ROWS[1], live: { ...LIVE, days: 0, as_of: null, state: "stale", return_pct: null, bench_return_pct: null, claim: null, failing: false } }]);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findByText(/No paper days recorded since going live/)).toBeInTheDocument();
  });

  it("refuses a non-numeric id without fetching", async () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    render(<MemoryRouter initialEntries={["/ideas/..%2Fadmin"]}><Routes><Route path="/ideas/:id" element={<IdeaRecord />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("No such idea.")).toBeInTheDocument();
    expect(f).not.toHaveBeenCalled();
  });
});
