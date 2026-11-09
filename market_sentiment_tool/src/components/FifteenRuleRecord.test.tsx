import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { FifteenRuleRecord } from "@/components/FifteenRuleRecord";

const stats = (n: number, net: number | null, ready = false) =>
  ({ n, net_per_contract: net, total: net == null ? 0 : net * n, win_rate: 0.5, low95: net == null ? null : net - 0.1, ready });

function serve(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })));
}

afterEach(() => vi.unstubAllGlobals());

describe("FifteenRuleRecord", () => {
  it("states the rule, the forward record against the go-live bar, and the replay apart", async () => {
    serve({ rule: "Buy the side the model beats by 10 points.", prereg_at: "2026-11-06T00:00:00+00:00", ready_trades: 300,
            replay: stats(49, 0.097), forward: stats(12, 0.05), by_series: {}, pending: 2,
            recent: [{ series: "WTI", target: "t", frozen_at: "2026-11-06T14:05:00+00:00", side: "yes", cost: 0.48, model: 0.62, outcome: 1, pnl: 0.5 }] });
    render(<FifteenRuleRecord />);
    expect(await screen.findByText("Buy the side the model beats by 10 points.")).toBeInTheDocument();
    expect(screen.getByText(/12 of 300 forward trades/)).toBeInTheDocument();
    expect(screen.getByText(/\+5\.0¢ a contract/)).toBeInTheDocument();
    expect(screen.getByText(/Replay before the rule was fixed: 49 trades, \+9\.7¢/)).toBeInTheDocument();
    expect(screen.getByText("WTI")).toBeInTheDocument();
  });

  it("says so when there are no forward trades yet", async () => {
    serve({ rule: "r", prereg_at: "2026-11-06T00:00:00+00:00", ready_trades: 300, replay: stats(49, 0.097),
            forward: stats(0, null), by_series: {}, pending: 0, recent: [] });
    render(<FifteenRuleRecord />);
    expect(await screen.findByText(/No forward trades yet/)).toBeInTheDocument();
  });
});

describe("FifteenRuleRecord with the fee-netted gate and tracking", () => {
  it("shows the gated record, the skipped windows, and the best entry minute", async () => {
    serve({
      rule: "Buy the side the model beats by 10 points.",
      prereg_at: "2026-11-07T00:00:00+00:00",
      ready_trades: 300,
      replay: stats(49, 0.097),
      forward: stats(30, 0.05),
      by_series: {}, pending: 1, recent: [],
      gate: { rule: "gated", forward: stats(24, 0.111) },
      decisions: { recorded: 141, buy: 31, skip: 110, by_reason: { no_edge: 104, halt: 6 } },
      offsets: { by_offset: [
        { offset_min: 5, windows: 40, priced: 38, mean_edge_net: 0.05, n: 20, net_per_contract: 0.02, win_rate: 0.5, mean_move_to_settle_bps: 10, mean_move_to_60m_bps: 20 },
        { offset_min: 9, windows: 40, priced: 36, mean_edge_net: 0.09, n: 18, net_per_contract: 0.14, win_rate: 0.61, mean_move_to_settle_bps: 12, mean_move_to_60m_bps: 22 },
      ] },
    });
    render(<FifteenRuleRecord />);
    expect(await screen.findByText(/With the fee netted out of the edge test/)).toBeInTheDocument();
    expect(screen.getByText(/24 trades, \+11\.1¢ a contract/)).toBeInTheDocument();
    expect(screen.getByText(/141 windows on record: 31 buys, 110 skipped \(no edge 104, halt 6\)/)).toBeInTheDocument();
    expect(screen.getByText(/Best entry minute so far: minute 9/)).toBeInTheDocument();
  });
});

describe("FifteenRuleRecord with the go-live bar on the gated record", () => {
  it("counts the bar on gated trades and keeps the raw record as the control", async () => {
    serve({
      rule: "Buy the side the model beats by 10 points.",
      prereg_at: "2026-11-07T00:00:00+00:00",
      ready_trades: 300,
      replay: stats(49, 0.097),
      forward: { n: 46, net_per_contract: 0.102, total: 4.71, win_rate: 0.56, low95: -0.018, ready: false, windows: 46 },
      by_series: {}, pending: 3, recent: [],
      gate: { rule: "gated", forward: { n: 37, net_per_contract: 0.162, total: 6.01, win_rate: 0.62, low95: 0.032, ready: false, windows: 37 } },
      bar: { basis: "gated", trades: 37, ready_trades: 300, ready: false, low95: 0.032, windows: 37, pending: 2,
             control: { basis: "raw", trades: 46, ready: false, low95: -0.018 } },
    });
    render(<FifteenRuleRecord />);
    expect(await screen.findByText(/37\/300 gated trades so far/)).toBeInTheDocument();
    expect(screen.getByText(/37 of 300 settled gated trades in 37 separate 15-minute windows/)).toBeInTheDocument();
    expect(screen.getByText(/\+16\.2¢ a contract, win rate 62%/)).toBeInTheDocument();
    expect(screen.getByText(/low end of its 95% range \(now \+3\.2¢\)/)).toBeInTheDocument();
    expect(screen.getByText(/2 waiting to settle/)).toBeInTheDocument();
    expect(screen.getByText(/On the original gross-edge record, kept as a control: 46 trades, \+10\.2¢ a contract, win rate 56%/)).toBeInTheDocument();
  });
});

