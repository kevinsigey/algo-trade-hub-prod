/**
 * Valuation bands (Phase 0 fact sheets): types + the pure reads the Valuation
 * tab renders. The API returns the stored sheet rows verbatim; PostgREST
 * numerics arrive as strings, so every figure goes through `num` first.
 *
 * The bands are deterministic: a company's own recorded full-year guidance,
 * valued at its frozen peer group's median multiple. Zones say where the
 * price sits against that construction -- a research display, not a trade
 * recommendation (the page says so, once, at the top).
 */

export interface GuideAnchor {
  metric: string;
  period: string | null;
  period_key: string | null;
  low: number;
  high: number;
  mid: number;
  point_guide: boolean;
  consensus: number | null;
  consensus_source?: string | null;
  consensus_period?: string | null;
  recorded_at: string | null;
  accession: string | null;
}

export interface DirectionEntry {
  period: string | null;
  mid: number | null;
  prev_mid?: number | null;
  direction: string;
  recorded_at: string | null;
}

export interface GuidanceRecord {
  ticker?: string;
  metric: string;
  period: string | null;
  unit?: string | null;
  low: number | null;
  high: number | null;
  consensus: number | null;
  consensus_period?: string | null;
  consensus_source?: string | null;
  accession: string | null;
  created_at: string | null;
}

/** The snapshot stamp on GET /api/valuation-bands (reliability pass F1):
 * every figure on the page belongs to this one completed compute. Null
 * only for pre-fix legacy data -- the page labels that state honestly. */
export interface SnapshotStamp {
  id: number;
  computed_at: string | null;
  completed_at: string | null;
  sheet_count: number | null;
  banded_count: number | null;
  source: string | null;
}

export interface FactSheet {
  ticker: string;
  tier: string;
  status: string; // banded | no_full_year_guide | guide_rejected | no_peer_multiple
  band_basis: string; // eps | revenue
  price: number | string | null;
  price_as_of: string | null;
  price_vendor?: string | null;
  snapshot_id?: number | null;
  guard_rejections?: string[] | null;
  stale_reasons?: string[] | null;
  ingest_notes?: string[] | null;
  peer_group: string | null;
  peer_multiple: number | string | null;
  peer_count: number | null;
  peer_basis: string | null;
  anchor: GuideAnchor | null;
  bands: { bear: number; base: number; bull: number } | null;
  implied_eps: number | string | null;
  implied_revenue: number | string | null;
  gap_range_widths: number | string | null;
  guidance_percentile: number | string | null;
  baseline_verdict: string | null;
  stale: boolean;
  falsifier: string | null;
  directions: Record<string, DirectionEntry> | null;
  fundamentals: Record<string, { value: number; as_of: string } | string[]> | null;
  inputs: { guidance_records?: GuidanceRecord[] } | null;
  computed_at: string;
  peer_members?: string[]; // detail endpoint only (read-side derivation)
}

/** ── The re-presentation summary block (additive on /api/valuation-bands):
 * one stamped block computed server-side from persisted band history of
 * completed snapshots only — counts for the verdict strip, the attention
 * feed (genuine diffs only), and the held map for board markers. */
export interface SummaryBands { bear: number | string | null; base: number | string | null; bull: number | string | null }

export interface FeedItem {
  kind: "conjunction" | "crossing" | "zone_change" | "guide_revision" | "new_banded" | string;
  ticker: string;
  zone?: string | null;
  from_zone?: string | null;
  to_zone?: string | null;
  classification?: string | null;
  as_of?: string | null;
  screens?: string[];
  book?: string | null;
  action?: string | null;
  created_at?: string | null;
  metric?: string | null;
  direction?: string | null;
  from_low?: number | null;
  from_high?: number | null;
  to_low?: number | null;
  to_high?: number | null;
  bands?: SummaryBands | null;
  price?: number | string | null;
}

export interface PageSummary {
  snapshot_id: number | null;
  previous_snapshot_id: number | null;
  counts: {
    banded: number;
    buy_zones: number;
    strong_short_zones: number;
    crossings_since_last_snapshot: number;
    pending_debates: number;
    classified_prints: number;
  };
  feed_state: "ok" | "no_previous_snapshot" | "no_snapshot" | string;
  feed: FeedItem[];
  classified_names: { ticker: string; classification: string; as_of: string | null }[];
  crossings: { ticker: string; book: string | null; zone: string | null; action: string | null; created_at: string | null }[];
  held: Record<string, { books: string[]; qty: number; sleeves: (string | null)[] }>;
  held_positions_unavailable: boolean;
}

