/** The Workshop (Trading HQ step 2): payload types, the signed-in fetch, and the plain words for each claim. */
import { sessionToken } from "@/components/RequireAdmin";
import { buildApiUrl } from "@/lib/api";
import type { NearMiss } from "@/lib/screening";

export type Claim = "beats_benchmark" | "beats_benchmark_when" | "ballast" | "smoother_ride";
export type Verdict = "PASS" | "FAIL" | "NOT ENOUGH DATA";

export type Measure =
  | "level" | "change" | "pct_change" | "vs_sma" | "sma_cross" | "rsi" | "macd" | "vs_high" | "vs_low" | "volatility" | "vs_vwap"
  | "net_upgrades" | "target_upside" | "zscore" | "percentile" | "revision";

export interface Condition {
  source: "fred" | "price" | "analyst" | "spread" | "news" | "dune";
  series: string;
  measure: Measure;
  lookback_days: number;
  slow_days?: number | null;
  op: ">" | "<";
  threshold: number;
}

export interface Group {
  mode: "all" | "any";
  conditions: Condition[];
}

/** Step 6: buy when `enter` holds; with `exit`, hold until `exit` holds (exit wins a tie). */
export interface Rules {
  enter: Group;
  exit: Group | null;
}

/** Each measure: its menu label, the units hint, and which sources can use it. */
type Src = Condition["source"];
const P: Src[] = ["price"];
const FP: Src[] = ["fred", "price", "spread", "dune"];
const ANY: Src[] = ["fred", "price", "spread", "dune"];
const WITH_NEWS: Src[] = ["fred", "price", "spread", "news", "dune"];
export const MEASURES: { value: Measure; label: string; hint: string; sources: Src[] }[] = [
  { value: "level", label: "level", hint: "the value itself (for news: the day's mean article tone, -100..+100)", sources: WITH_NEWS },
  { value: "change", label: "change", hint: "change over N days, in the series' own units", sources: WITH_NEWS },
  { value: "pct_change", label: "% change", hint: "% change over N days", sources: ["fred", "price", "dune"] },
  { value: "vs_sma", label: "vs its average", hint: "% above its N-day average", sources: FP },
  { value: "volatility", label: "volatility", hint: "N-day volatility, % a year", sources: FP },
  { value: "sma_cross", label: "average cross", hint: "% the N-day average is above the slow average", sources: P },
  { value: "rsi", label: "RSI", hint: "N-day RSI, 0-100 (below 30 = oversold)", sources: P },
  { value: "macd", label: "MACD", hint: "MACD 12/26/9 minus its signal, % of price (above 0 = bullish)", sources: P },
  { value: "vs_high", label: "vs N-day high", hint: "% above the prior N-day high (above 0 = breakout)", sources: P },
  { value: "vs_low", label: "vs N-day low", hint: "% above the prior N-day low (below 0 = breakdown)", sources: P },
  { value: "vs_vwap", label: "vs VWAP", hint: "% above its N-day VWAP", sources: P },
  { value: "zscore", label: "z-score", hint: "standard deviations from its N-day average (2 = stretched)", sources: WITH_NEWS },
  { value: "percentile", label: "percentile", hint: "today's rank among the last N days, 0-100 (95 = near the top)", sources: ANY },
  { value: "revision", label: "revision", hint: "how far the freshest print has been revised from its first print, in the series' own units (monthly series like PAYEMS)", sources: ["fred"] },
  { value: "net_upgrades", label: "net upgrades", hint: "analyst upgrades minus downgrades over N trading days", sources: ["analyst"] },
  { value: "target_upside", label: "target upside", hint: "% the average price target set in the last N trading days is above the price", sources: ["analyst"] },
];

export interface Execution {
  order_type: "market" | "limit";
  timing: "open" | "close" | "day";
  limit_offset_bps: number;
}

export interface Exits {
  stop_loss_pct: number | null;
  trailing_pct: number | null;
  take_profit_pct: number | null;
  max_days: number | null;
  mode: "close" | "intraday";
}

export const NO_EXITS: Exits = { stop_loss_pct: null, trailing_pct: null, take_profit_pct: null, max_days: null, mode: "close" };

