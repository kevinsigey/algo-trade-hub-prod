import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Strategies from "@/pages/Strategies";

const GAP_SCORE = { n: 0, model_brier: null, market_brier: null, brier_delta: null,
                    model_log_loss: null, market_log_loss: null, calibration: [] };
const gapPos = (ticker: string, category: string, pnl: number) => ({
  ticker, category, side: "yes", model_at_entry: 0.7, entry_price: 0.6, gap_pts: 12,
  contracts: 100, exit_state: null, pnl });

const BODIES: Record<string, unknown> = {
  "/api/portfolio": { state: "live", as_of: "2026-11-05T21:00:00Z", scoreboard: { equity: 97706, return_pct: -2.3, ahead_pts: 1.4 },
                      positions: [], curve: [], composition: [] },
  "/api/ideas": [{ id: 17, live: { state: "live" }, live_books: ["main"] }, { id: 36, live: { state: "live" }, live_books: [] }],
  "/api/oil/fifteen-rule": { rule: "Buy the side the model beats by 10.", prereg_at: "2026-11-06T00:00:00+00:00", ready_trades: 300,
                             replay: { n: 51, net_per_contract: 0.0967 }, forward: { n: 10, net_per_contract: 0.05 }, pending: 0, recent: [],
                             by_series: { WTI: { n: 3, net_per_contract: 0.03, win_rate: 0.5 },
                                          Brent: { n: 1, net_per_contract: -0.02, win_rate: 0 },
                                          "Natural gas": { n: 6, net_per_contract: 0.19, win_rate: 0.67 } },
                             gate: { rule: "gated", forward: { n: 7, net_per_contract: 0.14, win_rate: 0.57 },
                                     by_series: { WTI: { n: 2, net_per_contract: 0.05, win_rate: 0.5 },
                                                  Brent: { n: 0, net_per_contract: null, win_rate: null },
                                                  "Natural gas": { n: 5, net_per_contract: 0.2, win_rate: 0.6 } } } },
  "/api/oil/itm-record": { frozen: 24, settled: 24, hits: 9, hit_rate: 0.375, net_per_contract: 0.0188, backtest: null, recent: [] },
  "/api/gaps/desk": { as_of: "2026-11-05T21:00:00Z", started_at: "2026-11-04T12:15:00Z",
                      evidence: { status: "NOT ENOUGH EVIDENCE", days: 1.8, pairs: 1834, min_days: 28, min_pairs: 150 },
                      grade: { all: GAP_SCORE, crypto: GAP_SCORE, oil: GAP_SCORE },
                      ledger: { bankroll: 8114.82, return_pct: -18.85, max_drawdown_pct: 20, resolved: 3, open: 0, win_rate: 0.33, avg_entry_gap_pts: 12 },
                      fee_basis: "net", open_positions: [], top_gaps: [], near_misses: [], funnel: {},
                      closed_positions: [gapPos("KXBR-A", "oil", 120.5), gapPos("KXWTI-B", "oil", -40), gapPos("KXBTC-C", "crypto", -260)] },
  "/api/journal": { as_of: "2026-11-05T21:00:00Z", headline: {},
                    forecasters: [{ forecaster: "oil_wti_15m", forecaster_version: "wti-15m-v2", cadence: "15min",
                                    baseline: "kalshi", n_targets: 1000, n_settled: 969, brier: 0.0975,
                                    brier_baseline: 0.2396, brier_on_baseline: 0.0975, n_baseline: 918, bss: null,
                                    gap: -0.1421, reliability: [], murphy: {}, calibration_ready: true,
                                    gate_status: "PROMOTED", gate_reasons: [], computed_at: "2026-11-05T21:00:00Z" }] },
  "/api/crypto/sniper-verdict": { overall: { count: 18602, hit_rate: 0.548 } },
};

