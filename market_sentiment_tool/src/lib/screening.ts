/** Screening: card-driven building over the engine catalog.
 *
 * The artifact prototype's design: a screen is built by picking filter
 * CARDS (plain label, one-line blurb, a preset number in the usual
 * direction) and nudging values -- never by typing JSON. The page composes
 * the spec from the cards; the spec is shown read-only, for the record.
 * API shapes match the shipped endpoints (run/save bodies wrap the spec).
 */

export interface CatalogFn {
  name: string;
  category: string;
  kind: string;
  params: Record<string, unknown>;
  returns: string;
  doc: string;
  source: string;
}

export interface CardFn {
  id: string;
  fn: string;
  params: Record<string, number>;
  label: string;
  group: string;
  blurb: string;
  unit: string;
  divisor: number;
  source: string;
  ops: string[];
  preset: { op: string; value: number };
}

export interface Catalog {
  functions: CatalogFn[];
  universe_builders: string[];
  ops: { op: string; doc?: string }[];
  cards: CardFn[];
  computed_at?: string;
  universe_refresh?: Record<string, { as_of: string; source: string; count: number } | null>;
}

export interface NearMiss {
  ticker: string;
  fn: string;
  column: string;
  value: number;
  op: string;
  threshold: unknown;
}

export interface RunFooter {
  spec_name?: string;
  run_at?: string;
  data_as_of?: string | null;
  universe_size?: number;
  universe_capped?: { cap: number; universe_size_full: number };
  universe_selection?: string;
  universe_union?: boolean;
  survivors?: number;
  survivor_issuers?: number;
  near_misses?: NearMiss[];
  near_miss_count?: number;
  columns?: Record<string, { fn?: string; source?: string; as_of?: string }>;
  context?: Record<string, unknown>;
  missing?: { ticker: string; field: string; reason?: string }[];
  spec_echo?: Record<string, unknown>;
}

export interface QuotePayload {
  ticker: string;
  price: number;
  prev_close: number;
  change_pct: number | null;
  volume: number | null;
  as_of: string;
  closes: { date: string; close: number }[];
}

export interface RunPayload {
  columns: string[];
  rows: Record<string, unknown>[];
  footer: RunFooter;
}

export type ScreenSpec = Record<string, unknown> & {
  name?: string;
  universe?: { type: string; index?: string; tickers?: string[];
               indexes?: string[]; base?: unknown };
  filters?: SpecFilter[];
  derived?: { name: string; expr: string }[];
  score?: SpecScore[];
  sort?: { by: string; ascending?: boolean };
  limit?: number;
  max_universe?: number;
  membership_diff?: boolean;
};

export interface SpecFilter {
  fn: string;
  params?: Record<string, number>;
  op: string;
  value: number;
}

export interface SpecScore {
  fn: string;
  params?: Record<string, number>;
  weight: number;
  direction: string;
}

export interface TrayItem {
  key: string;
  fn: string;
  params?: Record<string, number>;
  label: string;
  unit: string;
  divisor: number;
  source: string;
  custom: boolean;
  op: string;
  value: number;
}

export interface ScoreTerm {
  fn: string;
  params?: Record<string, number>;
  label: string;
  weight: number;
  direction: "high" | "low";
}

export const OP_LABELS: Record<string, string> = {
  ge: "at least",
  gt: "above",
  le: "at most",
  lt: "below",
  pct_ge: "top slice (≥ percentile)",
  pct_gte: "top slice (≥ percentile)",
  pct_le: "bottom slice (≤ percentile)",
  pct_lte: "bottom slice (≤ percentile)",
};

export function cardKey(fn: string, params?: Record<string, number>): string {
  return `${fn}:${JSON.stringify(params ?? {})}`;
}

export function trayFromSpec(
  spec: ScreenSpec,
  cards: CardFn[],
): { tray: TrayItem[]; score: ScoreTerm[]; derived: { name: string; expr: string }[] } {
  const byKey = new Map(cards.map((c) => [cardKey(c.fn, c.params), c]));
  const tray: TrayItem[] = (spec.filters ?? []).map((f) => {
    const card = byKey.get(cardKey(f.fn, f.params));
    if (card)
      return { key: card.id, fn: card.fn, params: card.params, label: card.label,
               unit: card.unit, divisor: card.divisor, source: card.source,
               custom: false, op: f.op, value: f.value };
    return { key: `custom:${cardKey(f.fn, f.params)}`, fn: f.fn, params: f.params,
             label: f.fn, unit: "", divisor: 1, source: "from a saved spec",
             custom: true, op: f.op, value: f.value };
  });
  const score: ScoreTerm[] = (spec.score ?? []).map((s) => {
    const card = byKey.get(cardKey(s.fn, s.params));
    return { fn: s.fn, params: s.params, label: card?.label ?? s.fn,
             weight: s.weight, direction: (s.direction === "low" ? "low" : "high") };
  });
  return { tray, score, derived: spec.derived ?? [] };
}