export const DEFAULT_EXECUTION: Execution = { order_type: "market", timing: "open", limit_offset_bps: 0 };

export const ORDER_OPTIONS: { value: string; label: string }[] = [
  { value: "market:open", label: "Market at the open" },
  { value: "market:close", label: "Market at the close (fills a day later)" },
  { value: "market:day", label: "Market, during the day" },
  { value: "limit:open", label: "Limit at the open" },
  { value: "limit:close", label: "Limit at the close (fills a day later)" },
  { value: "limit:day", label: "Limit, during the day" },
];

/** One option leg (§2.3): strike as % of the price at entry; priced with a model, never real history. */
export interface OptionLeg {
  underlying: string;
  kind: "call" | "put";
  side: "buy" | "sell";
  strike_pct: number;
  days_to_expiry: number;
  roll_days_left: number;
  qty_per_share: number;
}

export interface IdeaSpec {
  title: string;
  hold: string[];
  options?: OptionLeg[];
  short?: string[];
  execution?: Execution;
  exits?: Exits;
  /** Judge (and trade) the idea as `idea_share` of a portfolio whose rest is `core`, equal weight, daily. */
  portfolio?: { core: string[]; idea_share: number } | null;
  rules: Rules | null;
  /** Steps 2-5 runs stored one condition; the server reads it as a one-condition buy rule. */
  when?: Condition | null;
  otherwise: string;
  claim: Claim;
  benchmark: string;
  cost_bps: number;
  slippage_bps?: number;
  borrow_bps_yr?: number;
  start: string;
  unseen_fraction: number;
  assumptions: string[];
}

/** An event study (earnings, FOMC/CPI/jobs days, price gaps), measured the IB Python Models way. */
export interface EventSpec {
  kind: "event";
  title: string;
  tickers: string[];
  event: "earnings" | "fomc" | "cpi" | "jobs" | "gap" | "custom";
  custom?: { ticker: string; date: string; surprise: number | null }[];
  when: "all" | "beat" | "miss" | "up" | "down";
  gap_pct: number;
  window: "reaction" | "drift_1_3" | "drift_1_5" | "drift_1_10";
  direction: "up" | "down";
  benchmark: string;
  start: string;
  unseen_fraction: number;
  assumptions: string[];
}

export const EVENT_LABELS: Record<EventSpec["event"], string> = {
  earnings: "Earnings prints", fomc: "FOMC statement days", cpi: "CPI release days", jobs: "Jobs report days", gap: "Price gaps",
  custom: "My own dates (paste a table)",
};
export const WINDOW_LABELS: Record<EventSpec["window"], string> = {
  reaction: "The reaction day", drift_1_3: "Days +1 to +3", drift_1_5: "Days +1 to +5", drift_1_10: "Days +1 to +10",
};

/** Rows of a pasted event table: `ticker,date[,surprise]`, or a notebook CSV whose header names
 *  ticker / report_date (or date) / surprise_pct (or surprise). Tabs or commas. Bad rows are skipped. */
export function parseEventTable(text: string): { ticker: string; date: string; surprise: number | null }[] {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (!lines.length) return [];
  const cells = (l: string) => l.split(/[,\t]/).map((c) => c.trim());
  const head = cells(lines[0]).map((c) => c.toLowerCase());
  const named = head.includes("ticker");
  const col = (names: string[], fallback: number) => {
    const i = head.findIndex((h) => names.includes(h));
    return named ? i : fallback;
  };
  const [ti, di, si] = [col(["ticker"], 0), col(["report_date", "date", "reaction_day", "event_date"], 1), col(["surprise_pct", "surprise"], 2)];
  const out: { ticker: string; date: string; surprise: number | null }[] = [];
  for (const line of named ? lines.slice(1) : lines) {
    const c = cells(line);
    const ticker = (c[ti] ?? "").toUpperCase();
    const date = (c[di] ?? "").slice(0, 10);
    if (!/^[A-Z][A-Z0-9.-]{0,9}$/.test(ticker) || !/^\d{4}-\d{2}-\d{2}$/.test(date)) continue;
    const s = si >= 0 && c[si] !== undefined && c[si] !== "" ? Number(c[si]) : NaN;
    out.push({ ticker, date, surprise: Number.isFinite(s) ? s : null });
  }
  return out;
}