/** The zone board's columns, in display order. Every banded name lands
 * in exactly one column: the five zone columns the build names, plus a
 * held/other column that exists so a stale or unpriced banded name is
 * never dropped from the board to make the columns tidy. */
export const BOARD_COLUMNS: { key: string; label: string; zones: string[] }[] = [
  { key: "strong_buy", label: "Strong buy", zones: ["buy_zone_strong"] },
  { key: "buy", label: "Buy", zones: ["buy_zone"] },
  { key: "neutral", label: "Neutral", zones: ["neutral", "no_chase_long"] },
  { key: "short", label: "Short", zones: ["short_zone"] },
  { key: "strong_short", label: "Strong short", zones: ["short_zone_strong"] },
  { key: "held_other", label: "Zone held / other", zones: ["stale", "no_price"] },
];

export function boardGroups(sheets: FactSheet[]): { key: string; label: string; sheets: FactSheet[] }[] {
  const banded = sheets.filter((s) => s.status === "banded");
  const groups = BOARD_COLUMNS.map((c) => ({ key: c.key, label: c.label, sheets: [] as FactSheet[] }));
  const byZone = new Map<string, number>();
  BOARD_COLUMNS.forEach((c, i) => c.zones.forEach((z) => byZone.set(z, i)));
  const fallback = groups.length - 1;
  for (const s of [...banded].sort((a, b) => a.ticker.localeCompare(b.ticker))) {
    groups[byZone.get(s.baseline_verdict ?? "") ?? fallback].sheets.push(s);
  }
  return groups;
}

/** The consensus period arrives as a yfinance relative tag ("0y", "+1y"):
 * cryptic on the page, so render the human form. The tag DOES carry
 * meaning -- which forecast year the consensus belongs to -- so it is
 * translated, not dropped; an unknown tag passes through as recorded. */
const CONSENSUS_PERIODS: Record<string, string> = {
  "0y": "current year",
  "+1y": "next year",
  "0q": "current quarter",
  "+1q": "next quarter",
};

export function consensusPeriodText(period: string | null | undefined): string | null {
  if (!period) return null;
  return CONSENSUS_PERIODS[period] ?? period;
}

