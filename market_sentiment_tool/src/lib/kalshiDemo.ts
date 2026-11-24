/** Payload of GET /api/kalshi-demo. The page reads only live_pilot (admin-only); the demo fields ride along unused. */

/** The live micro-pilot's scoreboard (issue #590): the oil & gas raw
 * rule on Kevin's LIVE Kalshi account. Attached to every payload shape
 * by the endpoint; the lane is independent of the demo connection. */
export interface KalshiLivePilot {
  state: "live" | "halted" | "not_enabled" | "unavailable";
  real_money: boolean;
  enabled: boolean;
  halted: boolean;
  halt_reason: string | null;
  balance: number | null;
  balance_at?: string | null;
  pnl_since_start: number | null;
  decisions: number;
  fills: number;
  fill_rate: number | null;
  mean_slippage_cents: number | null;
  settled: number;
  live_net_per_contract: number | null;
  live_low95_cents: number | null;
  paper_net_per_contract: number | null;
  paper_low95_cents: number | null;
  latency_median_s: number | null;
  gates: {
    execution: { state: string; fills: number; bar: number; mean_slippage_cents: number | null };
    edge: { state: string; settled: number; bar: number; low95_cents: number | null; stage3_unlocked: boolean };
  };
  daily_stop_usd: number;
  floor_usd: number;
  orders: Array<{
    id: number | null;
    created_at: string | null;
    series: string;
    ticker: string;
    side: string;
    status: string;
    skip_reason: string | null;
    contracts_requested: number | null;
    contracts_filled: number;
    frozen_quote: number | null;
    live_ask: number | null;
    fill_price: number | null;
    fee_usd: number | null;
    outcome: number | null;
    pnl: number | null;
    paper_pnl: number | null;
    window_close: string | null;
  }>;
}

/** What a public (non-admin) request gets: the live pilot is Kevin-only. */
export interface KalshiLivePilotAdminOnly {
  admin_only: true;
}

export interface KalshiDemoPayload {
  state: string;
  live_pilot?: KalshiLivePilot | KalshiLivePilotAdminOnly | null;
}
