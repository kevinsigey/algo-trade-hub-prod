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
  /** Curated sector from the backend map (tradehub/portfolio/sectors.py); absent on old payloads. */
  sector?: string | null;
  qty: number | null;
  side: string | null;
  market_value: number;
  pct_of_book: number | null;
  unrealized_pl: number | null;
  idea: string | null;
  /** Broker-page columns; absent on old payloads and on the stale fallback. */
  last_price?: number | null;
  change_pct?: number | null;
  avg_price?: number | null;
  cost_basis?: number | null;
  day_pl?: number | null;
}

/** The account rail's balances, as the broker reports them. */
export interface AccountView {
  last_equity: number | null;
  day_pl: number | null;
  day_pl_pct: number | null;
  cash: number | null;
  buying_power: number | null;
  long_value: number | null;
  short_value: number | null;
  initial_margin: number | null;
  maintenance_margin: number | null;
  realized_pl: number | null;
}

export interface BreakerState {
  enabled: boolean;
  tripped: boolean;
  reasons: string[];
  daily_limit_pct: number | null;
  drawdown_limit_pct: number | null;
  daily_loss_pct: number | null;
  drawdown_pct: number | null;
}

/** The rail's line for a book's circuit breaker. */
export function breakerLabel(b: BreakerState): string {
  if (b.tripped) return "Tripped";
  if (!b.enabled) return "Off";
  const parts = [
    b.daily_limit_pct != null ? `${(b.daily_loss_pct ?? 0).toFixed(1)}% of ${b.daily_limit_pct}% daily` : null,
    b.drawdown_limit_pct != null ? `${(b.drawdown_pct ?? 0).toFixed(1)}% of ${b.drawdown_limit_pct}% drawdown` : null,
  ].filter(Boolean);
  return `On, ${parts.join(", ")}`;
}

