import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import IdeaRecord from "@/pages/IdeaRecord";
import Ideas, { betLead, standing } from "@/pages/Ideas";
import type { PublicIdea } from "@/lib/workshop";

// The pages share helpers with the Workshop, which imports the Supabase client; CI has no Supabase env.
vi.mock("@/lib/supabase", () => ({ supabase: { auth: { getSession: async () => ({ data: { session: null } }) } } }));

const LIVE = {
  days: 70, since: "2026-11-03", as_of: "2027-02-12", state: "live", return_pct: 4.2, bench_return_pct: 6.1,
  claim: { holds: false, label: "-3.1 pts/yr vs benchmark", days: 63 }, failing: true,
};
const ROWS = [
  { id: 3, title: "Bonds as ballast", published_at: "2026-11-02", claim: "ballast", kind: "long_only", latest_verdict: "FAIL", variations: 1,
    result_line: "+25.8 pts/yr vs SPY", result_value: 25.8, result_p: 0.03, status: "backtest", live_at: null, killed_at: null, live: null },
  { id: 1, title: "Gold beats SPY", published_at: "2026-11-01", claim: "beats_benchmark", kind: "event", latest_verdict: "PASS", variations: 2,
    result_line: "+5.0 pts/yr vs SPY", result_value: 5.0, result_p: 0.0001,
    status: "live", live_at: "2026-11-02", killed_at: null, live_books: ["main", "big"], live: LIVE },
];