describe("FifteenRuleRecord split by market, with the entry-timing table", () => {
  it("shows each market's gated and raw forward record side by side, and what each entry minute paid", async () => {
    serve({
      rule: "Buy the side the model beats by 10 points.",
      prereg_at: "2026-11-07T00:00:00+00:00",
      ready_trades: 300,
      replay: stats(49, 0.097),
      forward: stats(30, 0.05),
      by_series: { WTI: stats(3, 0.03), Brent: stats(1, -0.02), "Natural gas": stats(6, 0.19) },
      pending: 1, recent: [],
      gate: { rule: "gated", forward: stats(24, 0.111),
              by_series: { WTI: stats(2, 0.05), Brent: stats(0, null), "Natural gas": stats(5, 0.2) } },
      decisions: { recorded: 141, buy: 31, skip: 110, by_reason: { no_edge: 104, halt: 6 } },
      offsets: { by_offset: [
        { offset_min: 1, windows: 40, priced: 39, mean_edge_net: 0.028, n: 12, net_per_contract: 0.195, win_rate: 0.71, mean_move_to_settle_bps: -2, mean_move_to_60m_bps: -4 },
        { offset_min: 5, windows: 40, priced: 38, mean_edge_net: 0.046, n: 20, net_per_contract: 0.062, win_rate: 0.53, mean_move_to_settle_bps: 1, mean_move_to_60m_bps: -3 },
        { offset_min: 15, windows: 40, priced: 0, mean_edge_net: null, n: 0, net_per_contract: null, win_rate: null, mean_move_to_settle_bps: 0, mean_move_to_60m_bps: -3 },
      ] },
    });
    render(<FifteenRuleRecord />);
    const markets = within(await screen.findByLabelText("Record by market"));
    expect(markets.getByText("Natural gas")).toBeInTheDocument();
    expect(markets.getByText("+20.0¢")).toBeInTheDocument();   // natgas, gated
    expect(markets.getByText("+19.0¢")).toBeInTheDocument();   // natgas, raw
    expect(markets.getByText("−2.0¢")).toBeInTheDocument();    // Brent, raw (its gated record is empty)
    const timing = within(screen.getByLabelText("Entry timing by minute"));
    expect(timing.getByText("+19.5¢")).toBeInTheDocument();    // minute 1 entries
    expect(timing.getByText("+6.2¢")).toBeInTheDocument();     // minute 5 entries (the freeze minute)
    expect(timing.getByText(/best so far/)).toBeInTheDocument();
    expect(timing.queryByText("15")).not.toBeInTheDocument();  // an unpriced minute is not a row
    expect(screen.getByText(/Best entry minute so far: minute 1/)).toBeInTheDocument();
  });
});

describe("FifteenRuleRecord on a malformed reply", () => {
  it("renders nothing rather than crash", async () => {
    serve({ state: "live" });
    const { container } = render(<FifteenRuleRecord />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });
});

describe("FifteenRuleRecord with by_session and windows", () => {
  it("shows windows line and the trading hours vs closed hours table", async () => {
    serve({
      rule: "Buy the side the model beats by 10 points.",
      prereg_at: "2026-11-06T00:00:00+00:00",
      ready_trades: 300,
      replay: { n: 49, net_per_contract: 0.097, total: 4.75, win_rate: 0.5, low95: 0.05, ready: false, windows: 0 },
      forward: { n: 12, net_per_contract: 0.05, total: 0.6, win_rate: 0.55, low95: 0.01, ready: false, windows: 8 },
      by_session: {
        open: { n: 8, net_per_contract: 0.06, total: 0.48, win_rate: 0.625, low95: 0.02, ready: false, windows: 5 },
        closed: { n: 4, net_per_contract: 0.03, total: 0.12, win_rate: 0.4, low95: -0.01, ready: false, windows: 3 }
      },
      pending: 2,
      recent: [{ series: "WTI", target: "t", frozen_at: "2026-11-06T14:05:00+00:00", side: "yes", cost: 0.48, model: 0.62, outcome: 1, pnl: 0.5 }]
    });
    render(<FifteenRuleRecord />);
    // windows line
    expect(await screen.findByText(/12 of 300 forward trades in 8 separate 15-minute windows/)).toBeInTheDocument();
    // table labels
    expect(screen.getByText("Trading hours vs closed hours")).toBeInTheDocument();
    expect(screen.getByText("When futures were trading")).toBeInTheDocument();
    expect(screen.getByText("When futures were closed")).toBeInTheDocument();
    // open row
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText("+6.0¢")).toBeInTheDocument();
    expect(screen.getByText("63%")).toBeInTheDocument();
    // closed row
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("+3.0¢")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
    // explanatory sentence
    expect(screen.getByText(/A real edge should hold while futures trade/)).toBeInTheDocument();
  });
});