export function isEvent(spec: unknown): spec is EventSpec {
  return (spec as { kind?: string } | null)?.kind === "event";
}

export interface EventRow {
  date: string; ticker: string; surprise: number | null; ar0: number; car_1_3: number; car_1_5: number; car_1_10: number; pre_5: number;
}

export interface RunAutopsy {
  status: "ok" | "too_few" | "unavailable";
  trades?: number;
  losers?: number;
  pattern?: { implicates: "gate" | "entry" | "exit" | "sizing"; text: string } | null;
  suggestion?: string | null;
  suggestions_left?: number;
}

export interface RunResult {
  verdict: Verdict;
  headline: string;
  reason: string | null;
  split_date: string | null;
  data_start: string | null;
  data_end: string | null;
  claim: { built: { holds: boolean; value: number | null; label: string }; unseen: { holds: boolean; value: number | null; label: string } } | null;
  shuffle: { beats_pct: number; p: number; bar: number; permutations: number; seed: number; method: string; holds?: boolean } | null;
  t_test: { mean_daily_diff: number; t: number; p: number; holds?: boolean } | null;
  periods: { held: number; of: number; holds?: boolean | null } | null;
  /** Why it lost: the recurring pattern in its losing trades. Old runs have none. */
  autopsy?: RunAutopsy | null;
  walk_forward?: {
    folds: { start: string; end: string; days: number; holds: boolean | null; value: number | null; label: string; idea_cagr: number | null; bench_cagr: number | null }[];
    held: number; of: number;
  } | null;
  notes?: string[];
  /** Present when the spec carries option legs: the model-prices label and each leg's vol source. */
  options?: { model_prices: boolean; legs: (OptionLeg & { vol: string })[] } | null;
  variations: number;
  context: { name: string; built_cagr: number | null; unseen_cagr: number | null; unseen_max_dd: number | null }[];
  curve: { t: string; idea: number; benchmark: number }[];
  n_events?: number;
  per_ticker?: { ticker: string; n: number; mean: number; shrunk: number; weight: number; t: number }[];
  events?: EventRow[];
  /** The claim-typed battery (spec 2026-11-08). On event runs, since Amendment 2
   * (2026-11-08) the battery's verdict is the run's verdict. */
  battery?: {
    type: string;
    verdict?: Verdict;
    p?: number | null;
    legs?: { name: string; holds: boolean; detail: string }[];
    spans?: { unseen?: { peer?: { n: number; mean: number; t: number; hit: number } | null } };
  } | null;
  /** The old random-dates event gate, preserved as a named control on event
   * runs made since Amendment 2. Null when the run predates it (the gate's
   * numbers then sit at top level, where they were the verdict's own). */
  legacy_event_gate?: {
    verdict: Verdict;
    shuffle: { beats_pct: number; p: number; bar: number; permutations: number; seed: number; method: string; holds?: boolean };
  } | null;
  /** The bar this verdict was judged under, stamped at record time (A2,
   * 2026-11-11). Absent on runs recorded before the stamp existed. */
  bar?: { standard: string; p_max: number; wf_min_share: number; shuffle_bar: number | null } | null;
  /** The search this run's idea belongs to, stamped at record time (A3,
   * 2026-11-11): the shuffle bar was raised by the trials in the batch, and
   * `of` is the count that raised it. Absent on unbatched ideas' runs and on
   * runs recorded before the stamp existed. */
  batch?: { id: string; trial: number | null; position: number; of: number } | null;
}

/** An idea's standing in its search (A3, 2026-11-11): trial `position` of
 * `size` in batch `id`; `trial` is the recorded trial number where the
 * search recorded one (null for Gen 2, whose numbers were never kept). */
export interface BatchInfo {
  id: string;
  trial: number | null;
  size: number;
  position: number;
}

