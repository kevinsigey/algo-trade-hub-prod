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

describe("FifteenRuleRecord on a malformed reply", () => {
  it("renders nothing rather than crash", async () => {
    serve({ state: "live" });
    const { container } = render(<FifteenRuleRecord />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });
});
