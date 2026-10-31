/** The Workshop (Trading HQ step 2): payload types, the signed-in fetch, and the plain words for each claim. */
import { sessionToken } from "@/components/RequireAdmin";
import { buildApiUrl } from "@/lib/api";

export type Claim = "beats_benchmark" | "beats_benchmark_when" | "ballast" | "smoother_ride";
export type Verdict = "PASS" | "FAIL" | "NOT ENOUGH DATA";

export type Measure =
  | "level" | "change" | "pct_change" | "vs_sma" | "sma_cross" | "rsi" | "macd" | "vs_high" | "vs_low" | "volatility" | "vs_vwap";

export interface Condition {
  source: "fred" | "price";
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
export const MEASURES: { value: Measure; label: string; hint: string; fred: boolean }[] = [
  { value: "level", label: "level", hint: "the value itself", fred: true },
  { value: "change", label: "change", hint: "change over N days, in the series' own units", fred: true },
  { value: "pct_change", label: "% change", hint: "% change over N days", fred: true },
  { value: "vs_sma", label: "vs its average", hint: "% above its N-day average", fred: true },
  { value: "volatility", label: "volatility", hint: "N-day volatility, % a year", fred: true },
  { value: "sma_cross", label: "average cross", hint: "% the N-day average is above the slow average", fred: false },
  { value: "rsi", label: "RSI", hint: "N-day RSI, 0-100 (below 30 = oversold)", fred: false },
  { value: "macd", label: "MACD", hint: "MACD 12/26/9 minus its signal, % of price (above 0 = bullish)", fred: false },
  { value: "vs_high", label: "vs N-day high", hint: "% above the prior N-day high (above 0 = breakout)", fred: false },
  { value: "vs_low", label: "vs N-day low", hint: "% above the prior N-day low (below 0 = breakdown)", fred: false },
  { value: "vs_vwap", label: "vs VWAP", hint: "% above its N-day VWAP", fred: false },
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
  rules: Rules | null;
  /** Steps 2-5 runs stored one condition; the server reads it as a one-condition buy rule. */
  when?: Condition | null;
  otherwise: string;
  claim: Claim;
  benchmark: string;
  cost_bps: number;
  start: string;
  unseen_fraction: number;
  assumptions: string[];
}

export interface RunResult {
  verdict: Verdict;
  headline: string;
  reason: string | null;
  split_date: string | null;
  data_start: string | null;
  data_end: string | null;
  claim: { built: { holds: boolean; value: number | null; label: string }; unseen: { holds: boolean; value: number | null; label: string } } | null;
  shuffle: { beats_pct: number; p: number; bar: number; permutations: number; seed: number; method: string } | null;
  t_test: { mean_daily_diff: number; t: number; p: number } | null;
  periods: { held: number; of: number } | null;
  variations: number;
  context: { name: string; built_cagr: number | null; unseen_cagr: number | null; unseen_max_dd: number | null }[];
  curve: { t: string; idea: number; benchmark: number }[];
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
    case "level": return `${s} ${op} ${t}`;
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
