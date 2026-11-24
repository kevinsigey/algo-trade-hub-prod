/** Payload of GET /api/kalshi-demo: the Kalshi DEMO book (Portfolio tab). */

export interface KalshiPosition {
  ticker: string;
  series: string;
  strike: number | null;
  side: string;
  contracts: number;
  avg_price: number | null;
  yes_bid: number | null;
  yes_ask: number | null;
  open_pnl: number | null;
  close_time: string | null;
}

export interface KalshiCurvePoint {
  at: string;
  pnl: number;
}

export interface KalshiPerformance {
  demo_curve: KalshiCurvePoint[];
  shadow_curve: KalshiCurvePoint[];
  shadow_curve_per_contract: KalshiCurvePoint[];
  fill_rate: number | null;
  avg_slippage_cents: number | null;
  win_rate: number | null;
  pnl_per_contract: number | null;
  decisions_not_traded: { caps: number; no_depth: number; missed: number };
}

export interface KalshiOrder {
  id: number;
  created_at: string;
  target: string;
  ticker: string;
  side: string;
  gate_version: string | null;
  contracts: number;
  contracts_filled: number;
  limit_price: number;
  frozen_quote: number;
  ask_size: number | null;
  status: string;
  skip_reason: string | null;
  fill_price: number | null;
  filled_at: string | null;
  window_close: string;
  outcome: number | null;
  settlement_pnl: number | null;
}

/** One demo lane's own record: the live gate's lane and the candidate
 * lane (v4-edge20-shadow) are never pooled. */
export interface KalshiLane {
  gate_version: string;
  orders: number;
  settled: number;
  win_rate: number | null;
  pnl: number;
  pnl_per_contract: number | null;
}

export interface KalshiProdLane {
  gate_version: string;
  recorded: number;
  would_fill: number;
  fill_rate: number | null;
  settled: number;
  pnl_per_contract: number | null;
  low95_cents: number | null;
}

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

export interface KalshiDemoNotConnected {
  state: "not_connected";
  demo: boolean;
  note: string;
  live_pilot?: KalshiLivePilot | KalshiLivePilotAdminOnly | null;
}

export interface KalshiDemoLive {
  state: "live";
  demo: boolean;
  as_of: string;
  balance: number | null;
  starting_balance: number;
  pnl_since_start: number | null;
  pnl_today: number | null;
  positions: KalshiPosition[];
  /** True when the positions read failed: positions is [] but the book
   * is NOT known to be flat. */
  positions_unavailable: boolean;
  performance: KalshiPerformance;
  lanes: KalshiLane[];
  /** Health lines for the tab (e.g. "demo book empty: KXNATGAS15M"). */
  health: string[];
  /** Would-have-filled record against the production book, per lane. */
  prod_book: KalshiProdLane[];
  orders: KalshiOrder[];
  note: string;
  /** The live micro-pilot's scoreboard (real money, issue #590). */
  live_pilot?: KalshiLivePilot | KalshiLivePilotAdminOnly | null;
}

export type KalshiDemoPayload = KalshiDemoNotConnected | KalshiDemoLive;
