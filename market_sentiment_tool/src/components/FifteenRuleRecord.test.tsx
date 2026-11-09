import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

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
