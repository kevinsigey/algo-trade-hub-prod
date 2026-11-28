import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
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

/** Click a dashboard card (or any "Open X" control) and return the full view it opens. */
async function open(name: string) {
  fireEvent.click(await screen.findByRole("button", { name: `Open ${name}` }));
  return screen.getByRole("dialog", { name: new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i") });
}
const OIL = "15-min oil & gas";
const boardModel = (version: string, label: string, series: string, n: number, needed: number, net: number,
                    extra: Record<string, unknown> = {}) => ({
  version, label, series, trades: n, net_cents: net, low95: -1.2, paired_low95: null, fill_short: 0, too_few: n < 10,
  progress: { n, needed, legs: { n: false, low95: false, paired: false } },
  account: { start: 20, balance: 21, drawdown: 0.4, bust: false, curve: [20, 20.5, 21], trades_taken: n }, ...extra });

describe("Strategies", () => {
  it("renders the sections in dashboard order: live models, on trial, by commodity, learned, retired", async () => {
    serve({ "/api/oil/fifteen-rule": { ...(BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>),
      board: { account_start: 20, commodities: [{ series: "KXWTI15M", commodity: "WTI",
        models: [boardModel("v4-edge20-shadow", "v4-edge20-shadow", "KXWTI15M", 8, 100, 4.2)] }] } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Strategies", level: 1 })).toBeInTheDocument();
    const live = screen.getByRole("region", { name: "Live models" });
    for (const name of ["Kalshi live", "Stock ideas", OIL, "WTI hourly strike"]) {
      expect(await within(live).findByRole("region", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("region", { name: "On trial" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "By commodity" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "What we learned" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Retired & paused" })).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    const at = ["Live models", "On trial (shadows)", "By commodity", "What we learned", "Retired & paused"].map((h) => text.indexOf(h));
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    // Nothing long stays on the page: the board, the findings and the retired books sit behind their cards.
    expect(screen.queryByRole("region", { name: "15-minute models by commodity" })).toBeNull();
    expect(screen.queryByText(/oil-trend-agree-v1\./)).toBeNull();
    expect(screen.queryByRole("list", { name: "Retired strategies" })).toBeNull();
  });

  it("shows each live card's headline and quick stats at rest", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const stock = await screen.findByRole("region", { name: "Stock ideas" });
    expect(await within(stock).findByText("+1.4 pts")).toBeInTheDocument();
    expect(within(stock).getByText(/vs SPY since start · 1 idea trading/)).toBeInTheDocument();
    expect(within(stock).getByRole("link", { name: /Portfolio/ })).toHaveAttribute("href", "/portfolio");
    const oil = screen.getByRole("region", { name: OIL });
    expect(await within(oil).findByText("+14.0¢")).toBeInTheDocument();
    expect(within(oil).getByText(/7 of 300 gated · 57% win · raw \+5\.0¢/)).toBeInTheDocument();
    const hourly = screen.getByRole("region", { name: "WTI hourly strike" });
    expect(await within(hourly).findByText("38%")).toBeInTheDocument();
    expect(within(hourly).getByText(/9 of 24 hit · \+1\.9¢ a contract/)).toBeInTheDocument();
  });

  it("opens the oil & gas card into the per-series gated/raw breakdown and every block of the old tile", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    await within(screen.getByRole("region", { name: OIL })).findByText("+14.0¢");
    const view = await open(OIL);
    for (const label of ["WTI", "Brent", "Natural gas"]) expect(within(view).getAllByText(label).length).toBeGreaterThan(0);
    expect(within(view).getByText(/2 gated trades · \+5\.0¢ a contract · 50% win/)).toBeInTheDocument();
    expect(within(view).getByText(/5 gated trades · \+20\.0¢ a contract · 60% win/)).toBeInTheDocument();
    expect(within(view).getByText(/0 gated trades · raw 1 trade · −2\.0¢ a contract/)).toBeInTheDocument();
    expect(within(view).getByText(/7 gated trades · \+14\.0¢ a contract · 57% win · raw control 10 · \+5\.0¢ a contract/)).toBeInTheDocument();
    for (const title of ["The rule", "Settlements scoring — the forecasts vs Kalshi's price", "The trade record",
                         "Decisions — every window gets one", "Entry timing — what entering at each minute has paid",
                         "Trading hours vs closed hours"]) {
      expect(within(view).getByText(title, { selector: "summary" })).toBeInTheDocument();
    }
    expect(within(view).getAllByText(/Five minutes into each 15-minute window, buy the side/)).toHaveLength(1);
    expect(within(view).getByText(/7 of 300 settled gated trades in 7 separate 15-minute windows/)).toBeInTheDocument();
    expect(within(view).getByText(/still ahead at the low end of its 95% range \(now \+2\.1¢\)/)).toBeInTheDocument();
    expect(within(view).getByText(/2 waiting to settle/)).toBeInTheDocument();
    expect(within(view).getByText(/On the original gross-edge record, kept as a control: 10 trades, \+5\.0¢ a contract, win rate 50%/)).toBeInTheDocument();
    expect(within(view).getByText(/Replay before the rule was fixed: 51 trades, \+9\.7¢ a contract/)).toBeInTheDocument();
    expect(within(view).getByText(/489 windows on record: 56 buys, 433 skipped \(no edge 403, no quote 3, halt 27\)/)).toBeInTheDocument();
    expect(within(view).getByLabelText("Entry timing by minute")).toBeInTheDocument();
    expect(within(view).getByText(/Best entry minute so far: minute 1 of the window \(17 priced entries, \+19\.5¢ a contract after fees\)/)).toBeInTheDocument();
    expect(within(view).getByText(/A real edge should hold while futures trade/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: OIL })).getByText("Not proven yet")).toBeInTheDocument();
    // The settlements chart rides in the same view.
    const chart = within(await within(view).findByLabelText("15-minute settlements scoring"));
    expect(chart.getByText(/969 settled/)).toBeInTheDocument();
  });

  it("no longer shows the killed oil shadow, even if a stale payload carries its block", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    serve({ "/api/oil/fifteen-rule": { ...base,
      shadow: { gate_version: "v2-oil-shadow", prereg_at: "2026-11-09T19:00:00+00:00",
                fresh: { windows: 273, trades: 246, net_per_contract: -0.048, low95: -0.108, win_rate: 0.4 } } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    await within(screen.getByRole("region", { name: OIL })).findByText("+14.0¢");
    const view = await open(OIL);
    expect(within(view).queryByText("Oil shadow — the minute-1 variant")).not.toBeInTheDocument();
  });

  it("puts the decline monitor in the oil & gas view", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    const cell = (trades: number, pnl: number | null) => ({ trades, pnl_per_trade: pnl });
    serve({ "/api/oil/fifteen-rule": { ...base,
      decline: [{ day: "2026-11-12", series: "Natural gas", live: cell(12, 0.025), blend: cell(4, 0.08), volregime: cell(0, null) }] } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    await within(screen.getByRole("region", { name: OIL })).findByText("+14.0¢");
    const view = await open(OIL);
    const table = within(view).getByRole("table", { name: "15-minute decline monitor" });
    expect(within(table).getByText("+2.5¢")).toBeInTheDocument();
    expect(within(table).getByText("+8.0¢")).toBeInTheDocument();
  });

  it("adds a metals card whose view holds the per-series breakdown", async () => {
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
    const card = await screen.findByRole("region", { name: "15-min metals" });
    expect(within(card).getByText("+10.3¢")).toBeInTheDocument();
    const view = await open("15-min metals");
    for (const label of ["Gold", "Silver", "Copper"]) expect(within(view).getAllByText(label).length).toBeGreaterThan(0);
    expect(within(view).getByText(/3 gated trades · \+13\.0¢ a contract · 67% win/)).toBeInTheDocument();
    expect(within(view).getByText(/0 gated trades · raw 2 trades · −5\.0¢ a contract/)).toBeInTheDocument();
    expect(within(view).getByText(/4 gated trades · \+10\.3¢ a contract · 75% win/)).toBeInTheDocument();
  });

  it("shows the metals card accruing, with no borrowed numbers, before its first settled trades", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    const zero = { n: 0, net_per_contract: null, win_rate: null };
    serve({ "/api/oil/fifteen-rule": { ...base,
      metals: { prereg_at: "2026-11-09T19:55:00+00:00", ready_trades: 300,
                by_series: { Gold: zero, Silver: zero, Copper: zero },
                gate: { forward: zero, by_series: { Gold: zero, Silver: zero, Copper: zero } } } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const card = await screen.findByRole("region", { name: "15-min metals" });
    expect(within(card).getByText("Accruing")).toBeInTheDocument();
    const view = await open("15-min metals");
    expect(within(view).getAllByText(/Accruing — no settled gated trades yet/)).toHaveLength(4);
  });

  it("draws the stock ideas curve on its card", async () => {
    serve({ "/api/portfolio": { ...(BODIES["/api/portfolio"] as Record<string, unknown>),
      curve: [{ t: "2026-09-01", portfolio_pct: 0, spy_pct: 0 },
              { t: "2026-10-01", portfolio_pct: 2.1, spy_pct: 1.2 },
              { t: "2026-11-01", portfolio_pct: 1.4, spy_pct: 0 }] } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const card = screen.getByRole("region", { name: "Stock ideas" });
    expect(await within(card).findByRole("img", { name: "Portfolio curve against SPY" })).toBeInTheDocument();
  });

  it("opens the by-commodity board from its card: ranked models and simulated accounts", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    serve({ "/api/oil/fifteen-rule": { ...base, board: { account_start: 20, commodities: [
      { series: "KXNATGAS15M", commodity: "Natural gas", models: [
        boardModel("live", "Live rule", "KXNATGAS15M", 97, 300, 7.8, { fill_short: 1, low95: 1.5, paired_low95: -2,
          progress: { n: 97, needed: 300, legs: { n: false, low95: true, paired: true } },
          account: { start: 20, balance: 26.31, drawdown: 2.25, bust: false, curve: [20, 22.5, 26.31], trades_taken: 97 } }),
        boardModel("v4-edge20-shadow", "v4-edge20-shadow", "KXNATGAS15M", 8, 100, 4.21),
      ] } ] } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const card = await screen.findByRole("region", { name: "By commodity" });
    expect(within(card).getByText("Natural gas")).toBeInTheDocument();
    const view = await open("By commodity");
    const nat = within(view).getByRole("region", { name: "Natural gas models" });
    expect(within(nat).getByText("Live rule")).toBeInTheDocument();
    expect(within(nat).getByText(/97\/300/)).toBeInTheDocument();
    expect(within(nat).getByText(/\$26\.31/)).toBeInTheDocument();
    expect(within(nat).getByText("too few trades")).toBeInTheDocument();
    expect(within(nat).getByText(/fill-short 1/)).toBeInTheDocument();
  });

  it("opens the retired & paused books: the gap tracker post-mortem and the sniper", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const card = screen.getByRole("region", { name: "Retired & paused" });
    expect(within(card).getByText(/Crypto sniper · Kalshi gap tracker/)).toBeInTheDocument();
    const view = await open("Retired & paused");
    expect(within(view).getByRole("list", { name: "Retired strategies" }).lastElementChild?.id).toBe("gap-tracker");
    expect(await within(view).findByText(/2 closed · \+\$80\.50 realized · 50% won/)).toBeInTheDocument();
    expect(within(view).getByText(/1 closed · −\$260\.00 realized · 0% won/)).toBeInTheDocument();
    expect(within(view).getByText(/3 closed · pot \$8,114\.82 of \$10,000/)).toBeInTheDocument();
    expect(within(view).getByText(/Paused · Nov 9, 2026/)).toBeInTheDocument();
    expect(await within(view).findByText(/each desk's fair values graded worse than Kalshi's/)).toBeInTheDocument();
    expect(within(view).getByText(/Brier worse by \+0\.023 on oil and \+0\.002 on crypto/)).toBeInTheDocument();
    expect(within(view).getByText(/Crypto's exits churned: 1 of its 1 trade ended because the model/)).toBeInTheDocument();
    expect(within(view).getAllByText(/fees came out of the trade's P&L, not the test/)).toHaveLength(1);
    expect(within(view).getByText("KXBR-A")).toBeInTheDocument();
    expect(await within(view).findByText(/18,602 graded/)).toBeInTheDocument();
  });

  it("reads each gap desk's record from the server ledger when the payload carries one", async () => {
    serve({ "/api/gaps/desk": { ...(BODIES["/api/gaps/desk"] as Record<string, unknown>),
      ledger_by_category: { oil: { closed: 21, realized: -667.95, win_rate: 0.5238, median_pnl: -12.5 },
                            crypto: { closed: 20, realized: -2509.22, win_rate: 0.2, median_pnl: -95 } } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const view = await open("Retired & paused");
    expect(await within(view).findByText(/21 closed · −\$667\.95 realized · 52% won · typical trade −\$12\.50/)).toBeInTheDocument();
    expect(within(view).getByText(/20 closed · −\$2509\.22 realized · 20% won · typical trade −\$95\.00/)).toBeInTheDocument();
  });

  it("opens what we learned from its one line", async () => {
    serve();
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const view = await open("What we learned");
    expect(within(view).getByText(/oil-trend-agree-v1\./)).toBeInTheDocument();
  });

  it("hides the live pilot's dollars from the public and shows them to admin", async () => {
    const pilot = { state: "live", halted: false, halt_reason: null, balance: 9.87, pnl_since_start: -0.13,
                    decisions: 12, fills: 9, live_net_per_contract: 0.02, paper_net_per_contract: 0.05, orders: [] };
    const NAME = "Kalshi live";
    serve({ "/api/kalshi-demo": { state: "ok", live_pilot: { admin_only: true } } });
    const { unmount } = render(<MemoryRouter><Strategies /></MemoryRouter>);
    const pub = screen.getByRole("region", { name: NAME });
    expect(within(pub).getByText("REAL MONEY")).toBeInTheDocument();
    expect(within(pub).getByText("Admin only")).toBeInTheDocument();
    expect(within(pub).getByText(/A \$10 live pilot runs .* WTI & Brent/)).toBeInTheDocument();
    expect(within(pub).queryByText("$9.87")).toBeNull();
    expect(within(pub).getByRole("link", { name: /Kalshi live book/ })).toHaveAttribute("href", "/portfolio?book=kalshi");
    const pubView = await open(NAME);
    expect(within(pubView).queryByText("$9.87")).toBeNull();
    unmount();
    auth.token = "t";
    serve({ "/api/kalshi-demo": { state: "ok", live_pilot: pilot } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const admin = screen.getByRole("region", { name: NAME });
    expect(await within(admin).findByText("$9.87")).toBeInTheDocument();
    expect(within(admin).getByText("−$0.13")).toBeInTheDocument();
    const view = await open(NAME);
    expect(within(view).getByText("9 of 12")).toBeInTheDocument();
    expect(within(view).getByText("Running")).toBeInTheDocument();
  });

  it("lists shadows on trial with progress, capped at five with Show all, each row opening its record", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    const versions = ["v2-blend-shadow", "v3-volregime-shadow", "v4-edge20-shadow", "v4-no-gold-shadow", "v4-side50-shadow"];
    serve({ "/api/oil/fifteen-rule": { ...base, board: { account_start: 20, commodities: [
              { series: "KXWTI15M", commodity: "WTI", models: [
                boardModel("oil-trend-agree-v1", "Trend-agree v1 (vs raw rule)", "KXWTI15M", 37, 150, 4),
                ...versions.map((v, i) => boardModel(v, v, "KXWTI15M", i + 1, 100, 1)) ] },
              { series: "KXBRENT15M", commodity: "Brent", models: [
                boardModel("oil-trend-agree-v1", "Trend-agree v1 (vs raw rule)", "KXBRENT15M", 20, 150, -2)] }] } },
            "/api/strategies/trials": { trials: [
              { id: "leaps", name: "LEAPS shadow", tests: "Do LEAPS deliver?", n: null, needed: 4, unit: "pairs",
                score: null, score_label: null, status: "no_read", note: null }] } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = await screen.findByRole("list", { name: "Shadows on trial" });
    await within(list).findByText(/Trend-agree v1/);
    // Seven shadows; the page shows the five closest to their bar, the rest behind Show all.
    expect(within(list).getAllByRole("listitem")).toHaveLength(5);
    expect(within(list).queryByText("LEAPS shadow")).toBeNull();
    const trend = within(list).getByText(/Trend-agree v1/).closest("li")!;
    expect(list.firstElementChild).toBe(trend);
    expect(within(trend).getByText((_, el) => el?.tagName === "SPAN" && /^37 \/ 150 trades/.test(el.textContent ?? ""))).toBeInTheDocument();
    expect(within(trend).getByRole("img", { name: "37 of 150 toward the pass bar" })).toBeInTheDocument();
    expect(within(trend).getByText("low95 −1.2¢")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all 7" }));
    const all = screen.getByRole("dialog", { name: "On trial — every shadow" });
    const full = within(all).getByRole("list", { name: "All shadows on trial" });
    expect(within(full).getAllByRole("listitem")).toHaveLength(7);
    expect(within(within(full).getByText("LEAPS shadow").closest("li")!).getByText("recording, no public read yet")).toBeInTheDocument();
    fireEvent.click(within(all).getByRole("button", { name: "Close" }));
    // A row opens its per-commodity records with the simulated account.
    fireEvent.click(within(trend).getByRole("button"));
    const view = screen.getByRole("dialog", { name: /Trend-agree v1/ });
    expect(within(view).getByRole("region", { name: "WTI record" })).toBeInTheDocument();
    expect(within(view).getByRole("region", { name: "Brent record" })).toBeInTheDocument();
    expect(within(view).getAllByText(/Simulated account/)).toHaveLength(2);
  });

  it("shows three trial rows on a phone, still with Show all", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("max-width"), addEventListener: () => {}, removeEventListener: () => {} }));
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    serve({ "/api/oil/fifteen-rule": { ...base, board: { account_start: 20, commodities: [
      { series: "KXWTI15M", commodity: "WTI", models: ["a", "b", "c", "d"].map((v, i) => boardModel(v, v, "KXWTI15M", i + 1, 100, 1)) }] } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = await screen.findByRole("list", { name: "Shadows on trial" });
    await within(list).findByText("d");
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Show all 4" })).toBeInTheDocument();
  });

  it("keeps a trial recording until the paired leg is met too", async () => {
    const base = BODIES["/api/oil/fifteen-rule"] as Record<string, unknown>;
    const m = boardModel("v4-late-window-shadow", "v4-late-window-shadow", "KXWTI15M", 120, 100, 1.5,
                         { low95: 0.3, paired_low95: -0.8, progress: { n: 120, needed: 100, legs: { n: true, low95: true, paired: false } } });
    serve({ "/api/oil/fifteen-rule": { ...base, board: { account_start: 20, commodities: [
      { series: "KXWTI15M", commodity: "WTI", models: [m] }] } } });
    render(<MemoryRouter><Strategies /></MemoryRouter>);
    const list = await screen.findByRole("list", { name: "Shadows on trial" });
    const row = (await within(list).findByText("v4-late-window-shadow")).closest("li")!;
    expect(within(row).getByText("recording")).toBeInTheDocument();
    expect(within(row).queryByText("eligible")).toBeNull();
  });
});
