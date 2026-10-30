/** The Workshop (Trading HQ step 2): payload types, the signed-in fetch, and the plain words for each claim. */
import { sessionToken } from "@/components/RequireAdmin";
import { buildApiUrl } from "@/lib/api";

export type Claim = "beats_benchmark" | "beats_benchmark_when" | "ballast" | "smoother_ride";
export type Verdict = "PASS" | "FAIL" | "NOT ENOUGH DATA";

export interface Condition {
  source: "fred" | "price";
  series: string;
  measure: "level" | "change" | "pct_change";
  lookback_days: number;
  op: ">" | "<";
  threshold: number;
}

export interface IdeaSpec {
  title: string;
  hold: string[];
  when: Condition | null;
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
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? "That draft has a field the test can't use." : `Request failed (${response.status})`;
    throw new ApiError(message, response.status, body);
  }
  return body as T;
}

const CLAIMS: Record<Claim, string> = {
  beats_benchmark: "Beats the benchmark after costs",
  beats_benchmark_when: "Beats the benchmark while the condition holds",
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
  const what = c.measure === "level" ? c.series : `${c.series} ${c.measure === "change" ? "change" : "% change"} over ${c.lookback_days} trading days`;
  return `${what} ${c.op} ${c.threshold}`;
}

/** A live idea's paper record (spec §4.6): the shadow track summed up, and the 3-month claim check. */
export interface ShadowSummary {
  days: number;
  since: string | null;
  as_of: string | null;
  state: "waiting" | "live" | "stale" | "killed";
  return_pct: number | null;
  bench_return_pct: number | null;
  claim: { holds: boolean; label: string; days: number } | null;
  failing: boolean;
  curve?: { t: string; idea: number; bench: number }[];
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