function serve(overrides: Record<string, unknown> = {}) {
  const bodies = { ...BODIES, ...overrides };
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => {
    const key = Object.keys(bodies).sort((a, b) => b.length - a.length).find((k) => String(url).includes(k));
    return new Response(JSON.stringify(key ? bodies[key] : {}), { status: key ? 200 : 404 });
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("Strategies", () => {
  it("lists every strategy with its stage and its record, each linked to its detail", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Strategies", level: 1 })).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    expect(await within(list).findByText(/\+1\.4 pts vs SPY/)).toBeInTheDocument();
    expect(within(list).getByText(/1 idea trading/)).toBeInTheDocument();
    expect(await within(list).findByText(/9 of 24 hit/)).toBeInTheDocument();
    expect(await within(list).findByText(/18,602 graded/)).toBeInTheDocument();
    for (const stage of ["Live paper account", "Paper record", "Picks only", "Retired"]) {
      expect(within(list).getAllByText(stage).length).toBeGreaterThan(0);
    }
  });

  it("splits the 15-minute rule into one row per market, each with its gated record", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    for (const name of [/WTI 15-minute rule/i, /Brent 15-minute rule/i, /Natural gas 15-minute rule/i]) {
      expect(await within(list).findByRole("link", { name })).toHaveAttribute("href", "#fifteen-rule");
    }
    expect(await within(list).findByText(/2 gated trades · \+5\.0¢ a contract · 50% win/)).toBeInTheDocument();
    expect(within(list).getByText(/5 gated trades · \+20\.0¢ a contract · 60% win/)).toBeInTheDocument();
    // Brent has no gated trades yet: its row falls back to the raw record and says so.
    expect(within(list).getByText(/0 gated trades · raw 1 trade · −2\.0¢ a contract/)).toBeInTheDocument();
    expect(within(list).queryByText(/15-minute oil and gas rule/)).not.toBeInTheDocument();
  });

  it("splits the gap tracker into an oil desk and a crypto desk, each with its own record", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    expect(await within(list).findByRole("link", { name: /Oil gap tracker/i })).toHaveAttribute("href", "#gap-oil");
    expect(within(list).getByRole("link", { name: /Crypto gap tracker/i })).toHaveAttribute("href", "#gap-crypto");
    expect(await within(list).findByText(/2 closed · \+\$80\.50 realized · 50% won/)).toBeInTheDocument();
    expect(within(list).getByText(/1 closed · −\$260\.00 realized · 0% won/)).toBeInTheDocument();
    expect(within(list).queryByText(/oil and crypto/)).not.toBeInTheDocument();
    // Both desks render below, each with its own heading.
    expect(await screen.findByText("Oil gap tracker", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByText("Crypto gap tracker", { selector: "h2" })).toBeInTheDocument();
  });

  it("states the gap rule with the fee outside the entry test and the one-hour exit", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    // Both desks state the corrected rule: the 8-point entry gap is measured gross (fees come
    // out of the trade's P&L), 2+ hours is the entry cutoff, and the near-settlement exit is 1 hour.
    expect(await within(list).findAllByText(/fees come out of the trade's P&L, not the test/)).toHaveLength(2);
    expect(within(list).getAllByText(/only with 2\+ hours to settlement and a book deep enough to exit/)).toHaveLength(2);
    expect(within(list).getAllByText(/under an hour is left/)).toHaveLength(2);
    // The two shipped errors are gone.
    expect(within(list).queryByText(/8\+ points after the fee/)).toBeNull();
    expect(within(list).queryByText(/2 hours before settlement/)).toBeNull();
  });

  it("reads each gap desk's record from the server ledger when the payload carries one", async () => {
    // The capped closed-positions page would compute 2 oil / 1 crypto; the server ledger is
    // computed over every closed position and wins.
    serve({ "/api/gaps/desk": { ...(BODIES["/api/gaps/desk"] as Record<string, unknown>),
      ledger_by_category: { oil: { closed: 21, realized: -667.95, win_rate: 0.5238, median_pnl: -12.5 },
                            crypto: { closed: 20, realized: -2509.22, win_rate: 0.2, median_pnl: -95 } } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    expect(await within(list).findByText(/21 closed · −\$667\.95 realized · 52% won · typical trade −\$12\.50/)).toBeInTheDocument();
    expect(within(list).getByText(/20 closed · −\$2509\.22 realized · 20% won · typical trade −\$95\.00/)).toBeInTheDocument();
  });

  it("shows the 15-minute settlements scoring as a chart in the fifteen section", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const chart = within(await screen.findByLabelText("15-minute settlements scoring"));
    expect(chart.getByText(/969 settled/)).toBeInTheDocument();
    expect(chart.getByText(/model ahead/)).toBeInTheDocument();
  });
});