export interface Run {
  id: number;
  variation: number;
  spec: IdeaSpec;
  draft_model: string | null;
  verdict: Verdict;
  result: RunResult;
  created_at: string;
  /** Save-by-choice (2026-11-02): null while the run is an unsaved preview. Only
   * saved runs count toward the record, the gate, and tracking. */
  saved_at: string | null;
  /** Standing under the current bar (A2, 2026-11-11): verdict is the as-run
   * history; verdict_now is what the run is worth under today's bar, with
   * the two legs that decided it. Absent on payloads that predate A2. */
  verdict_now?: Verdict | null;
  p_ok?: boolean | null;
  wf_ok?: boolean | null;
  p?: number | null;
}

export interface Idea {
  id: number;
  title: string;
  plain_words: string;
  /** Kevin's own groupings (2026-11-05). */
  tags?: string[];
  created_at: string;
  published_at?: string | null;
  tracked_at?: string | null;
  tracked_run_id?: number | null;
  live_at?: string | null;
  killed_at?: string | null;
  size_pct?: number | null;
  auto_orders?: boolean;
}

export interface PaperOrder {
  id: number;
  day: string;
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  client_order_id: string;
  status: "sent" | "already sent" | "skipped" | "rejected";
  reason: string | null;
  alpaca_order_id: string | null;
}

/** One book's live state for an idea (second book, 2026-11-02): the books are
 * independent -- an idea can be live on either, both, or neither, at different
 * sizes. Main reads off the idea row; other books read their own activation. */
export interface BookLiveState {
  live_at: string | null;
  size_pct: number | null;
  auto_orders: boolean;
  killed_at: string | null;
  /** The gate record stored when the idea went live on this book (an override
   * leaves its deliberate-call record here); null when it never went live. */
  gate: Record<string, unknown> | null;
  orders_enabled: boolean;
}

/** One Spec F LEAPS shadow pair (or unfilled trigger) — idea 81's trial rows. */
export interface LeapsPair {
  id: number;
  ticker: string;
  status: string;
  opened_at: string;
  crossing_id?: number | null;
  zone?: string | null;
  action?: string | null;
  guide_status?: string | null;
  trigger_price?: number | null;
  occ_symbol?: string | null;
  strike?: number | null;
  expiry?: string | null;
  contracts?: number | null;
  entry_bid?: number | null;
  entry_mid?: number | null;
  entry_ask?: number | null;
  premium_total?: number | null;
  delta_at_entry?: number | null;
  extrinsic_at_entry?: number | null;
  iv_at_entry?: number | null;
  spot_at_entry?: number | null;
  delta_notional?: number | null;
  share_shares?: number | null;
  share_entry_price?: number | null;
  marked_at?: string | null;
  leaps_mid?: number | null;
  mark_stale?: boolean;
  share_price?: number | null;
  dte?: number | null;
  roll_flag?: boolean;
  leaps_pnl?: number | null;
  share_pnl?: number | null;
  delta_delivered?: number | null;
  carry_drag_pct?: number | null;
  close_reason?: string | null;
  closed_at?: string | null;
}

export interface LeapsSummary {
  pairs_opened: number;
  pairs_open: number;
  pairs_closed: number;
  unfilled: number;
  mean_carry_drag_pct: number | null;
  mean_delta_delivered: number | null;
  premium_cash: number;
  share_cash: number;
  premium_pct_of_share_cash: number | null;
  trial_start: string | null;
  gate: { state: string; judged: boolean; pairs: number; needed: number; reason: string | null;
          stored?: boolean; judged_at?: string | null;
          cohort_pairs?: number | null;
          mean_carry_drag_pct?: number | null; mean_delta_delivered?: number | null;
          extension?: { state: string; reason: string | null;
                        stored?: boolean; judged_at?: string | null } | null };
}

export interface LeapsPanelData {
  idea_id: number;
  summary: LeapsSummary;
  pairs: LeapsPair[];
  unfilled: LeapsPair[];
}

