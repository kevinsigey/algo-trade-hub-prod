import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import OnChainPulse from "@/components/OnChainPulse";

const BODY = { chains: [
  { chain: "btc", status: "ok", fee_fastest: 4, fee_hour: 1, mempool_txs: 55249, mempool_mb: 22.3, retarget_pct: 5.83, blocks_to_retarget: 113, hashrate_eh: 1076, height: 973615 },
  { chain: "eth", status: "unavailable" },
] };
afterEach(() => vi.unstubAllGlobals());

describe("OnChainPulse", () => {
  it("shows live BTC numbers and says so when ETH is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(BODY) })));
    render(<OnChainPulse />);
    expect(await screen.findByText("4 sat/vB")).toBeInTheDocument();
    expect(screen.getByText("+5.83%")).toBeInTheDocument();
    expect(screen.getByText("55,249")).toBeInTheDocument();
    expect(screen.getByText("Ethereum chain data could not be reached just now.")).toBeInTheDocument();
  });

  it("says unavailable instead of rendering zeros when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("down"))));
    render(<OnChainPulse />);
    expect(await screen.findByText("Live chain data could not be reached just now.")).toBeInTheDocument();
  });
});
