/** The Workshop (Trading HQ step 2): payload types, the signed-in fetch, and the plain words for each claim. */
import { sessionToken } from "@/components/RequireAdmin";
import { buildApiUrl } from "@/lib/api";

export type Claim = "beats_benchmark" | "beats_benchmark_when" | "ballast" | "smoother_ride";
export type Verdict = "PASS" | "FAIL" | "NOT ENOUGH DATA";

export type Measure =
  | "level" | "change" | "pct_change" | "vs_sma" | "sma_cross" | "rsi" | "macd" | "vs_high" | "vs_low" | "volatility" | "vs_vwap"
  | "net_upgrades" | "target_upside" | "zscore" | "percentile";

export interface Condition {
  source: "fred" | "price" | "analyst" | "spread";
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
const FP: Src[] = ["fred", "price", "spread"];
const ANY: Src[] = ["fred", "price", "spread"];
export const MEASURES: { value: Measure; label: string; hint: string; sources: Src[] }[] = [
  { value: "level", label: "level", hint: "the value itself", sources: FP },
  { value: "change", label: "change", hint: "change over N days, in the series' own units", sources: FP },
  { value: "pct_change", label: "% change", hint: "% change over N days", sources: ["fred", "price"] },
  { value: "vs_sma", label: "vs its average", hint: "% above its N-day average", sources: FP },
  { value: "volatility", label: "volatility", hint: "N-day volatility, % a year", sources: FP },
  { value: "sma_cross", label: "average cross", hint: "% the N-day average is above the slow average", sources: P },
  { value: "rsi", label: "RSI", hint: "N-day RSI, 0-100 (below 30 = oversold)", sources: P },
  { value: "macd", label: "MACD", hint: "MACD 12/26/9 minus its signal, % of price (above 0 = bullish)", sources: P },
  { value: "vs_high", label: "vs N-day high", hint: "% above the prior N-day high (above 0 = breakout)", sources: P },
  { value: "vs_low", label: "vs N-day low", hint: "% above the prior N-day low (below 0 = breakdown)", sources: P },
  { value: "vs_vwap", label: "vs VWAP", hint: "% above its N-day VWAP", sources: P },
  { value: "zscore", label: "z-score", hint: "standard deviations from its N-day average (2 = stretched)", sources: ANY },
  { value: "percentile", label: "percentile", hint: "today's rank among the last N days, 0-100 (95 = near the top)", sources: ANY },
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

export interface IdeaSpec {
  title: string;
  hold: string[];
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
  walk_forward?: {
    folds: { start: string; end: string; days: number; holds: boolean | null; value: number | null; label: string; idea_cagr: number | null; bench_cagr: number | null }[];
    held: number; of: number;
  } | null;
  notes?: string[];
  variations: number;
  context: { name: string; built_cagr: number | null; unseen_cagr: number | null; unseen_max_dd: number | null }[];
  curve: { t: string; idea: number; benchmark: number }[];
  n_events?: number;
  per_ticker?: { ticker: string; n: number; mean: number; shrunk: number; weight: number; t: number }[];
  events?: EventRow[];
}

export interface Run {
  id: number;
  variation: number;
  spec: IdeaSpec;
  draft_model: string | null;
  verdict: Verdict;
  result: RunResult;
  created_at: string;
}

export interface Idea {
  id: number;
  title: string;
  plain_words: string;
  created_at: string;
  published_at?: string | null;
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

export interface IdeaDetail {
  idea: Idea;
  runs: Run[];
  tag?: string;
  shadow?: ShadowSummary | null;
  orders_enabled?: boolean;
  orders?: PaperOrder[];
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

export interface PublicIdea {
  id: number;
  title: string;
  published_at: string;
  claim: Claim | null;
  latest_verdict: Verdict | null;
  variations: number;
  status: "backtest" | "live" | "killed";
  live_at: string | null;
  killed_at: string | null;
  live: ShadowSummary | null;
}

export interface PublicIdeaDetail extends Omit<PublicIdea, "live"> {
  plain_words: string;
  shadow: ShadowSummary | null;
  runs: { variation: number; verdict: Verdict; created_at: string; headline: string | null; p: number | null; bar: number | null; claim: Claim }[];
  trades: { symbol: string; qty: number; entry_price: number; exit_price: number; pnl: number; return_pct: number; exited_at: string; held_days: number; idea: string }[];
}

export const STATUS_LABEL: Record<PublicIdea["status"], string> = {
  backtest: "Backtest only",
  live: "Live on paper",
  killed: "Killed",
};
