/** The public paper portfolio: payload types (tradehub/portfolio/service.py) and how its numbers read. */

export type PortfolioState = "not_connected" | "stale" | "pre_start" | "live";

export interface Scoreboard {
  start_at: string | null;
  equity: number | null;
  return_pct: number | null;
  spy_return_pct: number | null;
  ahead_pts: number | null;
  max_drawdown_pct: number | null;
  sharpe: number | null;
  win_rate: number | null;
}

export interface PositionRow {
  symbol: string;
  qty: number | null;
  side: string | null;
  market_value: number;
  pct_of_book: number | null;
  unrealized_pl: number | null;
  idea: string | null;
}

export interface PortfolioPayload {
  state: PortfolioState;
  as_of: string | null;
  account_number: string | null;
  scoreboard: Scoreboard;
  curve: { t: string; portfolio_pct: number; spy_pct: number }[];
  composition: { idea: string; pct_of_book: number; unrealized_pl: number }[];
  positions: PositionRow[];
}

export interface ClosedTrade {
  symbol: string;
  qty: number;
  entry_price: number;
  exit_price: number;
  entered_at: string;
  exited_at: string;
  pnl: number;
  return_pct: number;
  held_days: number;
  idea: string;
}

export interface ClosedPayload {
  state: PortfolioState;
  as_of: string | null;
  trades: ClosedTrade[];
}

const DASH = "—";

/** Unknown is a dash, never 0.0%. The sign is always shown, so a gain never reads as a level. */
export function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;
}

export function fmtPts(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)} pts`;
}

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function fmtUsd(v: number | null | undefined, { signed = false, whole = false } = {}): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  const text = (whole ? usd0 : usd).format(Math.abs(v));
  if (signed) return `${v >= 0 ? "+" : "−"}${text}`;
  return v < 0 ? `−${text}` : text;
}

const ctTime = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago",
  hour: "numeric",
  minute: "2-digit",
  weekday: "short",
  month: "short",
  day: "numeric",
});

function ct(iso: string): string {
  const parts = Object.fromEntries(ctTime.formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
  return `${parts.hour}:${parts.minute} ${parts.dayPeriod} CT, ${parts.weekday} ${parts.month} ${parts.day}`;
}

/** The line under the big numbers: every number on the page carries its as-of time and state. */
export function stateLabel(state: PortfolioState, asOf: string | null): string {
  if (state === "not_connected") return "Paper account not connected";
  if (state === "stale") return `Paper account · stale, last read ${asOf ? ct(asOf) : "—"}`;
  if (state === "pre_start") return `Paper account · not traded yet · as of ${asOf ? ct(asOf) : "—"}`;
  return `Paper account · live · as of ${asOf ? ct(asOf) : "—"}`;
}

export function tone(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || v === 0) return "text-white";
  return v > 0 ? "text-emerald-400" : "text-rose-400";
}