/** PostgREST numerics arrive as strings; anything unparseable is missing. */
export function num(v: number | string | null | undefined): number | null {  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export type ZoneTone = "buy" | "short" | "flat" | "muted";

export interface ZoneInfo { label: string; tone: ZoneTone; blurb: string }

const ZONES: Record<string, ZoneInfo> = {
  buy_zone_strong: { label: "Strong buy zone", tone: "buy",
    blurb: "Price is below the bear band — the market prices in less than the low end of guidance, with the 10% haircut." },
  buy_zone: { label: "Buy zone", tone: "buy",
    blurb: "Price is at or below the base band — the market prices in less than the midpoint of guidance." },
  neutral: { label: "Neutral", tone: "flat",
    blurb: "Price is inside the bull band and the implied figure sits inside the guide range." },
  short_zone: { label: "Short zone", tone: "short",
    blurb: "Price is above the base band — the market prices in more than the guide midpoint supports." },
  short_zone_strong: { label: "Strong short zone", tone: "short",
    blurb: "Price is above the bull band and the implied figure is above the guide midpoint." },
  no_chase_long: { label: "No-chase", tone: "flat",
    blurb: "Price is above the bull band, but the implied figure still trails the guide midpoint — rich price, cheap guide; no signal either way." },
  stale: { label: "Stale — zone held", tone: "muted",
    blurb: "The price or the guide is too old to grade; the sheet stands, the zone is not shown." },
  no_price: { label: "No price", tone: "muted",
    blurb: "No current price was available when this sheet was computed." },
  no_bands: { label: "No bands", tone: "muted",
    blurb: "No usable full-year guide, so no bands were computed." },
};

export function zoneInfo(verdict: string | null | undefined): ZoneInfo {
  if (!verdict) return { label: "—", tone: "muted", blurb: "" };
  return ZONES[verdict] ?? { label: verdict, tone: "muted", blurb: "" };
}

export interface Summary {
  total: number;
  banded: number;
  epsBanded: number;
  revenueBanded: number;
  buyZones: number;
  shortZones: number;
  flatZones: number;
  stale: number;
  unbanded: number;
  guideRejected: number;
  noFullYearGuide: number;
  noPeerMultiple: number;
}

export function summarize(sheets: FactSheet[]): Summary {
  const s: Summary = { total: sheets.length, banded: 0, epsBanded: 0,
    revenueBanded: 0, buyZones: 0, shortZones: 0, flatZones: 0, stale: 0,
    unbanded: 0, guideRejected: 0, noFullYearGuide: 0, noPeerMultiple: 0 };
  for (const sh of sheets) {
    if (sh.status === "banded") {
      s.banded += 1;
      if (sh.band_basis === "revenue") s.revenueBanded += 1; else s.epsBanded += 1;
      if (sh.stale || sh.baseline_verdict === "stale") { s.stale += 1; continue; }
      const tone = zoneInfo(sh.baseline_verdict).tone;
      if (tone === "buy") s.buyZones += 1;
      else if (tone === "short") s.shortZones += 1;
      else if (tone === "flat") s.flatZones += 1;
    } else {
      s.unbanded += 1;
      if (sh.status === "guide_rejected") s.guideRejected += 1;
      else if (sh.status === "no_full_year_guide") s.noFullYearGuide += 1;
      else if (sh.status === "no_peer_multiple") s.noPeerMultiple += 1;
    }
  }
  return s;
}

export function metricLabel(metric: string): string {
  if (metric === "eps_gaap") return "EPS (GAAP)";
  if (metric === "eps_adjusted") return "EPS (adjusted)";
  return metric;
}

/** Guide figures: dollars for revenue (in B), plain for EPS. */
function guideFigure(metric: string, v: number): string {
  if (metric === "revenue") return `$${(v / 1e9).toFixed(2)}B`;
  return v.toFixed(2);
}

export function guideText(sheet: FactSheet): string {
  const a = sheet.anchor;
  if (!a) return "—";
  const period = a.period_key ?? a.period ?? "";
  const what = a.metric === "revenue" ? "revenue" : "EPS";
  const lo = guideFigure(a.metric, a.low);
  if (a.point_guide || a.high === a.low) {
    return `${period} ${what} ${lo} (point guide)`;
  }
  if (a.metric === "revenue") {
    return `${period} ${what} $${(a.low / 1e9).toFixed(2)}–${(a.high / 1e9).toFixed(2)}B`;
  }
  return `${period} ${what} ${lo}–${guideFigure(a.metric, a.high)}`;
}

export function guideDirection(sheet: FactSheet): string | null {
  if (!sheet.anchor || !sheet.directions) return null;
  return sheet.directions[sheet.anchor.metric]?.direction ?? null;
}

export function humanizeGroup(group: string | null): string {
  if (!group) return "—";
  if (group.startsWith("sector:")) return `${group.slice(7)} (whole sector)`;
  return group.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

/** The gap: how many guide-range widths the implied figure sits from the guide mid. */
export function gapText(gap: number | string | null): string {
  const g = num(gap);
  if (g == null) return "—";
  const sign = g > 0 ? "+" : g < 0 ? "−" : "";
  return `${sign}${Math.abs(g).toFixed(1)} guide widths`;
}

/**
 * The gap as the table shows it (reliability pass F6): when the guide is
 * a point or its width is under 1% of its midpoint, "range widths" is a
 * division by almost-nothing and prints artifact numbers (PLTR +5262.9,
 * ADBE −296.1) — render the honest "n/a (narrow guide)" instead.
 */
export function gapDisplay(sheet: FactSheet): string {
  const a = sheet.anchor;
  if (a) {
    const lo = num(a.low), hi = num(a.high), mid = num(a.mid);
    if (a.point_guide || (lo != null && hi != null && mid != null
        && mid !== 0 && (hi - lo) < 0.01 * Math.abs(mid))) {
      return "n/a (narrow guide)";
    }
  }
  return gapText(sheet.gap_range_widths);
}

export function priceText(v: number | string | null): string {
  const n = num(v);
  if (n == null) return "—";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function multipleText(sheet: FactSheet): string {
  const m = num(sheet.peer_multiple);
  if (m == null) return "—";
  const kind = sheet.band_basis === "revenue" ? "P/S" : "fwd P/E";
  return `${m.toFixed(2)}× ${kind}`;
}
