/** The public paper portfolio: payload types (tradehub/portfolio/service.py) and how its numbers read. */

export type PortfolioState = "not_connected" | "stale" | "pre_start" | "live";

export interface Scoreboard {
  start_at: string | null;
  equity: number | null;
  return_pct: number | null;
  spy_return_pct: number | null;
  ahead_pts: number | null;
  /** QQQ since the first snapshot; null on payloads from before the
   * qqq_price snapshot column (or where its backfill has a gap). */
  qqq_return_pct?: number | null;
  ahead_qqq_pts?: number | null;
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
  /** After-hours move vs today's regular close (aggregate rows only, after 4 PM ET). */
  ah_change_pct?: number | null;
}

/** Today split at the 4:00 PM ET close (tradehub.portfolio.book.today_split).
 * regular_* is the regular session against the prior close; after_hours_* is
 * the move since the close snapshot. state is "regular" until a post-close
 * snapshot exists, then "after_hours"; "no_prior" on the book's first day. */
export interface TodaySplit {
  state: "regular" | "after_hours" | "no_prior" | "closed_day";
  prior_close_at: string | null;
  close_at: string | null;
  regular_pl: number | null;
  regular_pct: number | null;
  after_hours_pl: number | null;
  after_hours_pct: number | null;
  spy_regular_pct: number | null;
  spy_after_hours_pct: number | null;
  /** QQQ beside SPY; absent on old payloads, null where no QQQ price exists. */
  qqq_regular_pct?: number | null;
  qqq_after_hours_pct?: number | null;
  /** The ET date the figures describe; on a weekend/holiday it is the last
   * trading day, `is_today` is false, and `day_label` names it ("Fri"). */
  for_date?: string | null;
  day_label?: string | null;
  is_today?: boolean;
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

/** One line per symbol: the per-idea lots folded back into the position the
 * broker actually holds (tradehub/portfolio/book.py positions_aggregate). */
export interface AggregatePositionRow {
  symbol: string;
  asset: "stock" | "option";
  qty: number;
  market_value: number;
  pct_of_equity: number | null;
  pct_of_book: number | null;
  avg_entry: number | null;
  tags: string[];
  sector?: string | null;
  side?: string | null;
  last_price?: number | null;
  change_pct?: number | null;
  day_pl?: number | null;
  cost_basis?: number | null;
  unrealized_pl: number | null;
  /** After-hours move vs today's regular close; null before the close or when unknown. */
  ah_change_pct?: number | null;
}

/** The aggregate line in the PositionRow shape the page's tables read.
 * Ideas live in the per-idea slices only, so `idea` is always null here. */
export function aggregateToRow(a: AggregatePositionRow): PositionRow {
  return {
    symbol: a.symbol,
    sector: a.sector ?? null,
    qty: a.qty,
    side: a.side ?? null,
    market_value: a.market_value,
    pct_of_book: a.pct_of_book,
    unrealized_pl: a.unrealized_pl,
    idea: null,
    last_price: a.last_price ?? null,
    change_pct: a.change_pct ?? null,
    avg_price: a.avg_entry,
    cost_basis: a.cost_basis ?? null,
    day_pl: a.day_pl ?? null,
    ah_change_pct: a.ah_change_pct ?? null,
  };
}

/** Distinct weekdays in the equity curve. The Sharpe guard counts
 * these, not snapshots: intraday snapshots made 65 points out of 8 trading
 * days and let a meaningless Sharpe print (2026-11-12 review). Weekends
 * don't count either — a live point stamped on a Saturday or Sunday is
 * not a trading day and must not advance the guard. (No holiday
 * handling: a holiday weekday still counts, as before.) */
export function curveTradingDays(curve: { t: string }[]): number {
  const days = new Set<string>();
  for (const p of curve) {
    const day = (p.t ?? "").slice(0, 10);
    if (!day) continue;
    const dow = new Date(`${day}T00:00:00Z`).getUTCDay();
    if (dow === 0 || dow === 6) continue;
    days.add(day);
  }
  return days.size;
}

export interface PortfolioPayload {
  state: PortfolioState;
  as_of: string | null;
  /** Which paper book this payload reads ("main" | "big"); absent on old payloads. */
  book?: string;
  scoreboard: Scoreboard;
  account?: AccountView;
  breaker?: BreakerState;
  curve: { t: string; portfolio_pct: number; spy_pct: number; qqq_pct?: number | null }[];
  composition: { idea: string; pct_of_book: number; unrealized_pl: number }[];
  positions: PositionRow[];
  /** One line per symbol (book.positions_aggregate); absent on old payloads. */
  positions_aggregate?: AggregatePositionRow[];
  /** Today split at the 4 PM ET close; absent on old payloads. */
  today?: TodaySplit | null;
}

export interface ClosedTrade {
  symbol: string;
  /** Curated sector (tradehub/portfolio/sectors.py); absent on old payloads. */
  sector?: string | null;
  qty: number;
  entry_price: number;
  exit_price: number;
  entered_at: string;
  exited_at: string;
  pnl: number;
  return_pct: number;
  held_days: number;
  idea: string;
  /** The reason the opening order stated, for discretionary trades (2026-11-11). */
  reason?: string | null;
}

/** Closed results split into tested ideas vs discretionary trades (2026-11-11):
 * the Portfolio answer to "which of this book's results came from a tested idea?" */
export interface ResultsSplitSide {
  trades: number;
  pnl: number;
  wins: number;
}

export interface ResultsSplit {
  tested: ResultsSplitSide;
  discretionary: ResultsSplitSide & {
    reasons: { reason: string; trades: number; pnl: number }[];
  };
}

export interface ActivityOrderLeg {
  symbol: string | null;
  side: string | null;
  ratio_qty: number | null;
  qty: number | null;
  filled_qty: number | null;
}

export interface ActivityOrder {
  symbol: string;
  side: string;
  /** A multi-leg parent's legs; empty for a plain order. The parent itself
   * carries no symbol, so the legs are what the row names. */
  legs?: ActivityOrderLeg[];
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
  results_split?: ResultsSplit | null;
}

export interface ClosedPayload {
  state: PortfolioState;
  as_of: string | null;
  /** Which paper book this payload reads ("main" | "big"); absent on old payloads. */
  book?: string;
  trades: ClosedTrade[];
  results_split?: ResultsSplit | null;
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
  const q0 = kept[0].qqq_pct;
  return kept.map((p) => ({
    t: p.t, portfolio_pct: rebase(p.portfolio_pct, kept[0].portfolio_pct), spy_pct: rebase(p.spy_pct, kept[0].spy_pct),
    qqq_pct: p.qqq_pct == null || q0 == null ? null : rebase(p.qqq_pct, q0),
  }));
}

/** The backend's label for a lot no Workshop idea claims (book.MANUAL). */
export const MANUAL_IDEA = "No idea yet (manual)";

/** A closed trade counts as tested when its lot was attributed to a Workshop
 * idea — the same rule book.results_split applies server-side. */
export function isTestedTrade(t: ClosedTrade): boolean {
  return !!t.idea && t.idea !== MANUAL_IDEA;
}

const etDateFmt = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
});

