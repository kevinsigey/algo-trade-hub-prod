import { Fragment, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronDown, Loader2 } from "lucide-react";

import { FullView } from "@/components/Panel";
import { DashCard, PEEK, PeekRows } from "@/pages/portfolio/shared";

import { adminJson } from "@/lib/workshop";
import { ctDateTimeYear, ctDateYear, ordinal } from "@/lib/format";
import BandCrossings from "@/pages/BandCrossings";
import { DebatesSection } from "@/pages/Debates";
import LevelWatcher from "@/pages/LevelWatcher";
import DebateQueue from "@/components/DebateQueue";
import NameDecision from "@/components/NameDecision";
import { VerdictChipLine } from "@/components/VerdictChip";
import type { ChipsPayload, VerdictChip } from "@/lib/decisions";
import {
  consensusPeriodText, gapDisplay, guideDirection, guideText, humanizeGroup, metricLabel, multipleText,
  num, priceText, summarize, zoneInfo,
  type FactSheet, type FeedItem, type GuidanceBoard, type GuidanceRecord, type GridRow, type PageSummary, type SnapshotStamp,
} from "@/lib/valuation";

/**
 * Valuation bands: every name the guidance recorder covers gets a fact sheet --
 * its own recorded full-year guidance valued at its frozen peer group's median
 * multiple, as bear/base/bull bands with a zone for where the price sits.
 * Display only: the zones are a research read, not trade recommendations, and
 * nothing here touches a book. Names without usable guidance are listed with
 * the reason on their sheet, never silently dropped.
 */

const ZONE_ORDER: Record<string, number> = {
  buy_zone_strong: 0, buy_zone: 1, neutral: 2, no_chase_long: 3,
  short_zone: 4, short_zone_strong: 5, stale: 6, no_price: 7, no_bands: 8,
};

const DIRECTION_LABELS: Record<string, string> = {
  raised: "Raised", cut: "Cut", held: "Held", first: "First guide",
};

const STATE_LABELS: Record<string, string> = {
  no_full_year_guide: "No full-year guide on record",
  guide_rejected: "Guide on record — rejected by the guards",
  no_peer_multiple: "Guide on record — peer group too small to price",
};

const FUND_LABELS: Record<string, string> = {
  cash: "Cash", debt_current: "Debt (current)", debt_long_term: "Debt (long-term)",
  eps_diluted: "Diluted EPS", revenue: "Revenue (latest FY)",
  shares_diluted: "Diluted shares",
};

/** Unit labels on every value (F5 discipline; Round 4): the EDGAR concepts
 * behind this line are EarningsPerShareDiluted (USD per share) and
 * WeightedAverageNumberOfDilutedSharesOutstanding (a share count) -- a
 * bare "Diluted EPS 1.02" hid both. Money fields carry their $. */
export function fmtFund(key: string, v: number): string {
  if (key === "shares_diluted") return `${(v / 1e6).toFixed(1)}M shares`;
  if (key === "eps_diluted") return `$${v.toFixed(2)} per share`;
  return v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : `$${(v / 1e6).toFixed(1)}M`;
}

function zoneBadge(verdict: string | null) {
  const z = zoneInfo(verdict);
  const cls = z.tone === "buy" ? "bg-emerald-500/15 text-emerald-300"
    : z.tone === "short" ? "bg-rose-500/15 text-rose-300"
    : z.tone === "flat" ? "bg-slate-500/20 text-slate-200"
    : "bg-slate-800 text-slate-400";
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>{z.label}</span>;
}

/** One horizontal strip: a range bar, an optional mid tick, and a price-style
 * marker. The axis row beneath carries the scale (min/max of the strip) and
 * the marker's own value, so an off-band marker reads as a measured distance,
 * not a floating dot. All other words live in the chip row, so labels can
 * never collide on the bar itself. */
function RangeStrip({ lo, hi, mid, marker, aria, fmt }: {
  lo: number; hi: number; mid?: number | null; marker: number | null;
  aria: string; fmt: (v: number) => string;
}) {
  const vals = [lo, hi, ...(mid != null ? [mid] : []), ...(marker != null ? [marker] : [])];
  const rawLo = Math.min(...vals), rawHi = Math.max(...vals);
  const span = rawHi - rawLo || 1;
  const x0 = rawLo - span * 0.05, x1 = rawHi + span * 0.05;
  const W = 680;
  const X = (v: number) => 6 + ((v - x0) / (x1 - x0)) * (W - 12);
  const markerAnchor = marker == null ? "middle"
    : X(marker) < 70 ? "start" : X(marker) > W - 70 ? "end" : "middle";
  // Collision check (Kevin's standing rule: chart labels never overlap).
  // The axis min/max labels and the marker label share the bottom row; when
  // the marker sits near an edge, its end/start-anchored label lands on the
  // axis label's ground. Estimate widths at 11px and, on a collision, drop
  // the marker label to its own row -- no overlap by construction.
  const labelW = (s: string) => s.length * 6.6;
  const spanOf = (x: number, w: number, anchor: string): [number, number] =>
    anchor === "start" ? [x, x + w] : anchor === "end" ? [x - w, x] : [x - w / 2, x + w / 2];
  const minSpan: [number, number] = [6, 6 + labelW(fmt(x0))];
  const maxSpan: [number, number] = [W - 6 - labelW(fmt(x1)), W - 6];
  const markerSpan = marker != null ? spanOf(X(marker), labelW(fmt(marker)), markerAnchor) : null;
  const collides = markerSpan != null
    && (markerSpan[0] < minSpan[1] + 4 || markerSpan[1] > maxSpan[0] - 4);
  const H = collides ? 74 : 58;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={aria}>
      <rect x={X(lo)} y={16} width={Math.max(2, X(hi) - X(lo))} height={12}
            className="fill-slate-600" rx={2} />
      {mid != null && (
        <line x1={X(mid)} y1={11} x2={X(mid)} y2={33} className="stroke-slate-100" strokeWidth={2} />
      )}
      {marker != null && (
        <>
          <line x1={X(marker)} y1={4} x2={X(marker)} y2={40} stroke="#f59e0b" strokeWidth={2} />
          <path d={`M ${X(marker) - 5} 0 L ${X(marker) + 5} 0 L ${X(marker)} 7 Z`} fill="#f59e0b" />
        </>
      )}
      <text x={6} y={54} fontSize={11} className="fill-slate-500">{fmt(x0)}</text>
      <text x={W - 6} y={54} fontSize={11} textAnchor="end" className="fill-slate-500">{fmt(x1)}</text>
      {marker != null && (
        <text x={X(marker)} y={collides ? 70 : 54} fontSize={11} textAnchor={markerAnchor}
              className="fill-amber-400">{fmt(marker)}</text>
      )}
    </svg>
  );
}

/** Move 4: the band position as a visual. A mini track — bear/base/bull
 * ticks on one axis, the price as a dot positioned by value. The scale
 * extends 10% past the bands on each side and the dot CLAMPS at the
 * ends: a price beyond the bull band sits at the track's end, it never
 * runs off it or pretends to a position it doesn't have. No text lives
 * on the track (labels cannot overlap at any width); the numbers ride
 * the chip's title and adjacent text. */
export function BandTrack({ bands, price, ticker }: {
  bands: { bear: number | string | null; base: number | string | null; bull: number | string | null } | null;
  price: number | string | null; ticker: string;
}) {
  const bear = num(bands?.bear), base = num(bands?.base), bull = num(bands?.bull);
  const p = num(price);
  if (bear == null || base == null || bull == null) return null;
  const span = bull - bear || 1;
  const lo = bear - span * 0.1, hi = bull + span * 0.1;
  const pct = (v: number) => Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100));
  return (
    <div data-testid={`band-track-${ticker}`} role="img"
         aria-label={`Band track: bear ${priceText(bear)}, base ${priceText(base)}, bull ${priceText(bull)}, price ${priceText(p)}`}
         className="relative h-4 w-full">
      <div className="absolute top-1/2 h-0.5 -translate-y-1/2 rounded bg-slate-600"
           style={{ left: `${pct(bear)}%`, width: `${Math.max(1, pct(bull) - pct(bear))}%` }} />
      {[bear, base, bull].map((v, i) => (
        <div key={i} className="absolute top-1/2 h-2 w-px -translate-y-1/2 bg-slate-300"
             style={{ left: `${pct(v)}%` }} />
      ))}
      {p != null && (
        <div data-price-dot className="absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-amber-400"
             style={{ left: `${pct(p)}%` }} />
      )}
    </div>
  );
}

