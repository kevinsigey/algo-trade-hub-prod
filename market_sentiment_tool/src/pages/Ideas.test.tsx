import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import IdeaRecord from "@/pages/IdeaRecord";
import Ideas, { betLead, standing } from "@/pages/Ideas";
import type { PublicIdea } from "@/lib/workshop";

import App from "@/App";
import { TradeLabels } from "@/components/TradeLabels";
import type { FillRow } from "@/lib/workshop";

// The pages share helpers with the Workshop lib, which imports the Supabase client; CI has no Supabase env.
const session = vi.hoisted(() => ({ token: null as string | null }));
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: session.token ? { access_token: session.token } : null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

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

/** Answer by URL: the longest matching key wins; anything else is an empty object. */
function serveRoutes(routes: Record<string, unknown>) {
  const f = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => url.includes(k));
    return new Response(JSON.stringify(key ? routes[key] : {}), { status: 200 });
  });
  vi.stubGlobal("fetch", f);
  return f;
}
const posts = (f: ReturnType<typeof serveRoutes>) =>
  f.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST").map(([u, init]) => [String(u), (init as RequestInit).body]);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  session.token = null;
  window.history.pushState({}, "", "/");
  try { localStorage.clear(); } catch { void 0; }
});

/** Show all on a list card opens the full list in a dialog; returns queries scoped to it. */
async function showAll(card: "Trading now" | "In shadow") {
  fireEvent.click(await screen.findByRole("button", { name: `Show all ${card}` }));
  return within(await screen.findByRole("dialog", { name: card }));
}