/** The America/New_York calendar date of an instant, YYYY-MM-DD. Trading
 * days are ET days; the hourly snapshots straddle UTC midnight. */
export function etDay(iso: string): string {
  return etDateFmt.format(new Date(iso));
}

export interface DailyReturn {
  date: string;
  portfolio_pct: number;
  spy_pct: number | null;
  /** QQQ's daily return, beside SPY's; null where a day lacks a QQQ price. */
  qqq_pct: number | null;
  /** Today, before its close is fixed history: the value still moves with
   * the live read (regular session) or was fixed by the 4 PM ET snapshot. */
  provisional: boolean;
}

/** Portfolio minus QQQ over the same span, in points (the Performance
 * stat cards; computed here, not in the TSX, per the page's path rules). */
export function aheadOfQqqPts(portfolioPct: number, qqqPct: number): number {
  return portfolioPct - qqqPct;
}

/** One return per ET trading day from the curve: the day's last point is its
 * close, differenced against the previous trading day's close. Weekends are
 * skipped (a weekend live point is not a trading day — the curveTradingDays
 * rule). Today is provisional; once the close snapshot exists (the today
 * split reads "after_hours"), today's figures are the split's regular-session
 * returns, because the curve's live point after 4 PM ET carries after-hours
 * moves and those never enter daily-close stats. */