export interface IdeaDetail {
  idea: Idea;
  runs: Run[];
  /** The search this idea is one trial of (A3); null for a solo idea. */
  batch?: BatchInfo | null;
  /** The Spec F LEAPS shadow panel; present only for ideas tagged leaps-trial. */
  leaps?: LeapsPanelData | null;
  tag?: string;
  shadow?: ShadowSummary | null;
  orders_enabled?: boolean;
  orders?: PaperOrder[];
  /** Per-book live state, keyed by book name ("main", "big"). */
  books?: { main: BookLiveState; big: BookLiveState };
}

export interface GateResult {
  status: "ready" | "waiting" | "fails";
  new_days: number;
  needed: number;
  claim: { holds: boolean | null; label: string; days: number } | null;
  size_ok: boolean | null;
  reasons: string[];
}

export interface FillRow {
  order_id: string;
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  price: number;
  at: string;
  tag: string | null;
  idea_id: number | null;
  idea: string;
  history: { from: number | null; to: number | null; by: string; at: string }[];
}

export interface IdeaRow {
  id: number;
  title: string;
  created_at: string;
  runs: number;
  latest_verdict: Verdict | null;
  /** Standing under the current bar (A2): the chip reads this first. */
  verdict_now?: Verdict | null;
  /** The search this idea is one trial of (A3); null for a solo idea. */
  batch?: BatchInfo | null;
  published_at: string | null;
  tracked_at: string | null;
  live_at: string | null;
  killed_at: string | null;
}

/** The one-click play check (Kevin, 2026-11-02): the idea's target book at a
 * size against the live paper portfolio. Read-only -- it places nothing. */
export interface PlayCheckRow {
  ticker: string;
  weight: number | null;
  price: number | null;
  target_value: number;
  target_shares: number | null;
  held_shares: number;
  held_value: number;
  delta_value: number;
  delta_shares: number | null;
  coverage_pct: number | null;
  overlap_ideas: string[];
  cap_breach: boolean;
}

export interface PlayCheckResult {
  available: boolean;
  note?: string;
  book?: string;
  book_label?: string;
  sleeve_usd?: number;
  already_in_place_usd?: number;
  in_place_pct?: number;
  state?: "in" | "out";
  exit_reason?: string | null;
  otherwise?: string;
  size_pct: number;
  equity?: number;
  cash?: number;
  rows?: PlayCheckRow[];
  buys?: number;
  sells?: number;
  verdict?: "affordable" | "affordable_after_sells" | "not_affordable";
  shortfall?: number;
  cap_breaches?: { ticker: string; pct: number; cap: number }[];
  verdict_line?: string;
  as_of?: string | null;
  options_legs?: OptionLeg[];
  notes?: string[];
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public body: Record<string, unknown> | null) {
    super(message);
  }
}

/** Save a signed-in file response (the run's daily CSV) to the browser's downloads. */
export async function adminDownload(path: string, filename: string): Promise<void> {
  const token = await sessionToken();
  const response = await fetch(buildApiUrl(path), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!response.ok) throw new ApiError(`Download failed (${response.status})`, response.status, null);
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a); // Safari needs the link in the page, and the URL alive until the download starts
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** A run, year by year, plus the rolling 12-month excess return (the deeper look). */
export interface RunAnalysis {
  data_end: string | null;
  /** Recomputed total return minus the stored verdict's, in points; null when it can't be compared. */
  drift_pts?: number | null;
  years: { year: number; idea: number; bench: number; excess: number; days_in: number; idea_in: number | null }[];
  rolling: { t: string; excess: number }[];
}

/** The playbook play the draft was matched to, and why (the words that matched). */
export interface PlayMatch {
  id: string;
  name: string;
  summary: string;
  source: string;
  why: string[];
}

export interface DraftResponse {
  spec: IdeaSpec;
  model: string;
  play: PlayMatch | null;
  alternatives: (PlayMatch & { spec: IdeaSpec })[];
  dropped?: string[];
  /** What the drafter confessed it could not express (§2.2 envelope) -- shown, never silent. */
  unexpressed?: string[];
}

export function legText(leg: OptionLeg): string {
  return `${leg.side} ${leg.underlying} ${leg.kind} @ ${leg.strike_pct}% of spot, ${leg.days_to_expiry}d` +
    `${leg.roll_days_left ? `, roll at ${leg.roll_days_left}d left` : ""}` +
    `${leg.qty_per_share !== 1 ? `, ${leg.qty_per_share} per share` : ""}`;
}