/** Rebuild (2026-11-16 brief) — freshness: the snapshot's stamp, its
 * age, and a staleness badge judged against the stated cadence. The
 * snapshot-stamp testid and text shape are the page's standing stamp;
 * the badge is additive. */
function FreshnessBar({ board, snapshot }: {
  board: GuidanceBoard | null; snapshot: SnapshotStamp | null;
}) {
  const f = board?.freshness ?? null;
  if (!snapshot && !f) return null;
  const computed = f?.computed_at ?? snapshot?.computed_at ?? null;
  const snapId = f?.snapshot_id ?? snapshot?.id ?? null;
  const stamp = (snapId != null
    ? `Snapshot #${snapId} · computed ${computed ? ctDateTimeYear(computed) : "—"}`
    : "Unversioned legacy read — no snapshot stamp on this data yet")
    + (f?.previous_snapshot_id != null ? ` · movers measured against snapshot #${f.previous_snapshot_id}` : "")
    + (f ? ` · ${f.cadence}.` : "")
    + " — one consistent snapshot; a recompute publishes a new snapshot, it never edits this one.";
  return (
    <div data-testid="freshness-bar" className="flex min-w-0 items-center gap-x-3">
      <p data-testid="snapshot-stamp" title={stamp} className="min-w-0 truncate text-xs text-slate-500">
        {stamp}
      </p>
      {f && f.age_hours != null && (
        <span data-testid="freshness-age" className="shrink-0 text-xs text-slate-500">
          {`Snapshot age ${f.age_hours < 1 ? "<1" : Math.round(f.age_hours)}h`}
        </span>
      )}
      {f?.stale && (
        <span data-testid="freshness-stale"
              className="shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-xs font-medium text-amber-300">
          Stale — older than the stated cadence
        </span>
      )}
    </div>
  );
}

const STATUS_LABELS: Record<string, string> = {
  below_bear: "Below bear band", buy_zone: "Below guidance value", between: "In line",
  above_bull: "Above guidance value", no_band: "No band",
};

