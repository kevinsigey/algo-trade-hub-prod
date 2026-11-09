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
  it("shows every strategy as a tile with its stage and its record", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Strategies", level: 1 })).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    expect(await within(list).findByText((_, el) => el?.tagName === "P" && /\+1\.4 pts vs SPY since start/.test(el.textContent ?? ""))).toBeInTheDocument();
    expect(within(list).getByText(/1 idea trading/)).toBeInTheDocument();
    expect(await within(list).findByText(/9 of 24 hit/)).toBeInTheDocument();
    expect(await within(list).findByText(/18,602 graded/)).toBeInTheDocument();
    for (const stage of ["Live paper account", "Paper record", "Picks only", "Retired"]) {
      expect(within(list).getAllByText(stage).length).toBeGreaterThan(0);
    }
    for (const name of ["Stock ideas", "15-minute rules — oil & gas", "WTI hourly best strike",
                        "Kalshi gap tracker", "Sports picks", "Crypto sniper"]) {
      expect(within(list).getByText(name)).toBeInTheDocument();
    }
  });

  it("keeps the explanations under the tile expansions, collapsed except the live tile", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    const rule = await within(list).findByText(/Five minutes into each 15-minute WTI window/);
    const fifteenDetails = rule.closest("details");
    expect(fifteenDetails).not.toBeNull();
    expect(fifteenDetails!.open).toBe(false);
    const stockDetails = within(list).getByText(/Workshop ideas that cleared their gates/).closest("details");
    expect(stockDetails).not.toBeNull();
    expect(stockDetails!.open).toBe(true);
  });

  it("splits the 15-minute tile into one market block per market, each with its gated record", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    const tile = (await within(list).findByText("15-minute rules — oil & gas")).closest("li");
    expect(tile).not.toBeNull();
    expect(tile!.id).toBe("fifteen-rule");
    for (const label of ["WTI", "Brent", "Natural gas"]) {
      // Once in the tile's summary bars, once in the trade record's by-market table below.
      expect(within(tile!).getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(await within(list).findByText(/2 gated trades · \+5\.0¢ a contract · 50% win/)).toBeInTheDocument();
    expect(within(list).getByText(/5 gated trades · \+20\.0¢ a contract · 60% win/)).toBeInTheDocument();
    // Brent has no gated trades yet: its block falls back to the raw record and says so.
    expect(within(list).getByText(/0 gated trades · raw 1 trade · −2\.0¢ a contract/)).toBeInTheDocument();
    expect(within(list).queryByText(/15-minute oil and gas rule/)).not.toBeInTheDocument();
    // The tile headline is the family gated record with the raw record beside it as the control.
    expect(within(list).getByText(/7 gated trades · \+14\.0¢ a contract · 57% win · raw control 10 · \+5\.0¢ a contract/)).toBeInTheDocument();
  });

  it("adds a metals tile in the same visual form when the fifteen payload carries the metals block", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    serve({ "/api/oil/fifteen-rule": { ...base,
      metals: { prereg_at: "2026-11-09T19:55:00+00:00", ready_trades: 300,
                by_series: { Gold: { n: 4, net_per_contract: 0.11, win_rate: 0.75 },
                             Silver: { n: 2, net_per_contract: -0.05, win_rate: 0.5 },
                             Copper: { n: 0, net_per_contract: null, win_rate: null } },
                gate: { forward: { n: 4, net_per_contract: 0.1025, win_rate: 0.75 },
                        by_series: { Gold: { n: 3, net_per_contract: 0.13, win_rate: 0.67 },
                                     Silver: { n: 0, net_per_contract: null, win_rate: null },
                                     Copper: { n: 1, net_per_contract: 0.02, win_rate: 1 } } } } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    const tile = (await within(list).findByText("15-minute metals rule")).closest("li");
    expect(tile).not.toBeNull();
    expect(tile!.id).toBe("fifteen-metals");
    for (const label of ["Gold", "Silver", "Copper"]) {
      expect(within(tile!).getByText(label)).toBeInTheDocument();
    }
    expect(within(tile!).getByText(/3 gated trades · \+13\.0¢ a contract · 67% win/)).toBeInTheDocument();
    expect(within(tile!).getByText(/0 gated trades · raw 2 trades · −5\.0¢ a contract/)).toBeInTheDocument();
    // The tile headline is the metals block's own served aggregate.
    expect(within(tile!).getByText(/4 gated trades · \+10\.3¢ a contract · 75% win/)).toBeInTheDocument();
  });

  it("shows the metals tile accruing, with no borrowed numbers, before its first settled trades", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    serve({ "/api/oil/fifteen-rule": { ...base,
      metals: { prereg_at: "2026-11-09T19:55:00+00:00", ready_trades: 300,
                by_series: { Gold: { n: 0, net_per_contract: null, win_rate: null },
                             Silver: { n: 0, net_per_contract: null, win_rate: null },
                             Copper: { n: 0, net_per_contract: null, win_rate: null } },
                gate: { forward: { n: 0, net_per_contract: null, win_rate: null },
                        by_series: { Gold: { n: 0, net_per_contract: null, win_rate: null },
                                     Silver: { n: 0, net_per_contract: null, win_rate: null },
                                     Copper: { n: 0, net_per_contract: null, win_rate: null } } } } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    const tile = (await within(list).findByText("15-minute metals rule")).closest("li");
    expect(tile).not.toBeNull();
    // One per metal, plus the tile headline itself.
    expect(within(tile!).getAllByText(/Accruing — no settled gated trades yet/)).toHaveLength(4);
  });

  it("draws the stock ideas curve when the portfolio payload carries one", async () => {
    serve({ "/api/portfolio": { ...(BODIES["/api/portfolio"] as Record<string, unknown>),
      curve: [{ t: "2026-09-01", portfolio_pct: 0, spy_pct: 0 },
              { t: "2026-10-01", portfolio_pct: 2.1, spy_pct: 1.2 },
              { t: "2026-11-01", portfolio_pct: 1.4, spy_pct: 0 }] } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    expect(await within(list).findByRole("img", { name: "Portfolio curve against SPY" })).toBeInTheDocument();
  });

  it("splits the gap tracker into an oil desk and a crypto desk, each with its own record", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = screen.getByRole("list", { name: "Strategies at a glance" });
    expect(await within(list).findByText(/2 closed · \+\$80\.50 realized · 50% won/)).toBeInTheDocument();
    expect(within(list).getByText(/1 closed · −\$260\.00 realized · 0% won/)).toBeInTheDocument();
    expect(within(list).queryByText(/oil and crypto/)).not.toBeInTheDocument();
    // Both desks render in the tile's expansion, each with its own heading.
    expect(await screen.findByText("Oil gap tracker", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByText("Crypto gap tracker", { selector: "h2" })).toBeInTheDocument();
    // The tile headline is the combined realized record across both desks.
    expect(within(list).getByText(/−\$179\.50/)).toBeInTheDocument();
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