/** The market's own numbers stored on a debate at run time (hub-side yfinance). */
export interface MarketAnchor {
  price: number;
  prev_close: number | null;
  year_high: number | null;
  year_low: number | null;
  at: string;
}

/** A cached live price for the feed's "now" column. */
export interface LivePrice {
  price: number;
  at: string;
}

/** One agent-debate card (feed spec §6): every label the payload resolved server-side. */
export interface AgentDebateCard {
  source: "agent_debate";
  chip: string;
  run_id: string;
  ticker: string;
  decision: string;
  run_at_ct: string;
  as_of_date: string;
  historical: boolean;
  historical_label: string | null;
  framework_version: string;
  framework_short: string;
  llm_provider: string;
  llm_model: string;
  status: string;
  error: string | null;
  market_anchor: MarketAnchor | null;
  live: LivePrice | null;
  stale: boolean;
  cost_usd: number | string;
  inputs_note: string;
  analyst_summaries: Record<string, string>;
  bull_case: string;
  bear_case: string;
  trader_rationale: string;
  risk_verdict: string;
  has_report: boolean;
  grades: Record<string, { ret_pct: number; outcome: string } | "pending">;
}

export interface DebateRecordSummary {
  h5: { graded: number; hits: number; hit_rate: number | null; no_calls: number };
  h20: { graded: number; hits: number; hit_rate: number | null; no_calls: number };
  banner: boolean;
}

export interface AgentDebateFeed {
  chip: string;
  cards: AgentDebateCard[];
  record: DebateRecordSummary;
  banner: string | null;
}

/** A Workshop request that answers in plain text (a debate's markdown report). */
export async function adminText(path: string): Promise<string> {
  const token = await sessionToken();
  const response = await fetch(buildApiUrl(path), {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) throw new ApiError(`Request failed (${response.status})`, response.status, null);
  return response.text();
}

/** The import door's request body: a spec drafted out-of-band (in chat), with the same
 * envelope fields the server-side drafter returns. */
export interface SpecImport {
  spec: IdeaSpec;
  requested?: string[];
  unexpressed?: string[];
}

export type TickerNames = Record<string, { name: string; kind: string } | null>;

/** A Workshop request, signed with Kevin's session. Errors carry the server's detail and parsed body. */
export async function adminJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await sessionToken();
  const response = await fetch(buildApiUrl(path), {
    ...init,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers },
  });
  let body: Record<string, unknown> | null = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? `That draft has a field the test can't use: ${String(detail[0]?.msg ?? "").replace(/^Value error, /, "")}` : `Request failed (${response.status})`;
    throw new ApiError(message, response.status, body);
  }
  return body as T;
}

const CLAIMS: Record<Claim, string> = {
  beats_benchmark: "Beats the benchmark after costs",
  beats_benchmark_when: "Beats the benchmark while the rule has it in",
  ballast: "Ballast: loses less than SPY on its down days and is up overall, or goes up when SPY falls",
  smoother_ride: "Smoother ride: a shallower worst drop at a similar return",
};

export function claimLabel(claim: Claim): string {
  return CLAIMS[claim];
}

export const CLAIM_OPTIONS = Object.keys(CLAIMS) as Claim[];

export function verdictTone(v: Verdict | null): "ok" | "bad" | "flat" {
  if (v === "PASS") return "ok";
  if (v === "FAIL") return "bad";
  return "flat";
}