export function dailyReturns(curve: CurvePoint[], today?: TodaySplit | null, now: Date = new Date()): DailyReturn[] {
  const lastByDay = new Map<string, CurvePoint>();
  for (const p of curve) {
    const d = etDay(p.t);
    const dow = new Date(`${d}T00:00:00Z`).getUTCDay();
    if (dow === 0 || dow === 6) continue;
    lastByDay.set(d, p); // the curve is time-ordered: the day's last point is its close
  }
  const days = [...lastByDay.entries()].sort(([a], [b]) => (a < b ? -1 : 1));
  const ratio = (a: number, b: number) => ((1 + a / 100) / (1 + b / 100) - 1) * 100;
  const out: DailyReturn[] = [];
  for (let i = 1; i < days.length; i++) {
    const [date, p] = days[i];
    const prev = days[i - 1][1];
    out.push({
      date,
      portfolio_pct: ratio(p.portfolio_pct, prev.portfolio_pct),
      spy_pct: p.spy_pct == null || prev.spy_pct == null ? null : ratio(p.spy_pct, prev.spy_pct),
      qqq_pct: p.qqq_pct == null || prev.qqq_pct == null ? null : ratio(p.qqq_pct, prev.qqq_pct),
      provisional: false,
    });
  }
  const last = out[out.length - 1];
  if (last && last.date === etDay(now.toISOString())) {
    last.provisional = true;
    if (today?.state === "after_hours") {
      if (today.regular_pct != null) last.portfolio_pct = today.regular_pct;
      if (today.spy_regular_pct != null) last.spy_pct = today.spy_regular_pct;
      // A null QQQ regular figure means unknown, not "keep the curve
      // value": the curve's live point can carry after-hours moves, so
      // the day must not show them as its regular-session return
      // (CodeRabbit, PR #514).
      last.qqq_pct = today.qqq_regular_pct ?? null;
    }
  }
  return out;
}

/** Running drawdown of the curve's portfolio line: peak-relative, as a
 * return — (1 + p) / (1 + peak) − 1 over the cumulative curve. Subtracting
 * percentage points overstates it (from +10% to −5% is a −13.6% drawdown,
 * not −15.0) — Claude's #509 review. */
export function drawdownSeries(points: CurvePoint[]): { t: string; dd_pct: number }[] {
  let peak = -Infinity;
  return points.map((p) => {
    peak = Math.max(peak, p.portfolio_pct);
    return { t: p.t, dd_pct: ((1 + p.portfolio_pct / 100) / (1 + peak / 100) - 1) * 100 };
  });
}

/** The deepest drawdown in the points and when it bottomed. */
export function maxDrawdown(points: CurvePoint[]): { pct: number | null; at: string | null } {
  let pct: number | null = null;
  let at: string | null = null;
  for (const d of drawdownSeries(points)) {
    if (pct == null || d.dd_pct < pct) {
      pct = d.dd_pct;
      at = d.t;
    }
  }
  return { pct, at };
}

/** Annualized volatility (%) of the daily portfolio returns; null under 2 days. */
export function volatilityPct(daily: DailyReturn[]): number | null {
  if (daily.length < 2) return null;
  const xs = daily.map((d) => d.portfolio_pct);
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
  const variance = xs.reduce((a, x) => a + (x - mean) ** 2, 0) / (xs.length - 1);
  return Math.sqrt(variance) * Math.sqrt(252);
}

/** Beta of the daily portfolio returns to SPY's; null under 2 paired days
 * or when SPY never moved. The caller applies the 20-trading-day guard. */
