import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronDown, Loader2 } from "lucide-react";

import { adminJson } from "@/lib/workshop";
import { ctDateTimeYear, ctDateYear, ordinal } from "@/lib/format";
import BandCrossings from "@/pages/BandCrossings";
import LevelWatcher from "@/pages/LevelWatcher";
import NameDecision from "@/components/NameDecision";
import { VerdictChipLine } from "@/components/VerdictChip";
import type { ChipsPayload, VerdictChip } from "@/lib/decisions";
import {
  consensusPeriodText, gapDisplay, guideDirection, guideText, humanizeGroup, metricLabel, multipleText,
  num, priceText, summarize, zoneInfo,
  type FactSheet, type GuidanceRecord, type SnapshotStamp,
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

function fmtFund(key: string, v: number): string {
  if (key === "shares_diluted") return `${(v / 1e6).toFixed(1)}M`;
  if (key === "eps_diluted") return v.toFixed(2);
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
            <th className="px-3 py-2 font-medium">Peer multiple</th>
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

export default function Valuation() {
  const [sheets, setSheets] = useState<FactSheet[] | null>(null);
  const [snapshot, setSnapshot] = useState<SnapshotStamp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [members, setMembers] = useState<Record<string, string[]>>({});
  const [chips, setChips] = useState<Record<string, VerdictChip>>({});
  const [searchParams] = useSearchParams();
  const decisionParam = searchParams.get("decision")?.toUpperCase() ?? null;

  useEffect(() => {
    let live = true;
    adminJson<{ snapshot: SnapshotStamp | null; sheets: FactSheet[] }>("/api/valuation-bands")
      .then((env) => {
        if (!live) return;
        setSnapshot(env.snapshot);
        setSheets(env.sheets);
      })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : "The valuation sheets could not be loaded"); });
    // The verdict chips ride beside the sheets: a name with no rendered
    // verdict is simply absent from the map, and its cell says so.
    adminJson<ChipsPayload>("/api/verdict-chips")
      .then((env) => { if (live && env?.chips) setChips(env.chips); })
      .catch(() => { /* absence renders as "No debate verdict yet" */ });
    return () => { live = false; };
  }, []);

  // Deep link from a Screening row (?decision=TICKER): open that name's
  // sheet expansion, where its decision view lives.
  useEffect(() => {
    if (!decisionParam || !sheets) return;
    const sheet = sheets.find((s) => s.ticker === decisionParam);
    if (sheet) setExpanded(sheet.ticker);
  }, [decisionParam, sheets]);

  const summary = useMemo(() => (sheets ? summarize(sheets) : null), [sheets]);

  const toggle = (sheet: FactSheet) => {
    const next = expanded === sheet.ticker ? null : sheet.ticker;
    setExpanded(next);
    if (next && sheet.peer_group && members[sheet.ticker] === undefined) {
      adminJson<FactSheet>(`/api/valuation-bands/${sheet.ticker}`)
        .then((row) => setMembers((m) => ({ ...m, [sheet.ticker]: row.peer_members ?? [] })))
        .catch(() => setMembers((m) => ({ ...m, [sheet.ticker]: [] })));
    }
  };

  const unbanded = (sheets ?? []).filter((s) => s.status !== "banded");

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 md:px-8">
      <h1 className="text-2xl font-bold tracking-tight text-white">Guidance</h1>
      <p className="mt-1 max-w-3xl text-sm text-slate-400">
        Each company's own recorded full-year guidance, valued at its peer group's median
        multiple, as bear / base / bull bands — with the zone the current price sits in.
        The guide is what the company itself filed; the multiple is the frozen peer median.
      </p>
      <p className="mt-3 max-w-3xl rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-200">
        Display only — not trade recommendations. A zone says where the price sits against the
        company's own guidance at peer multiples. Nothing on this page places, sizes, or
        recommends a trade.
      </p>

      {error && <p role="alert" className="mt-4 text-sm text-rose-300">{error}</p>}
      {!sheets && !error && (
        <p className="mt-6 inline-flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading valuation sheets…
        </p>
      )}

      {sheets && summary && (
        <>
          <p data-testid="valuation-summary" className="mt-5 text-sm text-slate-300">
            <span className="font-medium text-white">{summary.total} fact sheets</span>
            {" "}— one for every name with recorded guidance ·{" "}
            <span className="font-medium text-white">{summary.banded} banded</span>
            {` (${summary.epsBanded} EPS basis · ${summary.revenueBanded} revenue basis)`} ·{" "}
            {summary.buyZones} {summary.buyZones === 1 ? "in a buy zone" : "in buy zones"} ·{" "}
            {summary.shortZones} {summary.shortZones === 1 ? "in a short zone" : "in short zones"}
            {summary.flatZones > 0 && ` · ${summary.flatZones} neutral or no-chase`}
            {summary.stale > 0 && ` · ${summary.stale} stale (zone held)`}
            {` · ${summary.unbanded} not banded`}
          </p>
          {snapshot ? (
            <p data-testid="snapshot-stamp" className="mt-1 text-xs text-slate-500">
              {`Snapshot #${snapshot.id} · computed ${snapshot.computed_at ? ctDateTimeYear(snapshot.computed_at) : "—"}`}
              {` · ${snapshot.sheet_count ?? summary.total} sheets / ${snapshot.banded_count ?? summary.banded} banded`}
              {" — one consistent snapshot; a recompute publishes a new snapshot, it never edits this one."}
            </p>
          ) : (
            <p data-testid="snapshot-stamp" className="mt-1 text-xs text-amber-300/80">
              Unversioned legacy read — no snapshot stamp on this data yet; figures can
              change between loads until the first stamped compute lands.
            </p>
          )}

          <div data-testid="zone-legend" className="mt-4 rounded-xl border border-slate-800 bg-slate-900/40 px-3.5 py-3">
            <h2 className="text-sm font-medium text-slate-200">What the zones mean</h2>
            <ul className="mt-2 grid gap-x-6 gap-y-1 text-xs text-slate-400 md:grid-cols-2">
              {(["buy_zone_strong", "buy_zone", "neutral", "no_chase_long", "short_zone", "short_zone_strong", "stale"] as const).map((v) => (
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

          <BandCrossings />

          <LevelWatcher />

          <section data-testid="basis-eps" aria-label="Bands from earnings guidance" className="mt-8">
            <h2 className="text-lg font-semibold text-white">Bands from earnings guidance</h2>
            <p className="mt-0.5 text-sm text-slate-400">
              The recorded full-year EPS guide × the peer group's median forward P/E.
              The bear band carries a 10% haircut to the guide's low end.
            </p>
            <div className="mt-3">
              <BandedTable sheets={sheets} basis="eps" expanded={expanded}
                           onToggle={(t) => { const s = sheets.find((x) => x.ticker === t); if (s) toggle(s); }}
                           members={members} chips={chips} />
            </div>
          </section>

          <section data-testid="basis-revenue" aria-label="Bands from revenue guidance" className="mt-8">
            <h2 className="text-lg font-semibold text-white">Bands from revenue guidance</h2>
            <p className="mt-0.5 text-sm text-slate-400">
              For names that guide revenue but not EPS: the recorded full-year revenue guide ×
              the peer group's median price/sales, per share. Kept in its own table — the two
              bases never mix in one comparison.
            </p>
            <div className="mt-3">
              <BandedTable sheets={sheets} basis="revenue" expanded={expanded}
                           onToggle={(t) => { const s = sheets.find((x) => x.ticker === t); if (s) toggle(s); }}
                           members={members} chips={chips} />
            </div>
          </section>

          <section data-testid="unbanded" aria-label="Names without bands" className="mt-10">
            <h2 className="text-lg font-semibold text-white">
              Not banded — and why ({summary.unbanded})
            </h2>
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
        </>
      )}
    </div>
  );
}