export function conditionText(c: Condition | null): string {
  if (!c) return "always";
  const { series: s, lookback_days: n, op, threshold: t } = c;
  const zero = t === 0;
  switch (c.measure) {
    case "level": return c.source === "spread" ? `${s} spread ${op} ${t}` : `${s} ${op} ${t}`;
    case "revision": return `${s} latest-print revision ${op} ${t}`;
    case "zscore": return `${s}${c.source === "spread" ? " spread" : ""} ${n}-day z-score ${op} ${t}`;
    case "percentile": return `${s}${c.source === "spread" ? " spread" : ""} ${n}-day percentile ${op} ${t}`;
    case "change": return `${s} change over ${n} trading days ${op} ${t}`;
    case "pct_change": return `${s} % change over ${n} trading days ${op} ${t}`;
    case "vs_sma": return `${s} % vs its ${n}-day avg ${op} ${t}`;
    case "sma_cross":
      return zero ? `${s} ${n}-day avg ${op === ">" ? "above" : "below"} ${c.slow_days}-day avg` : `${s} ${n}-day avg vs ${c.slow_days}-day avg (%) ${op} ${t}`;
    case "rsi": return `${s} RSI(${n}) ${op} ${t}`;
    case "macd": return `${s} MACD (12/26/9) ${op} ${t}`;
    case "vs_high": return zero && op === ">" ? `${s} new ${n}-day high` : `${s} % vs prior ${n}-day high ${op} ${t}`;
    case "vs_low": return zero && op === "<" ? `${s} new ${n}-day low` : `${s} % vs prior ${n}-day low ${op} ${t}`;
    case "volatility": return `${s} ${n}-day volatility (%/yr) ${op} ${t}`;
    case "vs_vwap": return `${s} % vs ${n}-day VWAP ${op} ${t}`;
    case "net_upgrades": return `${s} analyst upgrades minus downgrades over ${n} trading days ${op} ${t}`;
    case "target_upside": return `${s} analyst target upside (%, last ${n} trading days) ${op} ${t}`;
  }
}

/** A spec's rules, reading a legacy `when` the way the server does. */
export function specRules(spec: IdeaSpec): Rules | null {
  if (spec.rules) return spec.rules;
  return spec.when ? { enter: { mode: "all", conditions: [spec.when] }, exit: null } : null;
}

function groupText(g: Group): string {
  const parts = g.conditions.map(conditionText).join(", ");
  return g.conditions.length > 1 ? `${g.mode} of ${parts}` : parts;
}

export function rulesText(spec: IdeaSpec): string {
  const r = specRules(spec);
  if (!r) return "always";
  return r.exit ? `buy when ${groupText(r.enter)}; sell when ${groupText(r.exit)}` : `while ${groupText(r.enter)}`;
}

/** A live idea's paper record (spec §4.6): the shadow track summed up, and the 3-month claim check. */
export interface ShadowSummary {
  days: number;
  since: string | null;
  as_of: string | null;
  state: "waiting" | "live" | "stale" | "killed";
  return_pct: number | null;
  bench_return_pct: number | null;
  claim: { holds: boolean | null; label: string; days: number } | null;
  failing: boolean;
  curve?: { t: string; idea: number; bench: number }[];
  exits?: { day: string; why: string }[];
}

export type IdeaKind = "event" | "long_short" | "wrapped" | "long_only";

export const KIND_LABEL: Record<IdeaKind, string> = {
  event: "Event studies",
  long_short: "Long–short rules",
  wrapped: "Wrapped portfolios",
  long_only: "Long-only rules",
};

export interface PublicIdea {
  id: number;
  title: string;
  published_at: string;
  claim: Claim | null;
  /** The newest saved run's claim outcome in words ("+25.8 pts/yr vs SPY"). */
  result_line?: string | null;
  /** The unseen claim metric as a number, and the permutation p behind the verdict — the list's sort keys. */
  result_value?: number | null;
  result_p?: number | null;
  kind: IdeaKind;
  latest_verdict: Verdict | null;
  /** Standing under the hub-wide standard (Kevin, 2026-11-03): the stored
   * verdict re-judged against every test the hub has run (FDR bar) plus
   * walk-forward. verdict_now is what counts; latest_verdict is history. */
  verdict_now?: Verdict | null;
  fdr_pass?: boolean | null;
  wf_ok?: boolean | null;
  p_ok?: boolean | null;
  /** Ideas betting on the same names are one bet, however wrapped. */
  family?: { key: number; size: number; tickers: string[]; members: number[] } | null;
  /** The sector most of the idea's own names are in (backend map); Kevin's own tags (2026-11-05). */
  sector?: string;
  tags?: string[];
  origin?: "manual" | "lab" | "screen" | null;
  hindsight_selected?: boolean;
  gate_overridden?: boolean;
  registry?: { test_number: number | null; tests_total: number | null };
  variations: number;
  status: "backtest" | "tracking" | "live" | "killed";
  live_at: string | null;
  tracked_at: string | null;
  killed_at: string | null;
  /** The books this idea is live on right now (subset of ["main", "big"]). */
  live_books?: string[];
  live: ShadowSummary | null;
  /** The weekly critic's latest payload per book (loop piece 1): live vs
   * backtest in the claim's own units, and a PAUSE / HOLD / WATCH call. */
  critic?: Record<string, IdeaCritique>;
}