export function specFromState(args: {
  name: string;
  universeId: string;
  customTickers: string;
  tray: TrayItem[];
  derived: { name: string; expr: string }[];
  score: ScoreTerm[];
  limit: number;
}): ScreenSpec {
  const universe =
    args.universeId === "custom"
      ? { type: "list", tickers: args.customTickers.split(/[\s,]+/).map((t) => t.trim().toUpperCase()).filter(Boolean) }
      : { type: "index", index: args.universeId };
  const spec: ScreenSpec = {
    name: args.name.trim() || "untitled_screen",
    universe,
    filters: args.tray.map((t) => ({
      fn: t.fn,
      ...(t.params && Object.keys(t.params).length ? { params: t.params } : {}),
      op: t.op,
      value: t.value,
    })),
    limit: args.limit,
  };
  if (args.derived.length) spec.derived = args.derived;
  if (args.score.length) {
    spec.score = args.score.map((s) => ({
      fn: s.fn,
      ...(s.params && Object.keys(s.params).length ? { params: s.params } : {}),
      weight: s.weight,
      direction: s.direction,
    }));
    spec.sort = { by: "score", ascending: false };
  }
  return spec;
}

export interface Preset {
  id: string;
  name: string;
  blurb: string;
  items: { card: string; op: string; value: number }[];
  scoreCard?: string;
  scoreDirection?: "high" | "low";
}

export const PRESETS: Preset[] = [
  { id: "earnings-momentum", name: "Earnings momentum",
    blurb: "Strong 6-month momentum, a beat at the last print, and a market that liked it.",
    items: [{ card: "mom6", op: "pct_gte", value: 75 }, { card: "surprise", op: "gt", value: 0 },
            { card: "reaction", op: "gt", value: 0 }] },
  { id: "momentum-quality", name: "Momentum + quality",
    blurb: "Top-quartile 6-month momentum with a real operating margin -- the W18-style selection layer.",
    items: [{ card: "mom6", op: "pct_gte", value: 75 }, { card: "op_m", op: "gt", value: 10 }],
    scoreCard: "mom6" },
  { id: "clean-value", name: "Clean value",
    blurb: "The Finviz value screen in native functions: low P/E, real cash yield, debt under control.",
    items: [{ card: "pe", op: "lt", value: 15 }, { card: "fcf_yield", op: "ge", value: 4 },
            { card: "dte", op: "le", value: 150 }] },
  { id: "fcc-lens", name: "Cash-covered capex (FCC lens)",
    blurb: "Big spenders ranked by how many times operating cash flow covers the capex bill. Watch the bottom, not the top.",
    items: [{ card: "capex_int", op: "ge", value: 3 }, { card: "mcap", op: "ge", value: 5_000_000_000 }],
    scoreCard: "fcc", scoreDirection: "low" },
  { id: "near-high", name: "Near-high momentum",
    blurb: "Within 5% of the high with a strong quarter -- trend continuation, the opposite of a washout.",
    items: [{ card: "ddhigh", op: "ge", value: -5 }, { card: "ret3m", op: "gt", value: 10 },
            { card: "vol63", op: "le", value: 60 }] },
  { id: "oversold-quality", name: "Oversold quality",
    blurb: "RSI-washed-out names that still run a real operating margin -- self-funding businesses only.",
    items: [{ card: "rsi", op: "le", value: 35 }, { card: "op_m", op: "gt", value: 10 }] },
];

export const UNIVERSES = [
  { id: "sp500", label: "S&P 500", note: "index list, refreshed daily" },
  { id: "nasdaq100", label: "Nasdaq-100", note: "index list, refreshed daily" },
  { id: "nasdaq_all", label: "All US listed", note: "enrichment capped, disclosed on the run" },
  { id: "custom", label: "My tickers", note: "paste a list" },
];
