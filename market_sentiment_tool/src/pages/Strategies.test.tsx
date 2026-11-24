import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Strategies from "@/pages/Strategies";

const auth = vi.hoisted(() => ({ token: null as string | null }));
vi.mock("@/components/RequireAdmin", () => ({ sessionToken: async () => auth.token }));

const GAP_SCORE = { n: 0, model_brier: null, market_brier: null, brier_delta: null,
                    model_log_loss: null, market_log_loss: null, calibration: [] };
const gapPos = (ticker: string, category: string, pnl: number, exit_reason: string) => ({
  ticker, category, side: "yes", model_at_entry: 0.7, entry_price: 0.6, gap_pts: 12,
  contracts: 100, exit_state: null, exit_reason, pnl });

const BODIES: Record<string, unknown> = {
  "/api/portfolio": { state: "live", as_of: "2026-11-05T21:00:00Z", scoreboard: { equity: 97706, return_pct: -2.3, ahead_pts: 1.4 },
                      positions: [], curve: [], composition: [] },
  "/api/ideas": [{ id: 17, live: { state: "live" }, live_books: ["main"] }, { id: 36, live: { state: "live" }, live_books: [] }],
  "/api/oil/fifteen-rule": { rule: "Buy the side the model beats by 10.", prereg_at: "2026-11-06T00:00:00+00:00", ready_trades: 300,
                             replay: { n: 51, net_per_contract: 0.0967 },
                             forward: { n: 10, net_per_contract: 0.05, total: 0.5, win_rate: 0.5, low95: -0.04, windows: 9 },
                             pending: 1,
                             recent: [{ series: "WTI", target: "2026-11-08T15:15:00Z", frozen_at: "2026-11-08T15:05:00Z",
                                        side: "yes", cost: 0.4, model: 0.62, outcome: 1, pnl: 0.55 }],
                             by_series: { WTI: { n: 3, net_per_contract: 0.03, win_rate: 0.5 },
                                          Brent: { n: 1, net_per_contract: -0.02, win_rate: 0 },
                                          "Natural gas": { n: 6, net_per_contract: 0.19, win_rate: 0.67 } },
                             by_session: { open: { n: 4, net_per_contract: 0.1, win_rate: 0.75 },
                                           closed: { n: 6, net_per_contract: 0.02, win_rate: 0.5 } },
                             gate: { rule: "gated", forward: { n: 7, net_per_contract: 0.14, total: 0.98, win_rate: 0.57, low95: 0.021, windows: 7 },
                                     by_series: { WTI: { n: 2, net_per_contract: 0.05, win_rate: 0.5 },
                                                  Brent: { n: 0, net_per_contract: null, win_rate: null },
                                                  "Natural gas": { n: 5, net_per_contract: 0.2, win_rate: 0.6 } } },
                             bar: { basis: "gated", trades: 7, ready_trades: 300, ready: false, low95: 0.021, windows: 7, pending: 2,
                                    control: { basis: "raw", trades: 10, ready: false, low95: -0.04 } },
                             decisions: { recorded: 489, buy: 56, skip: 433, by_reason: { no_edge: 403, halt: 27, no_quote: 3 } },
                             offsets: { by_offset: [
                               { offset_min: 1, windows: 90, priced: 88, mean_edge_net: 0.028, n: 17, net_per_contract: 0.195, win_rate: 0.71 },
                               { offset_min: 5, windows: 96, priced: 96, mean_edge_net: 0.09, n: 30, net_per_contract: 0.08, win_rate: 0.6 } ] } },
  "/api/oil/itm-record": { frozen: 24, settled: 24, hits: 9, hit_rate: 0.375, net_per_contract: 0.0188, backtest: null, recent: [] },
  "/api/gaps/desk": { as_of: "2026-11-05T21:00:00Z", started_at: "2026-11-04T12:15:00Z", entries_paused: true,
                      evidence: { status: "NOT ENOUGH EVIDENCE", days: 1.8, pairs: 1834, min_days: 28, min_pairs: 150 },
                      grade: { all: GAP_SCORE, crypto: { ...GAP_SCORE, n: 2369, brier_delta: 0.0022 },
                               oil: { ...GAP_SCORE, n: 2055, brier_delta: 0.0233 } },
                      ledger: { bankroll: 8114.82, return_pct: -18.85, max_drawdown_pct: 20, resolved: 3, open: 0, win_rate: 0.33, avg_entry_gap_pts: 12 },
                      fee_basis: "net", open_positions: [], top_gaps: [], near_misses: [], funnel: {},
                      closed_positions: [gapPos("KXBR-A", "oil", 120.5, "gap_closed"), gapPos("KXWTI-B", "oil", -40, "model_moved"),
                                         gapPos("KXBTC-C", "crypto", -260, "model_moved")] },
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

afterEach(() => { vi.unstubAllGlobals(); auth.token = null; });

describe("Strategies", () => {
  it("shows every strategy as a tile with its stage and its record", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Strategies", level: 1 })).toBeInTheDocument();
    const list = document.body;
    expect(await within(list).findByText((_, el) => el?.tagName === "P" && /\+1\.4 pts vs SPY since start/.test(el.textContent ?? ""))).toBeInTheDocument();
    expect(within(list).getByText(/1 idea trading/)).toBeInTheDocument();
    expect(await within(list).findByText(/9 of 24 hit/)).toBeInTheDocument();
    expect(await within(list).findByText(/18,602 graded/)).toBeInTheDocument();
    for (const stage of ["Live paper account", "Paper record", "Retired"]) {
      expect(within(list).getAllByText(stage).length).toBeGreaterThan(0);
    }
    for (const name of ["Stock ideas", "15-minute rules — oil & gas", "WTI hourly best strike",
                        "Kalshi gap tracker", "Crypto sniper"]) {
      expect(within(list).getByText(name)).toBeInTheDocument();
    }
  });

  it("keeps every explanation under a collapsed tile expansion", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = document.body;
    const rule = await within(list).findByText(/Five minutes into each 15-minute window, buy the side/);
    const fifteenDetails = rule.closest("details");
    expect(fifteenDetails).not.toBeNull();
    expect(fifteenDetails!.open).toBe(false);
    const stockDetails = within(list).getByText(/Workshop ideas that cleared their gates/).closest("details");
    expect(stockDetails).not.toBeNull();
    expect(stockDetails!.open).toBe(false);
  });

  it("splits the 15-minute tile into one market block per market, each with its gated record", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = document.body;
    const tile = (await within(list).findByText("15-minute rules — oil & gas")).closest("li");
    expect(tile).not.toBeNull();
    expect(tile!.id).toBe("fifteen-rule");
    // The per-market bars render only once the fifteen payload lands; wait for them.
    await within(tile!).findByText(/2 gated trades · \+5\.0¢ a contract · 50% win/);
    for (const label of ["WTI", "Brent", "Natural gas"]) {
      // In the tile's summary bars; the per-market numbers live there, not in a second table below.
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

  it("renders the redesign board: commodity cards with ranked models and simulated accounts", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    const model = (version: string, label: string, trades: number, net: number | null, extra: Record<string, unknown> = {}) => ({
      version, label, series: "KXNATGAS15M", trades, net_cents: net, low95: 1.5, paired_low95: -2,
      fill_short: 1, too_few: trades < 10,
      progress: { n: trades, needed: 100, legs: { n: false, low95: true, paired: false } },
      account: { start: 20, balance: 26.31, drawdown: 2.25, bust: false, curve: [20, 22.5, 26.31], trades_taken: trades },
      ...extra });
    serve({ "/api/oil/fifteen-rule": { ...base, board: { account_start: 20, commodities: [
      { series: "KXNATGAS15M", commodity: "Natural gas", models: [
        model("live", "Live rule", 97, 7.8, { progress: { n: 97, needed: 300, legs: { n: false, low95: true, paired: true } } }),
        model("v4-edge20-shadow", "v4-edge20-shadow", 8, 4.21,
              { fill_short: 0, account: { start: 20, balance: 21.5, drawdown: 0.5, bust: false, curve: [20, 21.5], trades_taken: 8 } }),
      ] } ] } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = document.body;
    const tile = (await within(list).findByText("15-minute rules — oil & gas")).closest("li");
    expect(tile).not.toBeNull();
    // The board sits on the main page under its own heading (#589) -- no
    // <details> needs opening to reach it -- and the oil & gas tile no
    // longer carries the "By commodity" sub-panel.
    const boardSection = await screen.findByRole("region", { name: "15-minute models by commodity" });
    expect(within(boardSection).getByRole("heading", { name: "15-minute models by commodity" })).toBeInTheDocument();
    expect(within(tile!).queryByText("By commodity — every model, ranked", { selector: "summary" })).toBeNull();
    expect(within(tile!).queryByRole("region", { name: "Natural gas models" })).toBeNull();
    const card = within(boardSection).getByRole("region", { name: "Natural gas models" });
    expect(within(card).getByText("Live rule")).toBeInTheDocument();
    expect(within(card).getByText(/97 trades/)).toBeInTheDocument();
    expect(within(card).getByText(/\+7\.8¢/)).toBeInTheDocument();
    expect(within(card).getByText(/97\/300/)).toBeInTheDocument();
    expect(within(card).getByText(/\$26\.31/)).toBeInTheDocument();
    expect(within(card).getByText("too few trades")).toBeInTheDocument();
    expect(within(card).getByText(/fill-short 1/)).toBeInTheDocument();
  });

  it("splits the fifteen expansion into small titled expansions instead of one mega-dropdown", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = document.body;
    const tile = (await within(list).findByText("15-minute rules — oil & gas")).closest("li");
    expect(tile).not.toBeNull();
    // Several of these blocks render only once the fifteen payload lands; wait for one.
    await within(tile!).findByText("The trade record", { selector: "summary" });
    for (const title of ["The rule", "Settlements scoring — the forecasts vs Kalshi's price", "The trade record",
                         "Decisions — every window gets one", "Entry timing — what entering at each minute has paid",
                         "Trading hours vs closed hours"]) {
      const summary = within(tile!).getByText(title, { selector: "summary" });
      const details = summary.closest("details");
      expect(details).not.toBeNull();
      expect(details!.open).toBe(false);
    }
    // The rule is stated once for the whole family, not once per market.
    expect(within(tile!).getAllByText(/Five minutes into each 15-minute window, buy the side/)).toHaveLength(1);
    expect(within(tile!).queryByText(/15-minute WTI window/)).toBeNull();
    expect(within(tile!).queryByText(/15-minute Brent window/)).toBeNull();
    // The old framing prose that restated the layout is gone.
    expect(within(tile!).queryByText(/One rule, three separate markets/)).toBeNull();
    // No by-market table duplicating the tile's per-market bars.
    expect(within(tile!).queryByLabelText("Record by market")).toBeNull();
  });

  it("shows the trade record with the gated record leading, the raw record as control, and the go-live bar", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = document.body;
    const tile = (await within(list).findByText("15-minute rules — oil & gas")).closest("li");
    expect(tile).not.toBeNull();
    expect(await within(tile!).findByText(/7 of 300 settled gated trades in 7 separate 15-minute windows/)).toBeInTheDocument();
    expect(within(tile!).getByText(/still ahead at the low end of its 95% range \(now \+2\.1¢\)/)).toBeInTheDocument();
    expect(within(tile!).getByText(/2 waiting to settle/)).toBeInTheDocument();
    expect(within(tile!).getByText(/On the original gross-edge record, kept as a control: 10 trades, \+5\.0¢ a contract, win rate 50%/)).toBeInTheDocument();
    expect(within(tile!).getByText(/Replay before the rule was fixed: 51 trades, \+9\.7¢ a contract/)).toBeInTheDocument();
    // Decisions: every window gets one, with the skip reasons named once.
    expect(within(tile!).getByText(/489 windows on record: 56 buys, 433 skipped \(no edge 403, no quote 3, halt 27\)/)).toBeInTheDocument();
    // Entry timing: the per-minute table and its best minute, from the offsets block.
    expect(within(tile!).getByLabelText("Entry timing by minute")).toBeInTheDocument();
    expect(within(tile!).getByText(/Best entry minute so far: minute 1 of the window \(17 priced entries, \+19\.5¢ a contract after fees\)/)).toBeInTheDocument();
    // Sessions: the split and its one-line reading survive.
    expect(within(tile!).getByText(/A real edge should hold while futures trade/)).toBeInTheDocument();
  });

  it("no longer shows the killed oil shadow, even if a stale payload carries its block", async () => {
    // v2-oil-shadow was killed on Kevin's ruling (2026-11-17): the
    // endpoint stopped serving the block and the page dropped it.
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    serve({ "/api/oil/fifteen-rule": { ...base,
      shadow: { gate_version: "v2-oil-shadow", prereg_at: "2026-11-09T19:00:00+00:00",
                fresh: { windows: 273, trades: 246, net_per_contract: -0.048, low95: -0.108, win_rate: 0.4 } } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = document.body;
    const tile = (await within(list).findByText("15-minute rules — oil & gas")).closest("li");
    expect(tile).not.toBeNull();
    expect(within(tile!).queryByText("Oil shadow — the minute-1 variant")).not.toBeInTheDocument();
  });

  it("puts the decline monitor in the fifteen tile: v1 rule, blend and challenger per day and market", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    const cell = (trades: number, pnl: number | null) => ({ trades, pnl_per_trade: pnl });
    serve({ "/api/oil/fifteen-rule": { ...base,
      decline: [{ day: "2026-11-12", series: "Natural gas", live: cell(12, 0.025), blend: cell(4, 0.08), volregime: cell(0, null) }] } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = document.body;
    const tile = (await within(list).findByText("15-minute rules — oil & gas")).closest("li");
    await within(tile!).findByText("Day by day — v1 rule, blend and vol-regime challenger", { selector: "summary" });
    const table = within(tile!).getByRole("table", { name: "15-minute decline monitor" });
    expect(within(table).getByText("+2.5¢")).toBeInTheDocument();
    expect(within(table).getByText("+8.0¢")).toBeInTheDocument();
    // The vol-regime challenger's own record no longer rides as prose here;
    // it lives on its commodity card (the redesign board test covers it).
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
    const list = document.body;
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
    const list = document.body;
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
    const list = document.body;
    expect(await within(list).findByRole("img", { name: "Portfolio curve against SPY" })).toBeInTheDocument();
  });

  it("shows the gap tracker as a paused, closed book below the retired entries, with each desk's record", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = document.body;
    expect(await within(list).findByText(/2 closed · \+\$80\.50 realized · 50% won/)).toBeInTheDocument();
    expect(within(list).getByText(/1 closed · −\$260\.00 realized · 0% won/)).toBeInTheDocument();
    expect(within(list).queryByText(/oil and crypto/)).not.toBeInTheDocument();
    // The tile headline is the combined realized record across both desks, as the final record.
    expect(within(list).getByText(/−\$179\.50/)).toBeInTheDocument();
    expect(within(list).getByText(/realized · the final record/)).toBeInTheDocument();
    expect(within(list).getByText(/3 closed · pot \$8,114\.82 of \$10,000/)).toBeInTheDocument();
    // Demoted: muted, chipped as paused with the date, and last in the grid.
    const tile = within(list).getByText("Kalshi gap tracker").closest("li");
    expect(tile).not.toBeNull();
    expect(tile!.id).toBe("gap-tracker");
    expect(tile!.className).toContain("opacity-70");
    expect(within(tile!).getByText(/Paused · Nov 9, 2026/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Retired strategies" }).lastElementChild?.id).toBe("gap-tracker");
    // One post-mortem expansion; the live-desk panels and their framing are gone.
    expect(within(tile!).getByLabelText("Kalshi gap tracker — the record")).toBeInTheDocument();
    expect(within(list).queryByText("Oil gap tracker", { selector: "h2" })).toBeNull();
    expect(within(list).queryByText("Crypto gap tracker", { selector: "h2" })).toBeNull();
    expect(within(list).queryByText(/Largest passing gaps/)).toBeNull();
    expect(within(list).queryByText(/NOT ENOUGH EVIDENCE/)).toBeNull();
  });

  it("states the gap rule once, in past tense, with the fee outside the entry test and the one-hour exit", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = document.body;
    // The post-mortem states the corrected rule once, in past tense: the 8-point entry gap was
    // measured gross (fees came out of the trade's P&L), 2+ hours was the entry cutoff, and the
    // near-settlement exit was 1 hour.
    expect(await within(list).findAllByText(/fees came out of the trade's P&L, not the test/)).toHaveLength(1);
    expect(within(list).getAllByText(/only with 2\+ hours to settlement and a book deep enough to exit/)).toHaveLength(1);
    expect(within(list).getAllByText(/under an hour was left/)).toHaveLength(1);
    expect(within(list).getAllByText(/it bought Brent and WTI, Bitcoin and Ethereum/)).toHaveLength(1);
    // The two shipped errors are gone.
    expect(within(list).queryByText(/8\+ points after the fee/)).toBeNull();
    expect(within(list).queryByText(/2 hours before settlement/)).toBeNull();
  });

  it("gives the gap post-mortem: worse-than-market grades, the churn, and how the trades ended", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = document.body;
    const tile = (await within(list).findByText("Kalshi gap tracker")).closest("li");
    expect(tile).not.toBeNull();
    // Why it was paused, in the grade's own numbers: both desks worse than Kalshi's price.
    // findByText, not getByText: the tile headline renders before the desk payload lands,
    // and the post-mortem copy renders from that payload — asserting synchronously races
    // it on CI (the PR #449 race class).
    expect(await within(tile!).findByText(/each desk's fair values graded worse than Kalshi's/)).toBeInTheDocument();
    expect(within(tile!).getByText(/Brier worse by \+0\.023 on oil and \+0\.002 on crypto/)).toBeInTheDocument();
    // The two desk stories, computed from how their trades ended.
    expect(within(tile!).getByText(/Crypto's exits churned: 1 of its 1 trade ended because the model/)).toBeInTheDocument();
    expect(within(tile!).getByText(/Oil's gap-closed exits were the one working piece: 1 trade, \+\$120\.50/)).toBeInTheDocument();
    expect(within(tile!).getByText(/The WTI hourly lane never fired/)).toBeInTheDocument();
    expect(within(tile!).getByText(/flagged none/)).toBeInTheDocument();
    // The exit-type breakdown, per desk.
    expect(within(tile!).getByText("How the trades ended")).toBeInTheDocument();
    expect(within(tile!).getByText("Gap closed")).toBeInTheDocument();
    expect(within(tile!).getAllByText("Model moved")).toHaveLength(2);
    expect(within(tile!).getByText("−$40.00")).toBeInTheDocument();
    // The closed trades themselves, with how each ended.
    expect(within(tile!).getByText("Closed trades")).toBeInTheDocument();
    expect(within(tile!).getByText("KXBR-A")).toBeInTheDocument();
    expect(within(tile!).getByText(/\+\$120\.50 · gap closed/)).toBeInTheDocument();
    expect(within(tile!).getByText(/−\$260\.00 · model moved/)).toBeInTheDocument();
  });

  it("reads each gap desk's record from the server ledger when the payload carries one", async () => {
    // The capped closed-positions page would compute 2 oil / 1 crypto; the server ledger is
    // computed over every closed position and wins.
    serve({ "/api/gaps/desk": { ...(BODIES["/api/gaps/desk"] as Record<string, unknown>),
      ledger_by_category: { oil: { closed: 21, realized: -667.95, win_rate: 0.5238, median_pnl: -12.5 },
                            crypto: { closed: 20, realized: -2509.22, win_rate: 0.2, median_pnl: -95 } } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = document.body;
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
  it("renders one section per stage, in order", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const headings = ["Real money", "Paper, trading", "On trial (shadows)", "What we learned", "Retired & paused"];
    for (const h of headings) expect(screen.getByText(h)).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    const at = headings.map((h) => text.indexOf(h));
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    expect(screen.getByText(/oil-trend-agree-v1\./)).toBeInTheDocument();
    expect(await screen.findByText("Not proven yet")).toBeInTheDocument();
  });

  it("hides the live pilot's dollars from the public and shows them to admin", async () => {
    const pilot = { state: "live", halted: false, halt_reason: null, balance: 9.87, pnl_since_start: -0.13,
                    decisions: 12, fills: 9, live_net_per_contract: 0.02, paper_net_per_contract: 0.05 };
    serve({ "/api/kalshi-demo": { state: "ok", live_pilot: { admin_only: true } } });
    const { unmount } = render(<MemoryRouter><Strategies /></MemoryRouter>);
    const real = screen.getByRole("region", { name: "Real money" });
    expect(within(real).getByText(/A \$10 live pilot runs .* WTI & Brent/)).toBeInTheDocument();
    expect(within(real).queryByText("$9.87")).toBeNull();
    expect(within(real).getByRole("link", { name: /Kalshi live book/ })).toHaveAttribute("href", "/portfolio?book=kalshi");
    unmount();
    auth.token = "t";
    serve({ "/api/kalshi-demo": { state: "ok", live_pilot: pilot } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const admin = screen.getByRole("region", { name: "Real money" });
    expect(await within(admin).findByText("$9.87")).toBeInTheDocument();
    expect(within(admin).getByText("−$0.13")).toBeInTheDocument();
    expect(within(admin).getByText("9 of 12")).toBeInTheDocument();
    expect(within(admin).getByText("Running")).toBeInTheDocument();
  });

  it("lists every shadow on trial with its progress toward the bar", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    const m = (series: string, n: number, needed: number, net: number) => ({
      version: "oil-trend-agree-v1", label: "Trend-agree v1 (vs raw rule)", series, trades: n, net_cents: net,
      low95: -1.2, paired_low95: null, fill_short: 0, too_few: n < 10,
      progress: { n, needed, legs: { n: false, low95: false, paired: false } },
      account: { start: 20, balance: 20, drawdown: 0, bust: false, curve: [], trades_taken: n } });
    serve({ "/api/oil/fifteen-rule": { ...base, board: { account_start: 20, commodities: [
              { series: "KXWTI15M", commodity: "WTI", models: [m("KXWTI15M", 37, 150, 4)] },
              { series: "KXBRENT15M", commodity: "Brent", models: [m("KXBRENT15M", 20, 150, -2)] }] } },
            "/api/strategies/trials": { trials: [
              { id: "leaps", name: "LEAPS shadow", tests: "Do LEAPS deliver?", n: null, needed: 4, unit: "pairs",
                score: null, score_label: null, status: "no_read", note: null }] } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = await screen.findByRole("list", { name: "Shadows on trial" });
    const trend = (await within(list).findByText(/Trend-agree v1/)).closest("li")!;
    expect(within(trend).getByText(/37 \/ 150 trades/)).toBeInTheDocument();
    expect(within(trend).getByRole("img", { name: "37 of 150 toward the pass bar" })).toBeInTheDocument();
    expect(within(trend).getByText("low95 −1.2¢")).toBeInTheDocument();
    const leaps = (await within(list).findByText("LEAPS shadow")).closest("li")!;
    expect(within(leaps).getByText("recording, no public read yet")).toBeInTheDocument();
  });

  it("keeps retired and paused strategies collapsed", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const retired = screen.getByRole("region", { name: "Retired & paused" });
    expect(retired.querySelector("details")!.open).toBe(false);
    expect(within(retired).getByText("Crypto sniper")).toBeInTheDocument();
    expect(within(retired).getByText("Kalshi gap tracker")).toBeInTheDocument();
  });
  it("keeps a trial recording until the paired leg is met too", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    const m = { version: "v4-late-window-shadow", label: "v4-late-window-shadow", series: "KXWTI15M", trades: 120,
                net_cents: 1.5, low95: 0.3, paired_low95: -0.8, fill_short: 0, too_few: false,
                progress: { n: 120, needed: 100, legs: { n: true, low95: true, paired: false } },
                account: { start: 20, balance: 20, drawdown: 0, bust: false, curve: [], trades_taken: 120 } };
    serve({ "/api/oil/fifteen-rule": { ...base, board: { account_start: 20, commodities: [
      { series: "KXWTI15M", commodity: "WTI", models: [m] }] } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = await screen.findByRole("list", { name: "Shadows on trial" });
    const row = (await within(list).findByText("v4-late-window-shadow")).closest("li")!;
    expect(within(row).getByText("recording")).toBeInTheDocument();
    expect(within(row).queryByText("eligible")).toBeNull();
  });
});
