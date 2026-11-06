import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Strategies from "@/pages/Strategies";

const BODIES: Record<string, unknown> = {
  "/api/portfolio": { state: "live", as_of: "2026-11-05T21:00:00Z", scoreboard: { equity: 97706, return_pct: -2.3, ahead_pts: 1.4 },
                      positions: [], curve: [], composition: [] },
  "/api/ideas": [{ id: 17, live: { state: "live" }, live_books: ["main"] }, { id: 36, live: { state: "live" }, live_books: [] }],
  "/api/oil/fifteen-rule": { rule: "Buy the side the model beats by 10.", prereg_at: "2026-11-06T00:00:00+00:00", ready_trades: 300,
                             replay: { n: 51, net_per_contract: 0.0967 }, forward: { n: 4, net_per_contract: 0.05 }, pending: 0, recent: [] },
  "/api/oil/itm-record": { frozen: 24, settled: 24, hits: 9, hit_rate: 0.375, net_per_contract: 0.0188, backtest: null, recent: [] },
  "/api/gaps/desk": { evidence: { status: "NOT ENOUGH EVIDENCE", days: 1.8, pairs: 1834, min_days: 28, min_pairs: 150 },
                      ledger: { bankroll: 8114.82, return_pct: -18.85, resolved: 18 } },
  "/api/crypto/sniper-verdict": { overall: { count: 18602, hit_rate: 0.548 } },
};

function serve() {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => {
    const key = Object.keys(BODIES).sort((a, b) => b.length - a.length).find((k) => String(url).includes(k));
    return new Response(JSON.stringify(key ? BODIES[key] : {}), { status: key ? 200 : 404 });
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
    expect(await within(list).findByText(/4 of 300 forward trades/)).toBeInTheDocument();
    expect(await within(list).findByText(/9 of 24 hit/)).toBeInTheDocument();
    expect(await within(list).findByText(/−18\.9% on \$10k/)).toBeInTheDocument();
    expect(await within(list).findByText(/18,602 graded/)).toBeInTheDocument();
    for (const stage of ["Live paper account", "Paper record", "Picks only", "Retired"]) {
      expect(within(list).getAllByText(stage).length).toBeGreaterThan(0);
    }
    expect(within(list).getByRole("link", { name: /15-minute oil and gas rule/i })).toHaveAttribute("href", "#fifteen-rule");
  });
});