describe("Ideas record", () => {
  it("peeks at what is trading on the page; Show all has the full cards, and the fail waits under Removed", async () => {
    serve(ROWS);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findAllByText("Gold beats SPY")).not.toHaveLength(0);
    // The page itself is a dashboard: the FAIL is not trading and not in shadow, only in test activity and under Show all > Removed.
    expect(screen.getByRole("region", { name: "Trading now" })).not.toHaveTextContent("Bonds as ballast");
    expect(screen.getByRole("region", { name: "In shadow" })).not.toHaveTextContent("Bonds as ballast");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const all = await showAll("Trading now");
    // The live idea names each book it trades on; the backtest-only one names none.
    expect(all.getByText("Live · Main")).toBeInTheDocument();
    expect(all.getByText("Live · $1M")).toBeInTheDocument();
    expect(all.getByText("Claim failing")).toBeInTheDocument();
    expect(all.getByText("+4.2%")).toBeInTheDocument();
    expect(all.getByText(/as of 2027-02-12/)).toBeInTheDocument();
    // The FAIL never passed, so it is a filter away -- but the record keeps it (Kevin, 2026-11-03 trim).
    fireEvent.click(all.getByRole("button", { name: /^Removed/ }));
    expect(all.getByText(/Removed under the current standard/)).toBeInTheDocument();
    expect(all.getByText("Bonds as ballast")).toBeInTheDocument();
    expect(all.getByText("+25.8 pts/yr vs SPY")).toBeInTheDocument();  // the card's result line
    expect(all.getByText("FAIL")).toBeInTheDocument();
    expect(all.getByText("Backtest only")).toBeInTheDocument();
  });

  it("caps each page list at 5 rows and leaves the rest to Show all", async () => {
    const live = (id: number) => ({ ...ROWS[1], id, title: `Live idea ${id}`, live_books: ["main"] });
    serve([1, 2, 3, 4, 5, 6, 7].map(live));
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    const card = await screen.findByRole("region", { name: "Trading now" });
    expect(within(card).getAllByRole("listitem")).toHaveLength(5);
    const all = await showAll("Trading now");
    expect(all.getByText("Live idea 7")).toBeInTheDocument();
  });

  it("leads with header cards: live split by book, shadow count, tests and the critic", async () => {
    serve(ROWS);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    const live = await screen.findByRole("region", { name: "Live" });
    expect(live).toHaveTextContent("1");
    expect(live).toHaveTextContent("1 main · 1 on $1M");
    // A missing figure is a dash, never a 0 (the test double answers every URL with the idea list).
    expect(screen.getByRole("region", { name: "Tests under the current bar" })).toHaveTextContent("—");
    expect(screen.queryByRole("region", { name: "Needs label" })).not.toBeInTheDocument();
  });

  it("shows the record counts and the critic in the cards, public", async () => {
    serveRoutes({
      "/api/ideas": ROWS,
      "/api/ideas/summary": { tested: 10, passed: 1, failed: 8, not_enough_data: 1, published: 1 },
      "/api/ideas/critic-summary": { counts: { PAUSE: 1, WATCH: 2, HOLD: 3 }, units: 6, worst: [{ idea_id: 1, title: "Gold beats SPY", book: "main", degradation: -3.2 }] },
    });
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    const tests = await screen.findByRole("region", { name: "Tests under the current bar" });
    await waitFor(() => expect(tests).toHaveTextContent("1 PASS"));
    expect(tests).toHaveTextContent("8 fail · 1 not enough data");
    const critic = screen.getByRole("region", { name: "Weekly critic" });
    expect(critic).toHaveTextContent("1 pause");
    expect(critic).toHaveTextContent("2 watch · 3 hold");
    fireEvent.click(screen.getByRole("button", { name: "Open Weekly critic" }));
    expect(await screen.findByText("-3.2 vs claim")).toBeInTheDocument();
  });

  it("sorts the standing list by performance or significance on request", async () => {
    serve(ROWS);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    const all = await showAll("Trading now");
    // The hero caption carries the permutation p.
    expect(all.getByText(/p < 0\.001/)).toBeInTheDocument();
    const mainTitles = () => [...document.querySelectorAll("h3")].map((h) => h.textContent)
      .filter((t) => t === "Gold beats SPY");
    fireEvent.change(all.getByLabelText("Sort"), { target: { value: "value" } });
    expect(all.getByText(/Standing ideas/)).toBeInTheDocument();
    expect(mainTitles()).toEqual(["Gold beats SPY"]);
    fireEvent.change(all.getByLabelText("Sort"), { target: { value: "p" } });
    expect(mainTitles()).toEqual(["Gold beats SPY"]);
  });

  it("shows a demoted PASS as failing now, with the reason on the card", async () => {
    serve([{ ...ROWS[0], id: 50, title: "NVDA call spread", latest_verdict: "PASS", verdict_now: "FAIL",
             wf_ok: false, fdr_pass: true, status: "backtest" }]);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    const all = await showAll("In shadow");
    fireEvent.click(all.getByRole("button", { name: /^Removed/ }));
    expect(all.getByText("NVDA call spread")).toBeInTheDocument();
    expect(all.getByText(/Removed under the current standard/)).toBeInTheDocument();
    expect(all.getByText(/Passed as run — demoted under the hub-wide standard/)).toBeInTheDocument();
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
    const all = await showAll("In shadow");
    expect(all.getByText(/One bet · MU · TXN/)).toBeInTheDocument();
    expect(all.getByText("TXN and MU wrap")).toBeInTheDocument();
    expect(all.getByText("MU TXN TSM sleeve")).toBeInTheDocument();
    expect(all.getByText(/Standalone/)).toBeInTheDocument();
    expect(all.getByText("Energy ballast")).toBeInTheDocument();
  });

  it("leads with the ideas trading now, then groups the shadow ones by bet, sector or tag", async () => {
    const pass = { latest_verdict: "PASS", verdict_now: "PASS", status: "tracking", live_at: null, live: null, live_books: [] };
    serve([
      { ...ROWS[1], id: 38, title: "Utilities and health care", live_books: ["main"], sector: "Utilities", tags: ["Defensive"],
        family: { key: 7, size: 2, tickers: ["XLU", "XLV"], members: [38, 53] } },
      { ...ROWS[1], ...pass, id: 53, title: "Staples and utilities", sector: "Utilities", tags: ["Defensive", "Rates"],
        family: { key: 7, size: 2, tickers: ["XLU", "XLV"], members: [38, 53] } },
      { ...ROWS[1], ...pass, id: 54, title: "Micron sleeve", sector: "Technology", tags: [],
        family: { key: 22, size: 1, tickers: ["MU"], members: [54] } },
    ]);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    // On the page: one trading row, and the shadow list peeks the best idea of each bet.
    expect(await screen.findByRole("region", { name: "Trading now" })).toHaveTextContent("Utilities and health care");
    expect(screen.getByRole("region", { name: "In shadow" })).toHaveTextContent("Staples and utilities");
    const all = await showAll("In shadow");
    const trading = all.getByRole("region", { name: "Trading now" });
    expect(trading).toHaveTextContent("Utilities and health care");
    expect(trading).not.toHaveTextContent("Staples and utilities");
    const shadow = all.getByRole("region", { name: "In shadow" });
    expect(shadow).toHaveTextContent(/One bet · XLU · XLV/);
    expect(shadow).toHaveTextContent(/lead trading above/);

    fireEvent.change(all.getByLabelText("Group by"), { target: { value: "sector" } });
    expect(all.getByRole("region", { name: "In shadow" })).toHaveTextContent(/Utilities · 1/);
    expect(all.getByRole("region", { name: "In shadow" })).toHaveTextContent(/Technology · 1/);

    fireEvent.change(all.getByLabelText("Group by"), { target: { value: "tag" } });
    const byTag = all.getByRole("region", { name: "In shadow" });
    expect(byTag).toHaveTextContent(/Defensive · 1/);
    expect(byTag).toHaveTextContent(/Rates · 1/);
    expect(byTag).toHaveTextContent(/No tag · 1/);
  });

  it("labels gate overrides, hindsight selection and the registry position", async () => {
    serve([{ ...ROWS[1], gate_overridden: true, hindsight_selected: true,
             registry: { test_number: 58, tests_total: 63 } }]);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    const all = await showAll("Trading now");
    expect(all.getByText("Gold beats SPY")).toBeInTheDocument();
    expect(all.getByText("Gate overridden")).toBeInTheDocument();
    expect(all.getByText("Hindsight-selected")).toBeInTheDocument();
    expect(all.getByText(/test #58 of 63/)).toBeInTheDocument();
  });

  it("labels a paper record too early below 30 days instead of calling its claim failing", async () => {
    serve([{ ...ROWS[1], live: { ...LIVE, days: 12, return_pct: -2.4, bench_return_pct: 1.1, claim: null, failing: true } }]);
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    const all = await showAll("Trading now");
    expect(all.getByText("Too early to say")).toBeInTheDocument();
    expect(all.getByText("−2.4%")).toBeInTheDocument();
    expect(all.getByText(/12 days/)).toBeInTheDocument();
    expect(all.queryByText("Claim failing on paper")).not.toBeInTheDocument();
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
    const all = await showAll("Trading now");
    expect(all.getByText(/No paper days recorded since going live/)).toBeInTheDocument();
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
    expect(await screen.findAllByText("Chips on a leash")).not.toHaveLength(0);
    const all = await showAll("In shadow");
    expect(all.getByText("Tracking since 2026-11-02")).toBeInTheDocument();
    expect(all.getByText("Forward")).toBeInTheDocument();
    expect(all.getByText("+3.4%")).toBeInTheDocument();
    expect(all.getByText(/Claim holding/)).toBeInTheDocument();
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

describe("Idea page lists stay at 5 rows (DESIGN-RULES 3)", () => {
  const mkRun = (n: number) => ({ variation: n, verdict: "FAIL", created_at: "2026-10-30T00:00:00Z", headline: `Run headline ${n}`, p: 0.3, bar: 0.05, claim: "beats_benchmark" });
  const mkTrade = (n: number) => ({ symbol: `T${n}`, qty: 1, entry_price: 1, exit_price: 2, pnl: 1, return_pct: 1, exited_at: "2026-11-10T15:00:00Z", held_days: 1, idea: "x" });
  const page = () => render(<MemoryRouter initialEntries={["/ideas/1"]}><Routes><Route path="/ideas/:id" element={<IdeaRecord />} /></Routes></MemoryRouter>);

  it("shows the newest 5 runs and 5 paper trades, and Show all has the rest", async () => {
    serve({ ...ROWS[1], plain_words: "Gold.", shadow: null, runs: [1, 2, 3, 4, 5, 6, 7].map(mkRun), trades: [1, 2, 3, 4, 5, 6, 7].map(mkTrade) });
    page();
    const runs = await screen.findByRole("region", { name: "Every backtest run" });
    expect(within(runs).getAllByRole("listitem")).toHaveLength(5);
    expect(within(runs).getByText("Run headline 7")).toBeInTheDocument();
    expect(within(runs).queryByText("Run headline 1")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all Every backtest run" }));
    expect(await within(screen.getByRole("dialog")).findByText("Run headline 1")).toBeInTheDocument();
    cleanup();
    serve({ ...ROWS[1], plain_words: "Gold.", shadow: null, runs: [], trades: [1, 2, 3, 4, 5, 6, 7].map(mkTrade) });
    page();
    const trades = await screen.findByRole("region", { name: "Paper trades on this idea" });
    expect(within(trades).getAllByRole("listitem")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "Show all Paper trades on this idea" }));
    expect(await within(screen.getByRole("dialog")).findByText("T7")).toBeInTheDocument();
  });

  it("leads with the three stats and the paper chart before any tab", async () => {
    serve({ ...ROWS[1], plain_words: "Gold.", runs: [], trades: [], latest_verdict: "PASS",
            shadow: { ...LIVE, curve: [{ t: "2026-11-03", idea: 0.1, bench: 0.2 }, { t: "2026-11-04", idea: 0.5, bench: 0.3 }], exits: [] } });
    page();
    expect(await screen.findByText("Verdict now")).toBeInTheDocument();
    expect(screen.getByText("Paper return vs benchmark").nextSibling).toHaveTextContent("+4.2% vs +6.1%");
    expect(screen.getByRole("region", { name: "Paper or forward record" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Record" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("betLead", () => {
  const idea = (id: number, status: string, value: number) =>
    ({ id, status, result_value: value, live_books: status === "live" ? ["big"] : [] }) as unknown as PublicIdea;

  it("picks the idea trading now, else the best unseen result", () => {
    expect(betLead([idea(1, "backtest", 9), idea(2, "live", 1)]).id).toBe(2);
    expect(betLead([idea(1, "backtest", 2), idea(2, "tracking", 5)]).id).toBe(2);
  });
});

describe("Ideas standing", () => {
  it("keeps a failing idea in view while it trades, and clears a failing tracked one", () => {
    const failing = { verdict_now: "FAIL", latest_verdict: "PASS" };
    expect(standing({ ...failing, status: "tracking", live_books: ["big"] } as unknown as PublicIdea)).toBe(true);
    expect(standing({ ...failing, status: "tracking", live_books: [] } as unknown as PublicIdea)).toBe(false);
  });

  it("clears even a passing idea once it is removed from tracking (issue #601)", () => {
    const passing = { verdict_now: "PASS", latest_verdict: "PASS", live_books: [] };
    expect(standing({ ...passing, untracked_at: null } as unknown as PublicIdea)).toBe(true);
    expect(standing({ ...passing, status: "untracked", untracked_at: "2026-11-24T00:00:00Z" } as unknown as PublicIdea)).toBe(false);
  });
});

const DASH = {
  ideas: { total: 53, live: 3, live_big: 1, tracking: 28, published: 0, draft: 20, killed: 1 },
  runs: { total: 98, saved: 61, latest_verdicts: { PASS: 12, FAIL: 30 }, latest_verdicts_as_run: { PASS: 45, FAIL: 10 },
          recent: [{ idea_id: 9, title: "A draft under test", verdict: "FAIL", at: "2026-11-20T00:00:00Z" }] },
  fills: { state: "live", total: 30, attributed: 12, needs_label: 2, closed_pnl_by_idea: [{ idea: "Live one", pnl: 100, trades: 2 }] },
  screens: { total: 2, promoted: 1 }, manual_actions_open: 1,
};
const WROWS = [
  { id: 1, title: "Gold when rates rise", created_at: "", runs: 4, latest_verdict: "PASS", verdict_now: "FAIL", published_at: null, tracked_at: null, live_at: null, killed_at: null },
  { id: 2, title: "TXN + MU wrap", created_at: "", runs: 1, latest_verdict: "PASS", published_at: "2026-11-01", tracked_at: "2026-11-02", live_at: null, killed_at: null,
    batch: { id: "random-lab-gen-3", trial: 54, size: 15, position: 3 } },
];

describe("Ideas, signed in as the owner (the old Workshop list)", () => {
  const admin = (extra: Record<string, unknown> = {}) => {
    session.token = "jwt";
    return serveRoutes({
      "/api/admin/me": { ok: true }, "/api/ideas": ROWS, "/api/workshop/ideas": WROWS, "/api/workshop/dashboard": DASH, ...extra,
    });
  };

  it("lists every idea, drafts included, linked to the idea page, through the signed fetch", async () => {
    const f = admin();
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    const all = await showAll("In shadow");
    fireEvent.click(await all.findByRole("button", { name: "All incl. drafts" }));
    expect(await all.findByText("Gold when rates rise")).toBeInTheDocument();
    expect(all.getByText("4 runs")).toBeInTheDocument();
    expect(all.getByText("as run PASS")).toBeInTheDocument();  // A2: the chip reads the current bar, the as-run verdict beside it
    expect(all.getByText("FAIL")).toBeInTheDocument();
    expect(all.getByText(/Trial 3 of 15 in random-lab-gen-3 · lab trial 54/)).toBeInTheDocument();  // A3
    expect(all.getByRole("link", { name: /Gold when rates rise/ })).toHaveAttribute("href", "/ideas/1");
    const call = f.mock.calls.find(([u]) => String(u).includes("/api/workshop/ideas"));
    expect((call?.[1] as RequestInit).headers).toMatchObject({ Authorization: "Bearer jwt" });
  });

  it("opens the new-idea box from a small button, not on the page", async () => {
    admin();
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(screen.queryByLabelText("Type an idea in plain words")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /New idea/ }));
    expect(await screen.findByLabelText("Type an idea in plain words")).toBeInTheDocument();
  });

  it("leads with totals: tests under the current bar with the as-run tally, and the needs-label count", async () => {
    admin();
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    const tests = await screen.findByRole("region", { name: "Tests under the current bar" });
    await waitFor(() => expect(tests).toHaveTextContent("12 PASS"));
    expect(tests).toHaveTextContent(/as run 45 PASS/);
    expect(tests).toHaveTextContent("30 fail");
    expect(screen.getByRole("region", { name: "Needs label" })).toHaveTextContent("2");
    fireEvent.click(screen.getByRole("button", { name: "Open Tests under the current bar" }));
    expect(await screen.findByText("Tests kept")).toBeInTheDocument();
    expect(screen.getByText("61")).toBeInTheDocument();
  });

  it("shows closed paper P&L by idea inside the Live card, and test activity with drafts on the page", async () => {
    admin();
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findByText("A draft under test")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Open Live" }));
    expect(await screen.findByText("Closed paper P&L by idea")).toBeInTheDocument();
    expect(screen.getByText("Live one")).toBeInTheDocument();
  });

  it("relabels a fill to an idea from the Needs label card", async () => {
    const f = admin({
      "/api/workshop/fills": { state: "live", fills: [{ order_id: "o-1", symbol: "GLD", side: "buy", qty: 10, price: 300, at: "2026-11-02T15:00:00Z", tag: null, idea_id: null, idea: "No idea yet (manual)", history: [] }] },
      "/api/workshop/labels": {},
    });
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Open Needs label" }));
    const pick = await screen.findByLabelText("Idea for GLD buy 10 on 2026-11-02");
    await waitFor(() => expect(within(pick).getByRole("option", { name: "Gold when rates rise" })).toBeInTheDocument());
    fireEvent.change(pick, { target: { value: "1" } });
    await waitFor(() => expect(posts(f)).toContainEqual([expect.stringContaining("/api/workshop/labels"), JSON.stringify({ order_id: "o-1", idea_id: 1 })]));
  });

  it("keeps the sector tone as a card that opens the panel", async () => {
    admin({ "/api/workshop/tone": { as_of: "2026-11-24", sectors: [{ sector: "Energy", basket: "energy", etf: "XLE", tone_day: "2026-11-24", tone: -1.2, z: -1.8 }] } });
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Open Sector tone" }));
    const view = within(await screen.findByRole("dialog", { name: "Sector news tone" }));
    expect(await view.findByText("XLE")).toBeInTheDocument();
  });

  it("a visitor never sends an admin request or sees admin cards", async () => {
    const f = serveRoutes({ "/api/ideas": ROWS });
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findAllByText("Gold beats SPY")).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: /New idea/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Needs label" })).not.toBeInTheDocument();
    expect(f.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/api/workshop"))).toEqual([]);
    for (const l of screen.getAllByRole("link", { name: "Gold beats SPY" })) expect(l).toHaveAttribute("href", "/ideas/1");
  });
});

describe("Workshop routes", () => {
  it("/workshop lands on Ideas and the nav has no Workshop entry", async () => {
    serveRoutes({ "/api/ideas": [] });
    window.history.pushState({}, "", "/workshop");
    await act(async () => { render(<App />); });
    expect(await screen.findByRole("heading", { name: "Ideas" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^workshop$/i })).not.toBeInTheDocument();
  });

  it("/workshop/1 sends a visitor to the public idea page: no Test or Lifecycle tab, no owner requests", async () => {
    const f = serveRoutes({ "/api/ideas/1": { id: 1, title: "Gold", plain_words: "Gold beats stocks", status: "backtest", kind: "long_only", claim: null, variations: 1, runs: [], trades: [], shadow: null } });
    window.history.pushState({}, "", "/workshop/1");
    await act(async () => { render(<App />); });
    expect(await screen.findByRole("tab", { name: "Record" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/ideas/1");
    expect(screen.queryByRole("tab", { name: "Test" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Lifecycle" })).not.toBeInTheDocument();
    expect(f.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/api/workshop"))).toEqual([]);
  });
});

describe("TradeLabels", () => {
  it("shows only the fills that need a label", async () => {
    const fill = (order_id: string, symbol: string, side: string, qty: number, tag: string | null): FillRow =>
      ({ order_id, symbol, side, qty, price: 10, at: "2026-11-02T00:00:00Z", tag, idea_id: null, idea: null, history: [] }) as unknown as FillRow;
    session.token = "jwt";
    serveRoutes({ "/api/workshop/fills": { state: "live", fills: [fill("a", "GLD", "buy", 3, "idea-1-auto-x"), fill("b", "SPY", "buy", 1, "ext-9"), fill("c", "QQQ", "sell", 2, null)] } });
    render(<TradeLabels ideas={[]} />);
    expect(await screen.findByText(/QQQ sell 2/)).toBeInTheDocument();
    expect(screen.queryByText(/GLD buy 3/)).not.toBeInTheDocument();
    expect(screen.queryByText(/SPY buy 1/)).not.toBeInTheDocument();
    expect(screen.getByText(/2 fills already attributed/)).toBeInTheDocument();
  });
});