function pctText(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function capText(v: number | null | undefined): string {
  if (v == null) return "—";
  return v >= 1e12 ? `$${(v / 1e12).toFixed(2)}T` : v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : `$${(v / 1e6).toFixed(0)}M`;
}

/** Rebuild — the movers lead: what changed between the two latest
 * completed snapshots. Guide revisions ranked by size with held names
 * pinned first (the served order), band migrations, and the held
 * names' band status. With no previous snapshot the section says so
 * and invents nothing. */
function MoversSection({ board }: { board: GuidanceBoard }) {
  const movers = board.movers;
  return (
    <section data-testid="movers" aria-label="Movers">
      <h2 className="text-lg font-semibold text-white">Movers — since the previous snapshot</h2>
      {!movers ? (
        <p className="mt-2 text-sm text-slate-400">
          No previous completed snapshot to measure movers against yet — the
          movers start with the next snapshot.
        </p>
      ) : (
        <div className="mt-2 space-y-3">
          {movers.guide_revisions.length === 0 && movers.band_migrations.length === 0 ? (
            <p className="text-sm text-slate-400">
              No guide revisions or band migrations between the two latest snapshots.
            </p>
          ) : (
            <>
              {movers.guide_revisions.length > 0 && (
                <ul className="space-y-1.5">
                  {movers.guide_revisions.map((r, i) => (
                    <li key={`${r.ticker}-${r.metric}-${i}`}
                        data-testid={`mover-${r.ticker}-${r.metric}`}
                        className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2">
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className="font-semibold text-white">{r.ticker}</span>
                        {r.held && (
                          <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-xs font-medium text-sky-300">Held</span>
                        )}
                        <span className="text-sm text-slate-300">
                          {r.metric === "anchor"
                            ? `Guide revised (${metricLabel(r.guide_metric ?? "")})`
                            : r.metric === "capex" ? "Capex guide revised" : "FCF guide revised"}
                          {` — ${pctText(r.change_pct)}`}
                          {r.from && r.to
                            ? ` · ${feedFigure(r.guide_metric, r.from[0])}–${feedFigure(r.guide_metric, r.from[1])} → ${feedFigure(r.guide_metric, r.to[0])}–${feedFigure(r.guide_metric, r.to[1])}`
                            : ""}
                          {r.direction ? ` (${r.direction})` : ""}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              {movers.band_migrations.length > 0 && (
                <ul className="space-y-1.5">
                  {movers.band_migrations.map((m, i) => (
                    <li key={`${m.ticker}-mig-${i}`} data-testid={`migration-${m.ticker}`}
                        className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2">
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className="font-semibold text-white">{m.ticker}</span>
                        {m.held && (
                          <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-xs font-medium text-sky-300">Held</span>
                        )}
                        <span className="text-sm text-slate-300">
                          {`Band migration — ${zoneInfo(m.from_zone).label} → ${zoneInfo(m.to_zone).label}`}
                          {m.price != null ? ` · price ${priceText(m.price)}` : ""}
                        </span>
                      </div>
                      {m.bands && (
                        <div className="mt-1 max-w-md">
                          <BandTrack bands={m.bands} price={m.price ?? null} ticker={m.ticker} />
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          {movers.held_status.length > 0 && (
            <p data-testid="held-status" className="text-sm text-slate-400">
              {"Held now: "}
              {movers.held_status.map((h, i) => (
                <span key={h.ticker}>
                  {i > 0 ? " · " : ""}
                  <span className="font-medium text-slate-200">{h.ticker}</span>
                  {` ${STATUS_LABELS[h.status] ?? h.status} (${pctText(h.distance_pct)} vs base)`}
                </span>
              ))}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

const FULL_GRID_ROWS = 8;

type GridSort = "distance" | "revision" | "cap";
type GridFilter = "all" | "buy" | "below_bear" | "between" | "above_bull";

/** Rebuild — the football-field grid: every banded name as one row —
 * the band bar with its price marker, the distance to the guidance value as
 * the headline number, held pinned first, then classified (watchlist),
 * then the rest; sortable by distance / guide revision / market cap
 * and filterable by zone status. Prices are the snapshot's, labelled
 * with their as-of. */
function BandGrid({ board, classified, sheetFor, members, ensureMembers }: {
  board: GuidanceBoard; classified: Set<string>;
  sheetFor: (ticker: string) => FactSheet | undefined;
  members: Record<string, string[]>;
  ensureMembers: (sheet: FactSheet) => void;
}) {
  // The ribbon: a row's full fact sheet opens right under it.
  const [ribbonTicker, setRibbonTicker] = useState<string | null>(null);
  const onSelect = (ticker: string) => {
    const sheet = sheetFor(ticker);
    if (!sheet) return;
    setRibbonTicker(ticker);
    ensureMembers(sheet);
  };
  const onCloseRibbon = () => setRibbonTicker(null);
  const [sort, setSort] = useState<GridSort>("distance");
  const [filter, setFilter] = useState<GridFilter>("all");
  // One-screen default (Kevin, 2026-11-16): only the first FULL_ROWS
  // rows under the current sort render as full football fields; the
  // rest are compact one-line rows that expand in place on click.
  // Sorting/filtering always run over the full set — no name is ever
  // dropped or paginated away.
  const [openedRows, setOpenedRows] = useState<Set<string>>(new Set());
  const revisionBy = useMemo(() => {
    const out = new Map<string, number>();
    for (const r of board.movers?.guide_revisions ?? []) {
      if (r.change_pct == null) continue;
      const cur = out.get(r.ticker);
      if (cur === undefined || Math.abs(r.change_pct) > Math.abs(cur)) {
        out.set(r.ticker, r.change_pct);
      }
    }
    return out;
  }, [board]);
  const groupRank = (r: GridRow) => (r.held ? 0 : classified.has(r.ticker) ? 1 : 2);
  const matches = (r: GridRow) => {
    switch (filter) {
      case "buy": return r.status === "buy_zone" || r.status === "below_bear";
      case "below_bear": return r.status === "below_bear";
      case "between": return r.status === "between";
      case "above_bull": return r.status === "above_bull";
      default: return true;
    }
  };
  const rows = board.grid.filter(matches).sort((a, b) => {
    const g = groupRank(a) - groupRank(b);
    if (g !== 0) return g;
    if (sort === "cap") return (b.market_cap ?? -1) - (a.market_cap ?? -1);
    if (sort === "revision") {
      const ra = revisionBy.get(a.ticker), rb = revisionBy.get(b.ticker);
      if (ra === undefined && rb === undefined) return a.ticker.localeCompare(b.ticker);
      if (ra === undefined) return 1;
      if (rb === undefined) return -1;
      return Math.abs(rb) - Math.abs(ra);
    }
    return (a.distance_pct ?? 1e9) - (b.distance_pct ?? 1e9);
  });
  const chipCls = (active: boolean) =>
    `rounded-full px-3 py-1 text-xs font-medium ${active
      ? "bg-slate-100 text-slate-900" : "border border-slate-700 text-slate-300 hover:border-slate-500"}`;
  const filters: { id: string; label: string; value: GridFilter }[] = [
    { id: "grid-filter-all", label: "All banded", value: "all" },
    { id: "grid-filter-buy", label: "Below guidance value", value: "buy" },
    { id: "grid-filter-below-bear", label: "Below bear", value: "below_bear" },
    { id: "grid-filter-between", label: "Between", value: "between" },
    { id: "grid-filter-above-bull", label: "Above bull", value: "above_bull" },
  ];
  const sorts: { id: string; label: string; value: GridSort }[] = [
    { id: "grid-sort-distance", label: "Distance to guidance value", value: "distance" },
    { id: "grid-sort-revision", label: "Guide revision", value: "revision" },
    { id: "grid-sort-cap", label: "Market cap", value: "cap" },
  ];
  return (
    <section data-testid="band-grid" aria-label="Football-field grid">
      <h2 className="text-lg font-semibold text-white">Football-field grid</h2>
      <p className="mt-0.5 text-sm text-slate-400">
        Every banded name, one row: bear / base / bull as the field, the snapshot
        price as the marker, and the distance to the guidance value (the base band) as
        the headline number. Held names pin first, then classified prints. The
        first eight rows under the current sort carry the full field; the rest
        ride compact and expand in place. Selecting a full row opens its fact
        sheet in a ribbon right under it.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {filters.map((f) => (
          <button key={f.id} type="button" data-testid={f.id} aria-pressed={filter === f.value}
                  onClick={() => setFilter(f.value)} className={chipCls(filter === f.value)}>
            {f.label}
          </button>
        ))}
        <span className="mx-1 text-slate-600">|</span>
        {sorts.map((s) => (
          <button key={s.id} type="button" data-testid={s.id} aria-pressed={sort === s.value}
                  onClick={() => setSort(s.value)} className={chipCls(sort === s.value)}>
            {s.label}
          </button>
        ))}
      </div>
      <div className="mt-3 space-y-1.5">
        {rows.map((r, idx) => {
          const full = idx < FULL_GRID_ROWS || openedRows.has(r.ticker);
          if (!full) {
            return (
              <button key={r.ticker} type="button" data-testid={`grid-row-${r.ticker}`}
                      data-compact="true"
                      onClick={() => setOpenedRows((s) => new Set(s).add(r.ticker))}
                      className="block w-full rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-1.5 text-left hover:border-slate-600">
                <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
                  <span className="font-semibold text-white">{r.ticker}</span>
                  {r.held && (
                    <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[11px] font-medium text-sky-300">
                      {`Held${r.books.length ? ` · ${r.books.join(", ")}` : ""}`}
                    </span>
                  )}
                  <span data-testid={`distance-${r.ticker}`}
                        className="text-sm font-semibold text-white">
                    {r.distance_pct == null ? "—" : `${pctText(r.distance_pct)} to guidance value`}
                  </span>
                  <span className="text-xs text-slate-400">{STATUS_LABELS[r.status] ?? r.status}</span>
                  <span className="block w-44 shrink-0">
                    <BandTrack bands={r.bands} price={r.price} ticker={r.ticker} />
                  </span>
                  <span className="text-xs text-slate-500">Full bar →</span>
                </span>
              </button>
            );
          }
          const sheet = sheetFor(r.ticker);
          return (
          <Fragment key={r.ticker}>
          <button type="button" data-testid={`grid-row-${r.ticker}`}
                  onClick={() => onSelect(r.ticker)}
                  className="block w-full rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2 text-left hover:border-slate-600">
            <span className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
              <span className="font-semibold text-white">{r.ticker}</span>
              {r.held && (
                <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[11px] font-medium text-sky-300">
                  {`Held${r.books.length ? ` · ${r.books.join(", ")}` : ""}`}
                </span>
              )}
              <span data-testid={`distance-${r.ticker}`}
                    className="text-base font-semibold text-white">
                {r.distance_pct == null ? "—" : `${pctText(r.distance_pct)} to guidance value`}
              </span>
              <span className="text-xs text-slate-400">{STATUS_LABELS[r.status] ?? r.status}</span>
              <span className="text-xs text-slate-400">
                {`Price ${priceText(r.price)} · snapshot price as of ${r.price_as_of ?? "—"}`}
              </span>
              <span className="text-xs text-slate-400">{`Cap ${capText(r.market_cap)}`}</span>
              {revisionBy.get(r.ticker) !== undefined && (
                <span className="text-xs text-slate-400">
                  {`Guide revision ${pctText(revisionBy.get(r.ticker))}`}
                </span>
              )}
            </span>
            <span className="mt-1 block max-w-xl">
              <BandTrack bands={r.bands} price={r.price} ticker={r.ticker} />
            </span>
            <span className="block text-xs text-slate-500">
              {`Bear ${priceText(r.bands.bear)} · Base ${priceText(r.bands.base)} · Bull ${priceText(r.bands.bull)}`}
            </span>
          </button>
          {ribbonTicker === r.ticker && sheet && (
            <div data-testid={`ribbon-${r.ticker}`}
                 className="rounded-lg border border-slate-700 bg-slate-900/60 px-3.5 py-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className="text-sm font-semibold text-white">
                  {`${r.ticker} — the full fact sheet`}
                </span>
                <button type="button" data-testid={`ribbon-close-${r.ticker}`}
                        onClick={onCloseRibbon}
                        className="shrink-0 text-xs font-medium text-slate-400 hover:text-slate-200">
                  Close
                </button>
              </div>
              <SheetDetail sheet={sheet} members={members[r.ticker]} />
              <NameDecision ticker={r.ticker} />
            </div>
          )}
          </Fragment>
          );
        })}
        {rows.length === 0 && (
          <p className="text-sm text-slate-400">No banded names match this view.</p>
        )}
      </div>
    </section>
  );
}

/** Rebuild — the missing-band queue: held or watched (classified)
 * names with no house band in this snapshot, as a worklist. Each row
 * carries the stored reason and, when the name has a fact sheet, the
 * way into its sheet — where the band-authoring decision view lives. The
 * sheet opens in place under its row (idempotent: a second click keeps it
 * open). The queue lives in its own open view, so the list starts open. */
function MissingBandQueue({ board, sheetFor, members, ensureMembers }: {
  board: GuidanceBoard; sheetFor: (ticker: string) => FactSheet | undefined;
  members: Record<string, string[]>; ensureMembers: (sheet: FactSheet) => void;
}) {
  const [openTicker, setOpenTicker] = useState<string | null>(null);
  const heldNames = board.missing_band.filter((r) => r.held).map((r) => r.ticker);
  return (
    <section data-testid="missing-band-queue" id="missing-band-queue" aria-label="Missing-band queue">
      <p className="text-sm text-slate-400">
        Held or classified names with no house band in this snapshot. A missing
        band is a coverage gap to close, not a name to forget.
      </p>
      {board.missing_band.length === 0 ? (
        <p className="mt-2 text-sm text-slate-400">
          Every held and classified name carries a band in this snapshot.
        </p>
      ) : (
        <>
          <p data-testid="queue-summary" className="mt-2 text-sm text-slate-300">
            {`${board.missing_band.length} ${board.missing_band.length === 1 ? "name has" : "names have"} no band in this snapshot`}
            {heldNames.length > 0 ? ` — held: ${heldNames.join(", ")}` : " — none of them held"}
          </p>
          <ul className="mt-2 space-y-1.5">
            {board.missing_band.map((r) => {
              const sheet = sheetFor(r.ticker);
              return (
                <li key={r.ticker} data-testid={`queue-row-${r.ticker}`}
                    className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-semibold text-white">{r.ticker}</span>
                    {r.held && (
                      <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-xs font-medium text-sky-300">
                        {`Held${r.books.length ? ` · ${r.books.join(", ")}` : ""}`}
                      </span>
                    )}
                    {r.watched && (
                      <span className="rounded bg-slate-500/20 px-1.5 py-0.5 text-xs font-medium text-slate-300">Classified print</span>
                    )}
                    <span className="text-sm text-slate-400">{r.reason ?? "no bands computed"}</span>
                    {sheet && (
                      <button type="button" data-testid={`queue-open-${r.ticker}`}
                              onClick={() => { setOpenTicker(r.ticker); ensureMembers(sheet); }}
                              className="text-sm font-medium text-sky-300 hover:text-sky-200">
                        Open its fact sheet →
                      </button>
                    )}
                  </div>
                  {sheet && openTicker === r.ticker && (
                    <div data-testid={`queue-sheet-${r.ticker}`} className="mt-2 border-t border-slate-800 pt-2">
                      <SheetDetail sheet={sheet} members={members[r.ticker]} />
                      <NameDecision ticker={r.ticker} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

function feedFigure(metric: string | null | undefined, v: number | null | undefined): string {
  if (v == null) return "—";
  return metric === "revenue" ? `$${(v / 1e9).toFixed(2)}B` : v.toFixed(2);
}

function feedText(item: FeedItem): string {
  switch (item.kind) {
    case "conjunction":
      return `Conjunction — ${zoneInfo(item.zone).label} × ${item.classification} print`
        + (item.as_of ? ` (${item.as_of})` : "")
        + ` × recorded screen membership`
        + (item.screens?.length ? ` (${item.screens.join(", ")})` : "");
    case "crossing":
      return `Crossing — ${item.book ? `${item.book} book · ` : ""}${zoneInfo(item.zone).label}`
        + (item.action && item.action !== "none" ? ` · would-be action: ${item.action}` : "");
    case "zone_change":
      return `Zone change — ${zoneInfo(item.from_zone).label} → ${zoneInfo(item.to_zone).label}`;
    case "guide_revision":
      return `Guide revised — ${metricLabel(item.metric ?? "")} `
        + `${feedFigure(item.metric, item.from_low)}–${feedFigure(item.metric, item.from_high)}`
        + ` → ${feedFigure(item.metric, item.to_low)}–${feedFigure(item.metric, item.to_high)}`
        + (item.direction ? ` (${item.direction})` : "");
    case "new_banded":
      return `Newly banded — ${zoneInfo(item.zone).label}`;
    default:
      return item.kind;
  }
}

/** Move 2: the needs-attention feed — only genuine changes vs the
 * previous completed snapshot, in the served (ranked) order with
 * conjunctions pinned first. The empty state is an acceptance item:
 * when nothing changed, it says so plainly and invents nothing. */
function AttentionFeed({ summary }: { summary: PageSummary }) {
  return (
    <section data-testid="attention-feed" aria-label="Needs attention">
      <h2 className="text-lg font-semibold text-white">Needs attention — what changed</h2>
      {summary.feed_state === "no_previous_snapshot" ? (
        <p className="mt-2 text-sm text-slate-400">
          No previous completed snapshot to compare against yet — the feed starts
          with the next snapshot.
        </p>
      ) : summary.feed.length === 0 ? (
        <p className="mt-2 text-sm text-slate-400">
          Nothing changed since the previous snapshot
          {summary.previous_snapshot_id != null ? ` (#${summary.previous_snapshot_id})` : ""}.
        </p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {summary.feed.map((item, i) => (
            <li key={`${item.kind}-${item.ticker}-${i}`}
                data-testid={`feed-item-${item.ticker}`}
                className={`rounded-lg border px-3 py-2 ${item.kind === "conjunction"
                  ? "border-amber-500/40 bg-amber-500/5" : "border-slate-800 bg-slate-900/40"}`}>
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-semibold text-white">{item.ticker}</span>
                {item.kind === "conjunction" && (
                  <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-xs font-medium text-amber-300">Pinned</span>
                )}
                <span className="text-sm text-slate-300">{feedText(item)}</span>
              </div>
              {item.bands && (
                <div className="mt-1 max-w-md">
                  <BandTrack bands={item.bands} price={item.price ?? null} ticker={item.ticker} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Chip({ dot, children }: { dot: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-300">
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden="true" />{children}
    </span>
  );
}

function BandChart({ sheet }: { sheet: FactSheet }) {
  const bands = sheet.bands;
  const price = num(sheet.price);
  if (!bands) return null;
  const a = sheet.anchor;
  const implied = sheet.band_basis === "revenue" ? num(sheet.implied_revenue) : num(sheet.implied_eps);
  const guideFmt = (v: number) => a?.metric === "revenue" ? `$${(v / 1e9).toFixed(2)}B` : v.toFixed(2);
  return (
    <div data-testid={`band-chart-${sheet.ticker}`} className="space-y-3">
      <div>
        <RangeStrip lo={bands.bear} hi={bands.bull} mid={bands.base} marker={price} fmt={priceText}
                    aria={`Band chart: bear ${priceText(bands.bear)}, base ${priceText(bands.base)}, bull ${priceText(bands.bull)}, price ${priceText(price)}`} />
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
          <Chip dot="bg-slate-400">{`Bear ${priceText(bands.bear)}`}</Chip>
          <Chip dot="bg-slate-100">{`Base ${priceText(bands.base)}`}</Chip>
          <Chip dot="bg-slate-400">{`Bull ${priceText(bands.bull)}`}</Chip>
          <Chip dot="bg-amber-500">{`Price ${priceText(price)}`}</Chip>
        </div>
      </div>
      {a && implied != null && (
        <div>
          <RangeStrip lo={a.low} hi={a.high} marker={implied} fmt={guideFmt}
                      aria={`Guide chart: guide ${guideFmt(a.low)} to ${guideFmt(a.high)}, implied at the current price ${guideFmt(implied)}`} />
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            <Chip dot="bg-slate-400">{`Guide low ${guideFmt(a.low)}`}</Chip>
            <Chip dot="bg-slate-400">{`Guide high ${guideFmt(a.high)}`}</Chip>
            <Chip dot="bg-amber-500">{`Implied at price ${guideFmt(implied)}`}</Chip>
          </div>
        </div>
      )}
    </div>
  );
}

function RecordsTable({ records }: { records: GuidanceRecord[] }) {
  if (!records.length) {
    return <p className="text-sm text-slate-400">No guidance records on file for this name.</p>;
  }
  const fmt = (r: GuidanceRecord, v: number | null) =>
    v == null ? "—" : r.metric === "revenue" ? `$${(v / 1e9).toFixed(2)}B` : v.toFixed(2);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-xs">
        <thead>
          <tr className="border-b border-slate-800 text-slate-500">
            <th className="py-1 pr-3 font-medium">Metric</th>
            <th className="py-1 pr-3 font-medium">Period</th>
            <th className="py-1 pr-3 font-medium">Guide</th>
            <th className="py-1 pr-3 font-medium">Consensus</th>
            <th className="py-1 pr-3 font-medium">Filing (accession)</th>
            <th className="py-1 font-medium">Recorded</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r, i) => (
            <tr key={i} className="border-b border-slate-800/60 text-slate-300">
              <td className="py-1 pr-3">{metricLabel(r.metric)}</td>
              <td className="py-1 pr-3">{r.period ?? "—"}</td>
              <td className="py-1 pr-3">
                {r.low == null ? "—" : r.high != null && r.high !== r.low
                  ? `${fmt(r, r.low)}–${fmt(r, r.high)}` : fmt(r, r.low)}
              </td>
              <td className="py-1 pr-3">{r.consensus == null ? "—" : fmt(r, r.consensus)}</td>
              <td className="py-1 pr-3">{r.accession ?? "—"}</td>
              <td className="py-1">{r.created_at ? ctDateTimeYear(r.created_at) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FactBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
      <div className="mt-1.5 space-y-1 text-sm text-slate-300">{children}</div>
    </div>
  );
}

function Kv({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <span className="w-32 shrink-0 text-slate-500">{k}</span>
      <span className="min-w-0">{children}</span>
    </div>
  );
}

function SheetDetail({ sheet, members }: { sheet: FactSheet; members: string[] | undefined }) {
  const a = sheet.anchor;
  const records = sheet.inputs?.guidance_records ?? [];
  const funds = sheet.fundamentals ?? {};
  const fundRows = Object.entries(funds).filter(([k, v]) => k !== "missing" && v && !Array.isArray(v)) as
    [string, { value: number; as_of: string }][];
  const missing = (funds.missing as unknown as string[] | undefined) ?? [];
  const dirs = Object.entries(sheet.directions ?? {});
  return (
    <div className="space-y-4">
      {sheet.status === "banded" && <BandChart sheet={sheet} />}
      {sheet.stale && (
        <p className="text-sm text-amber-300">
          This sheet is stale — the price or the guide is too old to grade, so the zone is held.
          The record below still stands.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {a && (
          <FactBlock title="The guide behind the bands">
            <Kv k="Guide">{guideText(sheet)}</Kv>
            <Kv k="Metric">{metricLabel(a.metric)}</Kv>
            <Kv k="Filing (accession)">{a.accession ?? "—"}</Kv>
            <Kv k="Recorded">{a.recorded_at ? ctDateTimeYear(a.recorded_at) : "—"}</Kv>
            <Kv k="Consensus">{a.consensus == null ? "—" : a.metric === "revenue"
              ? `$${(a.consensus / 1e9).toFixed(2)}B` : a.consensus.toFixed(2)}</Kv>
            <Kv k="Consensus source">{a.consensus_source ?? "—"}
              {a.consensus_period ? ` · ${consensusPeriodText(a.consensus_period)}` : ""}</Kv>
            {sheet.guidance_percentile != null && (
              <Kv k="Guide percentile">{`${ordinal(Math.round(num(sheet.guidance_percentile) ?? 0))} among guided peers`}</Kv>
            )}
            <Kv k="Tier">{sheet.tier === "watch" ? "Watch (S&P 500)" : "Open (any recorded guide)"}</Kv>
          </FactBlock>
        )}
        {sheet.peer_group && (
          <FactBlock title="The peer group behind the multiple">
            <Kv k="Group">{humanizeGroup(sheet.peer_group)}</Kv>
            <Kv k="Median multiple">{multipleText(sheet)}</Kv>
            <Kv k="Multiple frozen">{ctDateTimeYear(sheet.computed_at)}</Kv>
            <Kv k="Peers used">{sheet.peer_count ?? "—"}</Kv>
            <Kv k="Basis">{sheet.peer_basis === "industry_group" ? "Frozen industry group"
              : sheet.peer_basis === "sector_widened" ? "Industry group, widened to the sector"
              : sheet.peer_basis === "sector_fallback" ? "Whole sector (no frozen group)"
              : sheet.peer_basis ?? "—"}</Kv>
            <Kv k="Members">{members === undefined
              ? "Loading the peer list…"
              : members.length ? members.join(", ") : "—"}</Kv>
          </FactBlock>
        )}
        {fundRows.length > 0 && (
          <FactBlock title="Fundamentals snapshot (EDGAR)">
            {fundRows.map(([k, v]) => (
              <Kv key={k} k={FUND_LABELS[k] ?? k}>
                {fmtFund(k, v.value)} <span className="text-slate-500">as of {v.as_of}</span>
              </Kv>
            ))}
            {missing.length > 0 && (
              <p className="text-xs text-slate-500">
                Not on file: {missing.map((k) => FUND_LABELS[k] ?? k).join(", ")}
              </p>
            )}
          </FactBlock>
        )}
        {dirs.length > 0 && (
          <FactBlock title="Guide direction by metric">
            {dirs.map(([metric, d]) => (
              <Kv key={metric} k={metricLabel(metric)}>
                {(DIRECTION_LABELS[d.direction] ?? d.direction)}
                {d.mid != null && ` — mid ${metric === "revenue" ? `$${(d.mid / 1e9).toFixed(2)}B` : d.mid.toFixed(2)}`}
                {d.prev_mid != null && ` (was ${metric === "revenue" ? `$${(d.prev_mid / 1e9).toFixed(2)}B` : d.prev_mid.toFixed(2)})`}
              </Kv>
            ))}
          </FactBlock>
        )}
      </div>
      {(sheet.ingest_notes ?? []).length > 0 && (
        <FactBlock title="Ingest notes — read these before the guide">
          {(sheet.ingest_notes ?? []).map((n, i) => (
            <p key={i} className="text-amber-300">{n}</p>
          ))}
        </FactBlock>
      )}
      {(sheet.guard_rejections ?? []).length > 0 && (
        <FactBlock title="Guard decisions on this name's records">
          {(sheet.guard_rejections ?? []).map((g, i) => (
            <p key={i} className="text-slate-300">{g}</p>
          ))}
        </FactBlock>
      )}
      {sheet.falsifier && (
        <FactBlock title={sheet.status === "banded" ? "What would falsify this sheet" : "Why there are no bands — the sheet's recorded note"}>
          <p className="whitespace-pre-line break-words text-slate-300">{sheet.falsifier}</p>
        </FactBlock>
      )}
      <FactBlock title={`Guidance records on file (${records.length})`}>
        <RecordsTable records={records} />
      </FactBlock>
      <p className="text-xs text-slate-500">
        Sheet computed {ctDateTimeYear(sheet.computed_at)}
        {sheet.snapshot_id != null && ` · snapshot #${sheet.snapshot_id}`}.
      </p>
    </div>
  );
}

function BandedTable({ sheets, basis, expanded, onToggle, members, chips }: {
  sheets: FactSheet[]; basis: string; expanded: string | null;
  onToggle: (t: string) => void; members: Record<string, string[]>;
  chips: Record<string, VerdictChip>;
}) {
  const rows = sheets
    .filter((s) => s.status === "banded" && s.band_basis === basis)
    .sort((x, y) => (ZONE_ORDER[x.baseline_verdict ?? ""] ?? 9) - (ZONE_ORDER[y.baseline_verdict ?? ""] ?? 9)
      || x.ticker.localeCompare(y.ticker));
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full min-w-[980px] text-left text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
            <th className="px-3 py-2 font-medium">Name</th>
            <th className="px-3 py-2 font-medium">Guide</th>
            <th className="px-3 py-2 font-medium">Direction</th>
            <th className="px-3 py-2 font-medium">Multiple</th>
            <th className="px-3 py-2 font-medium">Bear</th>
            <th className="px-3 py-2 font-medium">Base</th>
            <th className="px-3 py-2 font-medium">Bull</th>
            <th className="px-3 py-2 font-medium">Price</th>
            <th className="px-3 py-2 font-medium">Zone</th>
            <th className="px-3 py-2 font-medium">Gap</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const open = expanded === s.ticker;
            const dir = guideDirection(s);
            return [
              <tr key={s.ticker} className="border-b border-slate-800/60 hover:bg-slate-900/40">
                <td className="px-3 py-2">
                  <button type="button" aria-expanded={open} onClick={() => onToggle(s.ticker)}
                          className="inline-flex items-center gap-1 font-semibold text-white">
                    {s.ticker}
                    <ChevronDown className={`h-4 w-4 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
                  </button>
                </td>
                <td className="px-3 py-2 text-slate-200">
                  {guideText(s)}
                  <span className="block text-xs text-slate-500">{s.anchor ? metricLabel(s.anchor.metric) : ""}</span>
                </td>
                <td className="px-3 py-2 text-slate-300">{dir ? (DIRECTION_LABELS[dir] ?? dir) : "—"}</td>
                <td className="px-3 py-2 text-slate-200">
                  {multipleText(s)}
                  <span className="block text-xs text-slate-500">
                    {humanizeGroup(s.peer_group)} · {s.peer_count ?? "—"} peers
                    {" "}· frozen {ctDateYear(s.computed_at)}
                  </span>
                </td>
                <td className="px-3 py-2 text-slate-300">{priceText(s.bands?.bear)}</td>
                <td className="px-3 py-2 text-slate-300">{priceText(s.bands?.base)}</td>
                <td className="px-3 py-2 text-slate-300">{priceText(s.bands?.bull)}</td>
                <td className="px-3 py-2 text-slate-200">
                  {priceText(s.price)}
                  <span className="block text-xs text-slate-500">
                    daily close as of {s.price_as_of ?? "—"} · {s.price_vendor ?? "Yahoo Finance"}
                  </span>
                </td>
                <td className="px-3 py-2">
                  {zoneBadge(s.baseline_verdict)}
                  <VerdictChipLine chip={chips[s.ticker]} ticker={s.ticker} />
                </td>
                <td className="px-3 py-2 text-slate-300">{gapDisplay(s)}</td>
              </tr>,
              open ? (
                <tr key={`${s.ticker}-detail`} className="border-b border-slate-800 bg-slate-900/30">
                  <td colSpan={10} className="px-3 py-3">
                    <SheetDetail sheet={s} members={members[s.ticker]} />
                    <NameDecision ticker={s.ticker} />
                  </td>
                </tr>
              ) : null,
            ];
          })}
        </tbody>
      </table>
    </div>
  );
}

/** The not-banded reason, specific before generic: the guard's own recorded
 * reasons first (they say exactly which check fired), then ingest notes,
 * and only then the sheet's summary note. */
function unbandedNote(sheet: FactSheet): string {
  const guards = sheet.guard_rejections ?? [];
  if (guards.length) {
    const head = guards.slice(0, 2).join("; ");
    return guards.length > 2 ? `${head} (+${guards.length - 2} more)` : head;
  }
  const notes = sheet.ingest_notes ?? [];
  if (notes.length) return notes[0];
  return sheet.falsifier ?? "—";
}

/** The not-banded table cell: the first two guard reasons inline, the rest
 * behind an expandable tail -- the "(+N more)" text used to be a dead end
 * that summarized the remaining reasons away. */
function UnbandedNote({ sheet }: { sheet: FactSheet }) {
  const guards = sheet.guard_rejections ?? [];
  if (guards.length > 2) {
    return (
      <span>
        {guards.slice(0, 2).join("; ")}
        <details className="mt-1">
          <summary className="cursor-pointer text-slate-300 hover:text-white">
            +{guards.length - 2} more
          </summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {guards.slice(2).map((g, i) => <li key={i}>{g}</li>)}
          </ul>
        </details>
      </span>
    );
  }
  return <>{unbandedNote(sheet)}</>;
}

function onFileText(sheet: FactSheet): string {
  const records = sheet.inputs?.guidance_records ?? [];
  if (!records.length) return "Nothing on file";
  const metrics = [...new Set(records.map((r) => metricLabel(r.metric)))];
  return `${metrics.join(", ")} · ${records.length} record${records.length === 1 ? "" : "s"}`;
}

/** Every fact sheet in full: the two banded tables (one per basis, never
 * mixed) and the not-banded table with the recorded reasons. A name's
 * decision view opens in its expansion. */
function TablesView({ sheets, unbandedCount, members, ensureMembers, chips, initialExpanded }: {
  sheets: FactSheet[]; unbandedCount: number; members: Record<string, string[]>;
  ensureMembers: (sheet: FactSheet) => void; chips: Record<string, VerdictChip>;
  initialExpanded: string | null;
}) {
  const [expanded, setExpanded] = useState<string | null>(initialExpanded);
  const toggle = (sheet: FactSheet) => {
    const next = expanded === sheet.ticker ? null : sheet.ticker;
    setExpanded(next);
    if (next) ensureMembers(sheet);
  };
  const onToggle = (t: string) => { const s = sheets.find((x) => x.ticker === t); if (s) toggle(s); };
  const unbanded = sheets.filter((s) => s.status !== "banded");
  return (
    <div data-testid="reference-table" id="reference-table">
      <ZoneLegend />
      <p className="mt-4 max-w-3xl text-sm text-slate-400">
        The record behind the board: every fact sheet in full, with every name's decision view in its expansion.
      </p>
      <section data-testid="basis-eps" aria-label="Bands from earnings guidance" className="mt-6">
        <h3 className="text-base font-semibold text-white">Bands from earnings guidance</h3>
        <p className="mt-0.5 text-sm text-slate-400">
          The recorded full-year EPS guide × the peer group's median forward P/E.
          The bear band carries a 10% haircut to the guide's low end.
        </p>
        <div className="mt-3">
          <BandedTable sheets={sheets} basis="eps" expanded={expanded} onToggle={onToggle} members={members} chips={chips} />
        </div>
      </section>
      <section data-testid="basis-revenue" aria-label="Bands from revenue guidance" className="mt-6">
        <h3 className="text-base font-semibold text-white">Bands from revenue guidance</h3>
        <p className="mt-0.5 text-sm text-slate-400">
          For names that guide revenue but not EPS: the recorded full-year revenue guide ×
          the peer group's median price/sales, per share. Kept in its own table — the two
          bases never mix in one comparison.
        </p>
        <div className="mt-3">
          <BandedTable sheets={sheets} basis="revenue" expanded={expanded} onToggle={onToggle} members={members} chips={chips} />
        </div>
      </section>
      <section data-testid="unbanded" aria-label="Names without bands" className="mt-8">
        <h3 className="text-base font-semibold text-white">{`Not banded — and why (${unbandedCount})`}</h3>
        <p className="mt-0.5 max-w-3xl text-sm text-slate-400">
          A name lands here when the recorder has no usable full-year guide for it. Each
          sheet's recorded note is shown, not hidden — a missing band is a coverage fact,
          not an oversight.
        </p>
        <div className="mt-3 overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">State</th>
                <th className="px-3 py-2 font-medium">On file</th>
                <th className="px-3 py-2 font-medium">Recorded note</th>
              </tr>
            </thead>
            <tbody>
              {unbanded.map((s) => {
                const open = expanded === s.ticker;
                return [
                  <tr key={s.ticker} className="border-b border-slate-800/60 hover:bg-slate-900/40">
                    <td className="px-3 py-2">
                      <button type="button" aria-expanded={open} onClick={() => toggle(s)}
                              className="inline-flex items-center gap-1 font-semibold text-white">
                        {s.ticker}
                        <ChevronDown className={`h-4 w-4 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
                      </button>
                    </td>
                    <td className="px-3 py-2 text-slate-300">{STATE_LABELS[s.status] ?? s.status}</td>
                    <td className="px-3 py-2 text-slate-300">{onFileText(s)}</td>
                    <td className="px-3 py-2 text-slate-400"><UnbandedNote sheet={s} /></td>
                  </tr>,
                  open ? (
                    <tr key={`${s.ticker}-detail`} className="border-b border-slate-800 bg-slate-900/30">
                      <td colSpan={4} className="px-3 py-3">
                        <SheetDetail sheet={s} members={members[s.ticker]} />
                        <NameDecision ticker={s.ticker} />
                      </td>
                    </tr>
                  ) : null,
                ];
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

const ZONE_LEGEND = ["buy_zone_strong", "buy_zone", "neutral", "no_chase_long", "short_zone", "short_zone_strong", "stale"] as const;

/** What the zones mean, plus the page's method note (moved off the page face). */
function ZoneLegend() {
  return (
    <div data-testid="zone-legend" className="rounded-xl border border-slate-800 bg-slate-900/40 px-3.5 py-3">
      <p className="text-sm text-slate-400">
        Each company's own recorded full-year guidance, valued at a 50/50 blend of its own 5-year median
        multiple and its peer group's median (the peer median alone, flagged "peer only", without 5 years of
        history), as bear / base / bull bands — with the zone the current price sits in. A zone says where the
        price sits against the company's own guidance value. Nothing on this page places, sizes, or recommends a trade.
      </p>
      <h3 className="mt-3 text-sm font-medium text-slate-200">What the zones mean</h3>
      <ul className="mt-2 grid gap-x-6 gap-y-1 text-xs text-slate-400 md:grid-cols-2">
        {ZONE_LEGEND.map((v) => (
          <li key={v} className="flex gap-2">
            <span className="shrink-0">{zoneBadge(v)}</span>
            <span>{zoneInfo(v).blurb}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-slate-500">
        The gap column reads the distance from the guide midpoint in guide-range widths:
        +1.0 means the figure the price implies sits one full guide range above the midpoint.
      </p>
    </div>
  );
}

/** A KPI tile: one number, its label on the same line of text. */
function Kpi({ value, label, sub, className = "" }: {
  value: string | number; label: string; sub?: string; className?: string;
}) {
  return (
    <div className={`min-w-0 rounded-lg border border-slate-800 bg-slate-900/60 p-2 sm:p-3 ${className}`}>
      <div className="truncate font-display text-2xl sm:text-[1.75rem] font-semibold leading-none tabular-nums text-white">{value}</div>
      {" "}
      <div className="mt-1 truncate text-xs text-slate-400">{label}</div>
      {sub && <div className="hidden truncate text-[11px] text-slate-500 sm:block">{sub}</div>}
    </div>
  );
}

/** One row of the page's names list: where a banded name sits, at a glance. */
interface NameRow {
  ticker: string; verdict: string | null; distance: number | null;
  bands: GridRow["bands"]; price: number | string | null; held: boolean;
}

const namesFromSheets = (sheets: FactSheet[]): NameRow[] =>
  sheets.filter((s) => s.status === "banded").map((s) => {
    const base = num(s.bands?.base), p = num(s.price);
    return {
      ticker: s.ticker, verdict: s.baseline_verdict ?? null, held: false, price: s.price,
      distance: base ? ((p ?? NaN) / base - 1) * 100 : null,
      bands: { bear: num(s.bands?.bear), base, bull: num(s.bands?.bull) },
    };
  }).map((r) => ({ ...r, distance: r.distance != null && Number.isFinite(r.distance) ? r.distance : null }));

/** The names most worth a look: held first, then classified prints, then the
 * most below guidance value (the grid's default order). Five rows; the rest
 * open in the full tables. */
function NamesList({ rows, total, sheetFor, members, ensureMembers, chips, onShowAll }: {
  rows: NameRow[]; total: number; sheetFor: (t: string) => FactSheet | undefined;
  members: Record<string, string[]>; ensureMembers: (sheet: FactSheet) => void;
  chips: Record<string, VerdictChip>; onShowAll: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <section data-testid="names-list" aria-label="Names to look at"
             className="mt-3 rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-xs font-medium text-slate-400">Names to look at</h2>
        <button type="button" data-testid="names-show-all" onClick={onShowAll}
                className="text-xs font-medium text-sky-300 hover:text-sky-200">
          {`Show all ${total}`}
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="mt-2 text-xs text-slate-500">—</p>
      ) : (
        <ul className="mt-1 divide-y divide-slate-800/70">
          {rows.slice(0, PEEK).map((r) => {
            const sheet = sheetFor(r.ticker);
            const isOpen = open === r.ticker;
            return (
              <li key={r.ticker} data-testid={`name-row-${r.ticker}`}>
                <button type="button" aria-expanded={isOpen}
                        onClick={() => { setOpen(isOpen ? null : r.ticker); if (!isOpen && sheet) ensureMembers(sheet); }}
                        className="flex w-full items-center gap-2 py-1.5 text-left text-xs tabular-nums">
                  <span className="w-14 shrink-0 font-semibold text-white">{r.ticker}</span>
                  {r.held && <span className="shrink-0 rounded bg-sky-500/15 px-1.5 py-0.5 text-[11px] font-medium text-sky-300">Held</span>}
                  <span className="shrink-0">{zoneBadge(r.verdict)}</span>
                  <span className="hidden min-w-0 flex-1 sm:block">
                    <BandTrack bands={r.bands} price={r.price} ticker={r.ticker} />
                  </span>
                  <span data-testid={`name-distance-${r.ticker}`} className="ml-auto shrink-0 font-semibold text-slate-100">
                    {r.distance == null ? "—" : pctText(r.distance)}
                  </span>
                  <ChevronDown className={`h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform ${isOpen ? "rotate-180" : ""}`} aria-hidden="true" />
                </button>
                {isOpen && sheet && (
                  <div className="pb-3">
                    <VerdictChipLine chip={chips[r.ticker]} ticker={r.ticker} />
                    <div className="mt-2">
                      <SheetDetail sheet={sheet} members={members[r.ticker]} />
                      <NameDecision ticker={r.ticker} />
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** The zone mix as one stacked bar: below / in line / above (+ stale). */
function ZoneMix({ summary }: { summary: ReturnType<typeof summarize> }) {
  const parts = [
    { n: summary.buyZones, label: "below guidance value", cls: "bg-emerald-500" },
    { n: summary.flatZones, label: "in line", cls: "bg-slate-400" },
    { n: summary.shortZones, label: "above guidance value", cls: "bg-rose-500" },
    { n: summary.stale, label: "stale (zone held)", cls: "bg-amber-500" },
  ];
  const total = parts.reduce((a, p) => a + p.n, 0);
  return (
    <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900/60 p-3 col-span-3 lg:col-span-1">
      <div className="flex h-[1.75rem] items-center">
        <div role="img" aria-label="Zone mix" className="flex h-3 w-full overflow-hidden rounded-full bg-slate-800">
          {total > 0 && parts.filter((p) => p.n > 0).map((p) => (
            <div key={p.label} className={p.cls} style={{ width: `${(p.n / total) * 100}%` }} />
          ))}
        </div>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-slate-400">
        {parts.filter((p) => p.n > 0 || p.label.startsWith("below") || p.label.startsWith("above")).map((p) => (
          <span key={p.label} className="inline-flex items-center gap-1">
            <span className={`h-2 w-2 rounded-full ${p.cls}`} aria-hidden="true" />{`${p.n} ${p.label}`}
          </span>
        ))}
      </div>
    </div>
  );
}

const THREE = 3;

export default function Valuation() {
  const [sheets, setSheets] = useState<FactSheet[] | null>(null);
  const [snapshot, setSnapshot] = useState<SnapshotStamp | null>(null);
  const [pageSummary, setPageSummary] = useState<PageSummary | null>(null);
  const [board, setBoard] = useState<GuidanceBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [members, setMembers] = useState<Record<string, string[]>>({});
  const [chips, setChips] = useState<Record<string, VerdictChip>>({});
  const [tablesOpen, setTablesOpen] = useState(false);
  const [searchParams] = useSearchParams();
  const decisionParam = searchParams.get("decision")?.toUpperCase() ?? null;

  useEffect(() => {
    let live = true;
    adminJson<{ snapshot: SnapshotStamp | null; sheets: FactSheet[]; summary?: PageSummary | null; board?: GuidanceBoard | null }>("/api/valuation-bands")
      .then((env) => {
        if (!live) return;
        setSnapshot(env.snapshot);
        setSheets(env.sheets);
        setPageSummary(env.summary ?? null);
        setBoard(env.board ?? null);
      })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : "The fact sheets could not be loaded"); });
    // The verdict chips ride beside the sheets: a name with no rendered
    // verdict is simply absent from the map, and its cell says so.
    adminJson<ChipsPayload>("/api/verdict-chips")
      .then((env) => { if (live && env?.chips) setChips(env.chips); })
      .catch(() => { /* absence renders as "No debate verdict yet" */ });
    return () => { live = false; };
  }, []);

  // Deep link from a Screening row (?decision=TICKER): open the full tables
  // with that name's sheet expanded, where its decision view lives.
  useEffect(() => {
    if (decisionParam && sheets?.some((s) => s.ticker === decisionParam)) {
      setTablesOpen(true);
      const sheet = sheets.find((s) => s.ticker === decisionParam);
      if (sheet) ensureMembers(sheet);
    }
  }, [decisionParam, sheets]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Peer members ride the per-name read; load once, on first open.
  const ensureMembers = (sheet: FactSheet) => {
    if (!sheet.peer_group || members[sheet.ticker] !== undefined) return;
    adminJson<FactSheet>(`/api/valuation-bands/${sheet.ticker}`)
      .then((row) => setMembers((m) => ({ ...m, [sheet.ticker]: row.peer_members ?? [] })))
      .catch(() => setMembers((m) => ({ ...m, [sheet.ticker]: [] })));
  };
  const sheetFor = (t: string) => (sheets ?? []).find((s) => s.ticker === t);

  const summary = useMemo(() => (sheets ? summarize(sheets) : null), [sheets]);
  const classified = useMemo(() => new Set((pageSummary?.classified_names ?? []).map((c) => c.ticker)), [pageSummary]);

  const nameRows = useMemo<NameRow[]>(() => {
    const rows: NameRow[] = board
      ? board.grid.map((g) => ({ ticker: g.ticker, verdict: g.zone, distance: g.distance_pct, bands: g.bands, price: g.price, held: g.held }))
      : namesFromSheets(sheets ?? []);
    const rank = (r: NameRow) => (r.held ? 0 : classified.has(r.ticker) ? 1 : 2);
    return rows.sort((a, b) => rank(a) - rank(b) || (a.distance ?? 1e9) - (b.distance ?? 1e9));
  }, [board, sheets, classified]);

  const tablesView = (initial: string | null) => sheets && summary && (
    <TablesView sheets={sheets} unbandedCount={summary.unbanded} members={members}
                ensureMembers={ensureMembers} chips={chips} initialExpanded={initial} />
  );

  const movers = board?.movers ?? null;
  const moverCount = movers ? movers.guide_revisions.length + movers.band_migrations.length : null;
  const feed = pageSummary?.feed ?? [];
  const missing = board?.missing_band ?? null;

  return (
    <div className="mx-auto max-w-6xl px-4 py-3 md:px-8">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-2xl font-bold tracking-tight text-white">Guidance</h1>
        <span data-testid="display-only"
              title="A zone says where the price sits against the company's own guidance value. Nothing here places, sizes, or recommends a trade."
              className="rounded border border-amber-500/30 bg-amber-500/5 px-2 py-0.5 text-xs font-medium text-amber-200">
          Display only — not trade recommendations
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-400">
        Recorded full-year guidance as bear / base / bull bands, with the zone the price sits in.
      </p>

      {error && <p role="alert" className="mt-4 text-sm text-rose-300">{error}</p>}
      {!sheets && !error && (
        <p className="mt-6 inline-flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading fact sheets…
        </p>
      )}

      {sheets && summary && (
        <>
          <div className="mt-1"><FreshnessBar board={board} snapshot={snapshot} /></div>

          <div data-testid="valuation-summary"
               className="mt-3 grid grid-cols-3 gap-2 sm:gap-3 lg:grid-cols-[repeat(5,minmax(0,1fr))_minmax(0,2fr)]">
            <Kpi value={summary.total} label="fact sheets" sub="every name with recorded guidance" />
            <Kpi value={summary.banded} label="banded" sub={`${summary.epsBanded} EPS basis · ${summary.revenueBanded} revenue basis`} />
            <Kpi value={summary.unbanded} label="not banded" />
            <Kpi value={moverCount ?? "—"} label="movers" />
            <Kpi value={board ? board.grid.filter((g) => g.held).length : "—"} label="held banded" />
            <ZoneMix summary={summary} />
          </div>

          {!board && (
            <p className="mt-3 text-xs text-amber-300/80">
              The board block did not ride this load — the tables still serve the stamped snapshot;
              the movers, grid, and missing-band queue return with it.
            </p>
          )}

          <div className="mt-3 grid grid-cols-2 items-start gap-3 lg:grid-cols-3">
            {board && (
              <DashCard title="Movers" value={moverCount ?? "—"} sub={movers ? "since the previous snapshot" : "no previous snapshot"}
                        hint="Guide revisions and band migrations between the two latest snapshots."
                        detailTitle="Movers — since the previous snapshot" detail={<MoversSection board={board} />}>
                <div className="hidden sm:block">
                  <PeekRows empty="—" rows={(movers?.guide_revisions ?? []).slice(0, THREE).map((r, i) => ({
                    key: `${r.ticker}-${r.metric}-${i}`, label: r.ticker, aside: r.metric === "anchor" ? "guide" : r.metric,
                    value: pctText(r.change_pct), valueClass: (r.change_pct ?? 0) < 0 ? "text-rose-300" : "text-emerald-300",
                  }))} />
                </div>
              </DashCard>
            )}
            {board && (
              <DashCard title="Football field" value={summary.banded} sub={`${summary.buyZones} below · ${summary.flatZones} in line · ${summary.shortZones} above`}
                        hint="Every banded name: bear / base / bull as the field, the price as the marker."
                        detailTitle="Football field — every banded name"
                        detail={
                          <div className="space-y-4">
                            <ZoneLegend />
                            <BandGrid board={board} classified={classified} sheetFor={sheetFor}
                                      members={members} ensureMembers={ensureMembers} />
                          </div>}>
              </DashCard>
            )}
            <DashCard title="Needs attention" value={pageSummary && pageSummary.feed_state !== "no_previous_snapshot" ? feed.length : "—"}
                      sub={pageSummary ? "changes since the previous snapshot" : "summary not loaded"}
                      hint="Genuine changes only, conjunctions pinned first; with band crossings and the level watcher."
                      detailTitle="Needs attention — what changed"
                      detail={
                        <div className="space-y-4">
                          {pageSummary ? <AttentionFeed summary={pageSummary} /> : (
                            <p className="text-xs text-amber-300/80">
                              The summary block did not ride this load — the feed returns with it;
                              the board and tables serve the stamped snapshot regardless.
                            </p>
                          )}
                          <BandCrossings />
                          <LevelWatcher />
                        </div>}>
              <div className="hidden sm:block">
                <PeekRows empty="—" rows={feed.slice(0, THREE).map((it, i) => ({
                  key: `${it.kind}-${it.ticker}-${i}`, label: it.ticker, aside: it.kind.replace("_", " "),
                  value: it.zone ? zoneInfo(it.zone).label : "—",
                }))} />
              </div>
            </DashCard>
            {board && (
              <DashCard title="Missing a band" value={board.missing_band.length}
                        sub={`${board.missing_band.filter((r) => r.held).length} held`}
                        hint="Held or classified names with no house band: a coverage gap to close."
                        detailTitle={`Missing a band — the worklist (${board.missing_band.length})`}
                        detail={<MissingBandQueue board={board} sheetFor={sheetFor} members={members} ensureMembers={ensureMembers} />}>
                <div className="hidden sm:block">
                  <PeekRows empty="—" rows={board.missing_band.slice(0, THREE).map((r) => ({
                    key: r.ticker, label: r.ticker, aside: r.held ? "held" : r.watched ? "classified" : undefined,
                    value: r.sheet_status ? (STATE_LABELS[r.sheet_status] ?? r.sheet_status).split(" — ")[0] : "—",
                  }))} />
                </div>
              </DashCard>
            )}
            <DashCard title="Debates" value={pageSummary ? pageSummary.counts.pending_debates : "—"} sub="pending in the queue"
                      hint="The debate queue, agent debates and valuation debates."
                      detailTitle="Debates"
                      detail={<div id="debate-queue-anchor"><DebateQueue /><DebatesSection /></div>} />
            <DashCard title="Fact sheets" value={summary.total}
                      sub={`${summary.epsBanded} EPS · ${summary.revenueBanded} revenue · ${summary.unbanded} not banded`}
                      hint="Every fact sheet in full: the earnings and revenue band tables and the not-banded reasons."
                      detailTitle={`Fact sheets — every name in full (${summary.total})`}
                      detail={tablesView(null)} />
          </div>

          <NamesList rows={nameRows} total={summary.total} sheetFor={sheetFor} members={members}
                     ensureMembers={ensureMembers} chips={chips} onShowAll={() => setTablesOpen(true)} />
          {tablesOpen && (
            <FullView title={`Fact sheets — every name in full (${summary.total})`} onClose={() => setTablesOpen(false)}>
              {tablesView(decisionParam)}
            </FullView>
          )}
        </>
      )}
    </div>
  );
}