export function betaToSpy(daily: DailyReturn[]): number | null {
  const pairs = daily.filter((d) => d.spy_pct != null);
  if (pairs.length < 2) return null;
  const mp = pairs.reduce((a, d) => a + d.portfolio_pct, 0) / pairs.length;
  const ms = pairs.reduce((a, d) => a + (d.spy_pct ?? 0), 0) / pairs.length;
  let cov = 0;
  let variance = 0;
  for (const d of pairs) {
    cov += (d.portfolio_pct - mp) * ((d.spy_pct ?? 0) - ms);
    variance += ((d.spy_pct ?? 0) - ms) ** 2;
  }
  return variance === 0 ? null : cov / variance;
}

export function bestWorstDay(daily: DailyReturn[]): { best: DailyReturn | null; worst: DailyReturn | null } {
  let best: DailyReturn | null = null;
  let worst: DailyReturn | null = null;
  for (const d of daily) {
    if (!best || d.portfolio_pct > best.portfolio_pct) best = d;
    if (!worst || d.portfolio_pct < worst.portfolio_pct) worst = d;
  }
  return { best, worst };
}

export interface TradeStats {
  trades: number;
  win_rate: number | null;
  avg_win: number | null;
  /** Mean losing trade, as a negative dollar figure. */
  avg_loss: number | null;
  profit_factor: number | null;
  avg_held_days: number | null;
}

export function tradeStats(trades: ClosedTrade[]): TradeStats {
  const empty: TradeStats = {
    trades: 0, win_rate: null, avg_win: null, avg_loss: null, profit_factor: null, avg_held_days: null,
  };
  if (trades.length === 0) return empty;
  const wins = trades.filter((t) => t.pnl > 0);
  const losses = trades.filter((t) => t.pnl < 0);
  const grossWin = wins.reduce((a, t) => a + t.pnl, 0);
  const grossLoss = losses.reduce((a, t) => a + t.pnl, 0);
  return {
    trades: trades.length,
    win_rate: (wins.length / trades.length) * 100,
    avg_win: wins.length ? grossWin / wins.length : null,
    avg_loss: losses.length ? grossLoss / losses.length : null,
    profit_factor: grossLoss < 0 ? grossWin / -grossLoss : null,
    avg_held_days: trades.reduce((a, t) => a + t.held_days, 0) / trades.length,
  };
}

/** The cutoff curveRange applies, for filtering closed trades to a range. */
export function rangeCutoff(range: CurveRange, now: Date = new Date()): Date | null {
  if (range === "All") return null;
  const since = new Date(now);
  if (range === "1W") since.setDate(since.getDate() - 7);
  else if (range === "1M") since.setMonth(since.getMonth() - 1);
  else since.setMonth(0, 1);
  return since;
}

export function tradesInRange(trades: ClosedTrade[], range: CurveRange, now: Date = new Date()): ClosedTrade[] {
  const cut = rangeCutoff(range, now);
  return cut ? trades.filter((t) => new Date(t.exited_at) >= cut) : trades;
}

export interface PnlSlice {
  key: string;
  realized: number;
  open: number;
  total: number;
}

function pnlSlices(slotOf: (add: (key: string, realized: number, open: number) => void) => void): PnlSlice[] {
  const map = new Map<string, PnlSlice>();
  const add = (key: string, realized: number, open: number) => {
    let s = map.get(key);
    if (!s) {
      s = { key, realized: 0, open: 0, total: 0 };
      map.set(key, s);
    }
    s.realized += realized;
    s.open += open;
  };
  slotOf(add);
  return [...map.values()]
    .map((s) => ({ ...s, total: s.realized + s.open }))
    .sort((a, b) => Math.abs(b.total) - Math.abs(a.total));
}

/** Realized P&L (the trades given — the caller range-filters them) plus the
 * book's current open P&L, per idea. */
export function pnlByIdea(
  trades: ClosedTrade[],
  composition: { idea: string; unrealized_pl: number }[],
): PnlSlice[] {
  return pnlSlices((add) => {
    for (const t of trades) add(t.idea || MANUAL_IDEA, t.pnl, 0);
    for (const c of composition) add(c.idea, 0, c.unrealized_pl);
  });
}

/** The same split per sector: realized off the trades' sector, open off the
 * position rows'. A trade from an old payload without a sector reads Other,
 * the sector map's own fallback. */