function serve(body: unknown, status = 200) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Ideas record", () => {
  it("leads with what still stands; the fail stays on the record under Removed", async () => {
    serve(ROWS);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findByText("Gold beats SPY")).toBeInTheDocument();
    // The FAIL never passed, so it is trimmed out of the main list -- but the
    // record keeps it, one click down (Kevin, 2026-11-03 trim).
    expect(screen.getByText(/Removed under the current standard/)).toBeInTheDocument();
    expect(screen.getByText("Bonds as ballast")).toBeInTheDocument();
    expect(screen.getByText("+25.8 pts/yr vs SPY")).toBeInTheDocument();  // the card's result line
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    expect(screen.getByText("Backtest only")).toBeInTheDocument();
    // The live idea names each book it trades on; the backtest-only one names none.
    expect(screen.getByText("Live · Main")).toBeInTheDocument();
    expect(screen.getByText("Live · $1M")).toBeInTheDocument();
    expect(screen.getByText("Claim failing")).toBeInTheDocument();
    expect(screen.getByText("+4.2%")).toBeInTheDocument();
    expect(screen.getByText(/as of 2027-02-12/)).toBeInTheDocument();
  });

  it("sorts the standing list by performance or significance on request", async () => {
    serve(ROWS);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findByText("Gold beats SPY")).toBeInTheDocument();
    // The hero caption carries the permutation p.
    expect(screen.getByText(/p < 0\.001/)).toBeInTheDocument();
    const mainTitles = () => [...document.querySelectorAll("h3")].map((h) => h.textContent)
      .filter((t) => t === "Gold beats SPY");
    fireEvent.change(screen.getByLabelText("Sort"), { target: { value: "value" } });
    expect(screen.getByText(/Standing ideas/)).toBeInTheDocument();
    expect(mainTitles()).toEqual(["Gold beats SPY"]);
    fireEvent.change(screen.getByLabelText("Sort"), { target: { value: "p" } });
    expect(mainTitles()).toEqual(["Gold beats SPY"]);
  });

  it("shows a demoted PASS as failing now, with the reason on the card", async () => {
    serve([{ ...ROWS[0], id: 50, title: "NVDA call spread", latest_verdict: "PASS", verdict_now: "FAIL",
             wf_ok: false, fdr_pass: true, status: "backtest" }]);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findByText("NVDA call spread")).toBeInTheDocument();
    expect(screen.getByText(/Removed under the current standard/)).toBeInTheDocument();
    expect(screen.getByText(/Passed as run — demoted under the hub-wide standard/)).toBeInTheDocument();
  });

  it("groups ideas that bet on the same names as one bet", async () => {
    const fam = { key: 47, size: 2, tickers: ["MU", "TXN"], members: [47, 51] };
    serve([
      { ...ROWS[1], id: 47, title: "TXN and MU wrap", status: "backtest", live_at: null, live: null, live_books: [],
        latest_verdict: "PASS", verdict_now: "PASS", family: fam },
      { ...ROWS[1], id: 51, title: "MU TXN TSM sleeve", status: "backtest", live_at: null, live: null, live_books: [],
        latest_verdict: "PASS", verdict_now: "PASS", family: fam },
      { ...ROWS[1], id: 9, title: "Energy ballast", status: "backtest", live_at: null, live: null, live_books: [],
        latest_verdict: "PASS", verdict_now: "PASS", family: { key: 9, size: 1, tickers: ["XLE"], members: [9] } },
    ]);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findByText(/One bet · MU · TXN/)).toBeInTheDocument();
    expect(screen.getByText("TXN and MU wrap")).toBeInTheDocument();
    expect(screen.getByText("MU TXN TSM sleeve")).toBeInTheDocument();
    expect(screen.getByText(/Standalone/)).toBeInTheDocument();
    expect(screen.getByText("Energy ballast")).toBeInTheDocument();
  });

  it("labels gate overrides, hindsight selection and the registry position", async () => {
    serve([{ ...ROWS[1], gate_overridden: true, hindsight_selected: true,
             registry: { test_number: 58, tests_total: 63 } }]);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findByText("Gold beats SPY")).toBeInTheDocument();
    expect(screen.getByText("Gate overridden")).toBeInTheDocument();
    expect(screen.getByText("Hindsight-selected")).toBeInTheDocument();
    expect(screen.getByText(/test #58 of 63/)).toBeInTheDocument();
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
             { variation: 2, verdict: "PASS", created_at: "2026-10-31T00:00:00Z", headline: "Did what it claims on the years it hadn't seen.", p: 0.01, bar: 0.025, claim: "beats_benchmark",
               detail: { curve: [{ t: "2020-01-01", idea: 0, benchmark: 0 }, { t: "2021-01-01", idea: 12, benchmark: 5 }],
                 reason: null, variations: 2,
                 claim: { built: { holds: true, value: 1, label: "Beat it built" }, unseen: { holds: true, value: 1, label: "Beat it unseen" } },
                 shuffle: { beats_pct: 99, p: 0.01, bar: 0.025, permutations: 1000, seed: 1, method: "shuffle" },
                 t_test: null, periods: { held: 4, of: 5 }, walk_forward: { folds: [], held: 2, of: 2 }, context: [],
                 data_start: "2020-01-01", data_end: "2026-10-29", split_date: "2024-01-01", n_events: null, per_ticker: [], notes: null } }],
      trades: [{ symbol: "GLD", qty: 10, entry_price: 300, exit_price: 310, pnl: 100, return_pct: 3.3, exited_at: "2026-11-10T15:00:00Z", held_days: 8, idea: "Gold beats SPY" }],
    });
    render(<MemoryRouter initialEntries={["/ideas/1"]}><Routes><Route path="/ideas/:id" element={<IdeaRecord />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("Did not do what it claims.")).toBeInTheDocument();
    expect(screen.getByText("Did what it claims on the years it hadn't seen.")).toBeInTheDocument();
    // Opening the run shows the graph and the full evidence (Kevin, 2026-11-02).
    fireEvent.click(screen.getByRole("button", { name: /Did what it claims/ }));
    expect(await screen.findByText("On the unseen years")).toBeInTheDocument();
    expect(screen.getByText("Beat it unseen")).toBeInTheDocument();
    expect(screen.getByText(/Cumulative return since 2020-01-01/)).toBeInTheDocument();
    expect(screen.getByText("GLD")).toBeInTheDocument();
    expect(screen.getByText("Claim failing")).toBeInTheDocument();
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

describe("Tracked ideas (Kevin, 2026-11-02)", () => {
  const TRACKED = {
    id: 7, title: "Chips on a leash", published_at: "2026-11-02", claim: "beats_benchmark", kind: "long_only",
    latest_verdict: "PASS", variations: 1, result_line: "+14.9 pts/yr vs SPY", result_value: 14.9, result_p: 0.024,
    status: "tracking", live_at: null, tracked_at: "2026-11-02T23:59:00Z", killed_at: null, live_books: [],
    live: { days: 70, since: "2026-11-03", as_of: "2027-02-12", state: "live", return_pct: 3.4,
            bench_return_pct: 1.1, claim: { holds: true, label: "+2.3 pts/yr vs benchmark", days: 63 }, failing: false },
  };

  it("the card names tracking and shows the forward record against the benchmark", async () => {
    serve([TRACKED]);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findByText("Chips on a leash")).toBeInTheDocument();
    expect(screen.getByText("Tracking since 2026-11-02")).toBeInTheDocument();
    expect(screen.getByText("Forward")).toBeInTheDocument();
    expect(screen.getByText("+3.4%")).toBeInTheDocument();
    expect(screen.getByText(/Claim holding/)).toBeInTheDocument();
  });

  it("the record page banners tracking and heads the graph as a forward record", async () => {
    serve({ ...TRACKED, plain_words: "Chips, held loosely.", trades: [],
            shadow: { ...TRACKED.live, curve: [{ t: "2026-11-03", idea: 0.2, bench: 0.1 }, { t: "2026-12-02", idea: 3.4, bench: 1.1 }], exits: [] },
            runs: [] });
    render(<MemoryRouter initialEntries={["/ideas/7"]}><Routes><Route path="/ideas/:id" element={<IdeaRecord />} /></Routes></MemoryRouter>);
    expect(await screen.findByText(/Tracking since 2026-11-02/)).toBeInTheDocument();
    expect(screen.getByText(/Forward record since tracking 2026-11-02/)).toBeInTheDocument();
    expect(screen.getByText("Forward")).toBeInTheDocument();
  });
});

describe("betLead", () => {
  const idea = (id: number, status: string, value: number) => ({ id, status, result_value: value }) as unknown as PublicIdea;

  it("picks the idea trading now, else the best unseen result", () => {
    expect(betLead([idea(1, "backtest", 9), idea(2, "live", 1)]).id).toBe(2);
    expect(betLead([idea(1, "backtest", 2), idea(2, "tracking", 5)]).id).toBe(2);
  });
});

describe("Ideas standing", () => {
  it("keeps a failing idea in view while it trades, and clears a failing tracked one", () => {
    const failing = { verdict_now: "FAIL", latest_verdict: "PASS" };
    expect(standing({ ...failing, status: "live" } as unknown as PublicIdea)).toBe(true);
    expect(standing({ ...failing, status: "tracking" } as unknown as PublicIdea)).toBe(false);
  });
});