export interface PortfolioPayload {
  state: PortfolioState;
  as_of: string | null;
  /** Which paper book this payload reads ("main" | "big"); absent on old payloads. */
  book?: string;
  scoreboard: Scoreboard;
  account?: AccountView;
  breaker?: BreakerState;
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

export interface ActivityOrder {
  symbol: string;
  side: string;
  qty: number | null;
  filled_qty: number | null;
  type: string | null;
  time_in_force: string | null;
  status: string;
  limit_price: number | null;
  stop_price: number | null;
  filled_avg_price: number | null;
  submitted_at: string | null;
  filled_at: string | null;
  asset: "stock" | "option";
  source: string;
}

export interface ActivityPayload {
  state: PortfolioState;
  as_of: string | null;
  /** Which paper book this payload reads ("main" | "big"); absent on old payloads. */
  book?: string;
  open: ActivityOrder[];
  recent: ActivityOrder[];
  trades: ClosedTrade[];
}

export interface ClosedPayload {
  state: PortfolioState;
  as_of: string | null;
  /** Which paper book this payload reads ("main" | "big"); absent on old payloads. */
  book?: string;
  trades: ClosedTrade[];
}

/** One book's headline for the Portfolio master view (GET /api/portfolio/books):
 * the two paper accounts side by side, each opening into its own book page. */
export interface BookHeadline {
  book: string;
  label: string;
  detail: string;
  state: PortfolioState;
  as_of: string | null;
  equity: number | null;
  return_pct: number | null;
  positions: number;
  live_ideas: number;
}

export interface BooksPayload {
  books: BookHeadline[];
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

export function ct(iso: string): string {
  const parts = Object.fromEntries(ctTime.formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
  return `${parts.hour}:${parts.minute} ${parts.dayPeriod} CT, ${parts.weekday} ${parts.month} ${parts.day}`;
}

/** The line under the big numbers: every number on the page carries its as-of time and state. */
export function stateLabel(state: PortfolioState, asOf: string | null): string {
  if (state === "not_connected") return "Paper account not connected";
  if (state === "stale") return `Paper account · stale, last read ${asOf ? ct(asOf) : "—"}`;
  if (state === "pre_start") return `Paper account · not the account on record · as of ${asOf ? ct(asOf) : "—"}`;
  return `Paper account · live · as of ${asOf ? ct(asOf) : "—"}`;
}

export function tone(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || v === 0) return "text-white";
  return v > 0 ? "text-emerald-400" : "text-rose-400";
}

export const CURVE_RANGES = ["1W", "1M", "YTD", "All"] as const;
export type CurveRange = (typeof CURVE_RANGES)[number];
type CurvePoint = PortfolioPayload["curve"][number];

/** The curve from the range's start, rebased so both lines read from 0% there. */
export function curveRange(curve: CurvePoint[], range: CurveRange, now: Date = new Date()): CurvePoint[] {
  if (range === "All" || curve.length === 0) return curve;
  const since = new Date(now);
  if (range === "1W") since.setDate(since.getDate() - 7);
  else if (range === "1M") since.setMonth(since.getMonth() - 1);
  else since.setMonth(0, 1);
  const kept = curve.filter((p) => new Date(p.t) >= since);
  if (kept.length === 0) return [];
  const rebase = (v: number, base: number) => ((1 + v / 100) / (1 + base / 100) - 1) * 100;
  return kept.map((p) => ({
    t: p.t, portfolio_pct: rebase(p.portfolio_pct, kept[0].portfolio_pct), spy_pct: rebase(p.spy_pct, kept[0].spy_pct),
  }));
}

const OCC = /^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "NVDA Dec 4 2026 $200 call" for an option symbol; null for anything else. */
export function contractLabel(symbol: string): string | null {
  const m = OCC.exec(symbol);
  if (!m) return null;
  const [, root, yy, mm, dd, kind, strike] = m;
  return `${root} ${MONTHS[Number(mm) - 1]} ${Number(dd)} 20${yy} $${Number(strike) / 1000} ${kind === "C" ? "call" : "put"}`;
}

/** Keeps the given order, but moves each option leg directly under its underlying's row. */
export function withOptionsUnderStock(rows: PositionRow[]): PositionRow[] {
  const legs = rows.filter((r) => OCC.test(r.symbol));
  const out: PositionRow[] = [];
  const placed = new Set<PositionRow>();
  for (const r of rows) {
    if (OCC.test(r.symbol)) continue;
    out.push(r);
    if (out.filter((x) => x.symbol === r.symbol).length > 1) continue; // same stock under a second idea
    for (const leg of legs) {
      if (OCC.exec(leg.symbol)![1] === r.symbol) { out.push(leg); placed.add(leg); }
    }
  }
  return [...out, ...legs.filter((l) => !placed.has(l))];
}

const HEAVY_SECTOR_PCT = 40;
const NOT_A_SECTOR_BET = new Set(["Broad Market", "Bonds", "Cash"]);

/** Sectors over 40% of what's invested. The per-symbol cap can't see five chip ideas holding different chips. */
export function concentration(rows: PositionRow[]): { sector: string; pct: number }[] {
  const invested = rows.reduce((sum, r) => sum + Math.abs(r.market_value), 0);
  if (invested <= 0) return [];
  const sectors = new Map<string, number>();
  for (const r of rows) {
    const sector = r.sector ?? "Other";
    if (NOT_A_SECTOR_BET.has(sector) || sector === "Other") continue;
    sectors.set(sector, (sectors.get(sector) ?? 0) + Math.abs(r.market_value));
  }
  return [...sectors].filter(([, v]) => v / invested * 100 > HEAVY_SECTOR_PCT)
    .map(([sector, v]) => ({ sector, pct: v / invested * 100 }));
}

export interface ManualAction {
  id: number;
  book?: string;
  idea_id: number | null;
  idea_title?: string | null;
  kind: string;
  symbol: string | null;
  detail: string;
  state: string;
  created_at: string;
}

export interface ManualActionsPayload {
  book: string;
  actions: ManualAction[];
}