export interface IdeaCritique {
  recommendation: "PAUSE" | "WATCH" | "HOLD";
  degradation: number | null;
  at: string;
  live: { days: number; value: number | null; label: string };
  claim: { kind: string | null; backtest_label: string | null };
  conditions: { dominant: string | null; losing_entries: number; entries: number };
  flags: string[];
  reasons: string[];
  paper: { orders: number; sent: number; filled: number; fill_rate: number | null; net_filled_usd: number } | null;
}

/** The run's full stored evidence, carried on the record since 2026-11-02 -- the same
 * blocks the Workshop verdict card renders (curve, claim, shuffle, walk-forward). */
export interface PublicRunDetail {
  curve: { t: string; idea: number; benchmark: number }[];
  reason: string | null;
  variations: number | null;
  claim: RunResult["claim"];
  shuffle: RunResult["shuffle"];
  t_test: RunResult["t_test"];
  periods: RunResult["periods"];
  walk_forward: RunResult["walk_forward"];
  context: RunResult["context"];
  data_start: string | null;
  data_end: string | null;
  split_date: string | null;
  n_events?: number | null;
  per_ticker?: RunResult["per_ticker"];
  notes?: string[] | null;
  /** The search stamp from the run (A3); absent on older runs. */
  batch?: RunResult["batch"];
}

export interface PublicIdeaDetail extends Omit<PublicIdea, "live"> {
  plain_words: string;
  shadow: ShadowSummary | null;
  runs: { variation: number; verdict: Verdict; created_at: string; headline: string | null; p: number | null; bar: number | null; claim: Claim; detail: PublicRunDetail }[];
  trades: { symbol: string; qty: number; entry_price: number; exit_price: number; pnl: number; return_pct: number; exited_at: string; held_days: number; idea: string }[];
}

export const STATUS_LABEL: Record<PublicIdea["status"], string> = {
  backtest: "Backtest only",
  tracking: "Tracking — forward record running",
  live: "Live on paper",
  killed: "Killed",
};

export interface WorkshopDashboard {
  ideas: { total: number; live: number; live_big: number; tracking: number; published: number; draft: number; killed: number };
  runs: { total: number; saved: number; latest_verdicts: Record<string, number>;
          latest_verdicts_as_run?: Record<string, number>;
          recent: { idea_id: number; title: string | null; verdict: string; at: string | null }[] };
  fills: { state: string; total: number; attributed: number; needs_label: number;
           closed_pnl_by_idea: { idea: string; pnl: number; trades: number }[] };
  screens: { total: number; promoted: number };
  manual_actions_open: number;
}

export interface ScreenMembershipEvent {
  ticker: string;
  /** Every share-class ticker of the issuer when the event spans classes
   * (Round 2 issuer-keyed diffing); absent for single-ticker events. */
  tickers?: string[];
  kind: "entered" | "exited";
  date: string;
  since?: string;
}

export interface ScreenRow {
  id: number;
  name: string;
  spec: Record<string, unknown>;
  last_run: { run_at: string | null; survivors: number | null;
              survivor_issuers?: number | null;
              universe_selection?: string;
              data_as_of?: string | null; sources?: string[];
              column_sources?: Record<string, string>;
              near_misses?: NearMiss[]; near_miss_count?: number } | null;
  membership?: { tracked_since: string; as_of: string;
                 members: Record<string, string> } | null;
  membership_events?: ScreenMembershipEvent[] | null;
  promoted_idea_id: number | null;
}