export function pnlBySector(trades: ClosedTrade[], positions: PositionRow[]): PnlSlice[] {
  return pnlSlices((add) => {
    for (const t of trades) add(t.sector || "Other", t.pnl, 0);
    for (const r of positions) {
      if (r.unrealized_pl != null) add(r.sector || "Other", 0, r.unrealized_pl);
    }
  });
}

export interface SplitPoint {
  t: string;
  tested: number;
  discretionary: number;
}

/** Cumulative realized P&L of tested ideas vs discretionary trades, one
 * point per closed trade in exit order. */
export function splitOverTime(trades: ClosedTrade[]): SplitPoint[] {
  const sorted = [...trades].sort((a, b) => (a.exited_at < b.exited_at ? -1 : 1));
  let tested = 0;
  let discretionary = 0;
  return sorted.map((t) => {
    if (isTestedTrade(t)) tested += t.pnl;
    else discretionary += t.pnl;
    return { t: t.exited_at, tested: Math.round(tested * 100) / 100, discretionary: Math.round(discretionary * 100) / 100 };
  });
}

export interface WeekPnl {
  /** The week's Monday, YYYY-MM-DD (ET). */
  week: string;
  pnl: number;
  trades: number;
}

export function realizedByWeek(trades: ClosedTrade[]): WeekPnl[] {
  const map = new Map<string, WeekPnl>();
  for (const t of trades) {
    const day = new Date(`${etDay(t.exited_at)}T00:00:00Z`);
    const monday = new Date(day);
    monday.setUTCDate(day.getUTCDate() - ((day.getUTCDay() + 6) % 7));
    const key = monday.toISOString().slice(0, 10);
    let s = map.get(key);
    if (!s) {
      s = { week: key, pnl: 0, trades: 0 };
      map.set(key, s);
    }
    s.pnl += t.pnl;
    s.trades += 1;
  }
  return [...map.values()]
    .sort((a, b) => (a.week < b.week ? -1 : 1))
    .map((w) => ({ ...w, pnl: Math.round(w.pnl * 100) / 100 }));
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

/** What an order row names: a plain order names its symbol; a multi-leg
 * parent has no symbol of its own, so it names its legs (2026-11-12 --
 * the recent-orders list showed a bare "3/3 filled" for combos). */
export function orderLabel(o: ActivityOrder): string {
  if (o.legs && o.legs.length > 0) {
    return o.legs
      .map((l) => (l.symbol ? (contractLabel(l.symbol) ?? l.symbol) : "—"))
      .join(" / ");
  }
  return o.symbol ? (contractLabel(o.symbol) ?? o.symbol) : "—";
}

/** The full orders table's label: for a multi-leg order, each leg's own
 * side and quantity ride with the leg ("buy 1 SPY Nov 11 2026 $750 put /
 * sell 1 SPY Nov 11 2026 $749 put"), so a spread and its reverse read
 * differently — the compact list's orderLabel alone cannot tell them
 * apart. A plain order reads as its orderLabel, unchanged. */
export function orderDetailLabel(o: ActivityOrder): string {
  if (o.legs && o.legs.length > 0) {
    return o.legs
      .map((l) => {
        const name = l.symbol ? (contractLabel(l.symbol) ?? l.symbol) : "—";
        const verb = (l.side ?? "").split("_")[0];
        const qty = l.ratio_qty ?? l.qty;
        return [verb || null, qty != null ? String(qty) : null, name]
          .filter(Boolean).join(" ");
      })
      .join(" / ");
  }
  return orderLabel(o);
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

export interface IdeaCard {
  idea: string;
  id: number | null;
  positions: number;
  value: number;
  /** Gross exposure over equity: a short counts at its size, not netted
   * against longs. Null when equity itself is unknown. */
  pct: number | null;
  /** Null when any holding's figure is unknown: a missing figure is never read as zero. */
  day_pl: number | null;
  unrealized: number | null;
  /** Open P&L over gross cost; null when nothing is held or a figure is unknown. */
  return_pct: number | null;
  /** The idea's set size, % of the book; known only for live ideas the admin list returns. */
  target_pct: number | null;
}

/**
 * One row per idea in the book: what it holds, today's move, the open P&L, and how far it sits
 * from its set size. Manual shares are one row per symbol, so a hand position never hides inside
 * a bucket. Live ideas that hold nothing yet still appear, at zero.
 * ponytail: keyed by title, since positions carry only the title; two live ideas sharing a title would merge.
 */
export function ideaScorecard(rows: PositionRow[], equity: number | null,
                              live: { id: number; title: string; size_pct: number | null }[]): IdeaCard[] {
  const cards = new Map<string, IdeaCard & { gross: number; cost: number }>();
  const card = (idea: string) => {
    if (!cards.has(idea)) {
      const l = live.find((x) => x.title === idea);
      cards.set(idea, { idea, id: l?.id ?? null, positions: 0, value: 0, pct: 0, day_pl: 0, unrealized: 0,
                        return_pct: null, target_pct: l?.size_pct ?? null, gross: 0, cost: 0 });
    }
    return cards.get(idea)!;
  };
  for (const r of rows) {
    const c = card(r.idea && r.idea !== "No idea yet (manual)" ? r.idea : `${r.symbol} (manual)`);
    c.positions += 1;
    c.value += r.market_value;
    c.gross += Math.abs(r.market_value);
    c.day_pl = c.day_pl == null || r.day_pl == null ? null : c.day_pl + r.day_pl;
    c.unrealized = c.unrealized == null || r.unrealized_pl == null ? null : c.unrealized + r.unrealized_pl;
    c.cost += Math.abs(r.cost_basis ?? r.market_value - (r.unrealized_pl ?? 0));
  }
  for (const l of live) card(l.title);
  return [...cards.values()]
    .map(({ gross, cost, ...c }) => ({
      ...c,
      pct: equity ? (gross / equity) * 100 : null,
      return_pct: c.positions && c.unrealized != null && cost ? (c.unrealized / cost) * 100 : null,
    }))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
}

/** Today's biggest movers by dollar P&L, gains and losses apart. `known` is false when no row has a day figure. */
export function dayMovers(rows: PositionRow[], n = 3): { up: PositionRow[]; down: PositionRow[]; known: boolean } {
  const moved = rows.filter((r) => r.day_pl);
  return {
    up: moved.filter((r) => r.day_pl! > 0).sort((a, b) => b.day_pl! - a.day_pl!).slice(0, n),
    down: moved.filter((r) => r.day_pl! < 0).sort((a, b) => a.day_pl! - b.day_pl!).slice(0, n),
    known: rows.some((r) => r.day_pl != null),
  };
}

/** The Portfolio card's payload (GET /api/portfolio/portfolio-check): thesis weights against the
 * caps and targets, cluster exposures, cash, and the latest check outcomes -- the same engine
 * (tradehub.portfolio.portfolio_check) and stored state the order and activation gates read. */
export interface PortfolioCheckMember {
  symbol: string;
  weight_pct: number;
  target_pct: number | null;
  max_pct: number | null;
  min_pct: number | null;
  status: "ok" | "over" | "under";
}

export interface PortfolioCheckSleeve {
  id: string;
  label: string;
  weight_pct: number;
  sleeve_max_pct: number | null;
  exit_only: boolean;
  status: "ok" | "over" | "under";
  correlation_to_book: number | null;
  members: PortfolioCheckMember[];
}

export interface PortfolioCheckEvent {
  at: string | null;
  source: string | null;
  symbol: string | null;
  outcome: "pass" | "warn" | "block" | "unavailable" | null;
  detail: string | null;
}

export interface PortfolioCheckState {
  book: string;
  as_of: string;
  equity: number;
  cash: number;
  cash_pct: number | null;
  invested: number;
  sleeves: PortfolioCheckSleeve[];
  unassigned: { symbol: string; weight_pct: number }[];
  clusters: Record<string, { label: string; pct: number; with_flagged_pct?: number }>;
  recent_checks: PortfolioCheckEvent[];
  targets_updated_at: string | null;
  series_refreshed_at: string | null;
  unpriced: string[];
}
