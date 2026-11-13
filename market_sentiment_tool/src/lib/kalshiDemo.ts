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

export interface KalshiDemoNotConnected {
  state: "not_connected";
  demo: boolean;
  note: string;
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
  orders: KalshiOrder[];
  note: string;
}

export type KalshiDemoPayload = KalshiDemoNotConnected | KalshiDemoLive;
