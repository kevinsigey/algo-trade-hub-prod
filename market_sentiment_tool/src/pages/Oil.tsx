import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { HOURLY_HEADLINE } from "@/lib/forecasterLabels";
import { ChevronDown } from "lucide-react";

import { Chip, type Tone } from "@/components/Chip";
import { JournalDetail } from "@/components/JournalDetail";
import { getJson } from "@/lib/getJson";
import { FifteenMinutePanel } from "@/components/FifteenMinutePanel";
import { StrikeRecordLine } from "@/components/StrikeRecordLine";
import { LiveChip } from "@/components/LiveChip";
import { NextRelease } from "@/components/NextRelease";
import { Stat } from "@/components/Stat";
import type { FrozenForecast, JournalFeed, JournalResponse } from "@/lib/journal";
import { STATUS_WORDS, skillText, totals, split, viewRows, type Status, type ViewRow } from "@/lib/journalView";
import { buyBelowLimit, cents } from "@/lib/oilFees";

/**
 * /oil: the two live predictions, one page. The next 15 minutes first, because it turns over fastest and states a
 * direction, then the next hour's range and strikes. The graded record sits below both, kept visibly apart from the
 * live display. The Hormuz tracker has its own tab (OilLayout).
 */
const STATUS_TONE: Record<Status, Tone> = { waiting: "quiet", early: "quiet", ahead: "good", behind: "bad", promoted: "good" };
const OIL = new Set(["oil_wti", "oil_wti_cautious", "kalshi_implied_oil", "baseline_persistence_oil"]);
const OIL_15M = new Set(["oil_wti_15m", "oil_brent_15m", "natgas_15m", "kalshi_implied_oil_wti_15m", "kalshi_implied_oil_brent_15m", "kalshi_implied_natgas_15m"]);
const OIL_HOURLY = new Set(["oil_wti_hourly", "oil_wti_hourly_cautious", "kalshi_implied_oil_hourly", "baseline_persistence_oil_hourly"]);
const REFRESH_MS = 10 * 60 * 1000;

const MONTHS: Record<string, number> = { JAN: 0, FEB: 1, MAR: 2, APR: 3, MAY: 4, JUN: 5, JUL: 6, AUG: 7, SEP: 8, OCT: 9, NOV: 10, DEC: 11 };

interface LadderRow { strike: number; ours: number; market: number | null }

/** "KXWTIH-26NOV0214" -> "Nov 2 · 2 PM ET" (the suffix hour is the ET settle hour). */
function eventLabel(event: string): string {
  const m = event.match(/-(\d{2})([A-Z]{3})(\d{2})(\d{2})$/);
  if (!m) return event;
  const [, , mon, day, hh] = m;
  const month = new Date(2000, MONTHS[mon] ?? 0, 1).toLocaleString("en-US", { month: "short" });
  const hour = Number(hh);
  return `${month} ${Number(day)} · ${hour % 12 === 0 ? 12 : hour % 12} ${hour < 12 ? "AM" : "PM"} ET`;
}

/** The strike where P(above) crosses `level`, interpolated; null when the ladder never crosses. */
function crossing(rows: LadderRow[], pick: (r: LadderRow) => number | null, level = 0.5): number | null {
  for (let i = 0; i + 1 < rows.length; i++) {
    const a = pick(rows[i]);
    const b = pick(rows[i + 1]);
    if (a === null || b === null) continue;
    if (a >= level && b <= level && a !== b) {
      return rows[i].strike + ((a - level) / (a - b)) * (rows[i + 1].strike - rows[i].strike);
    }
  }
  return null;
}

interface LiveRow { strike: number; ours: number; market: number | null; yes_bid?: number | null; yes_ask?: number | null }
interface StrikePick {
  strike: number; side: "yes" | "no"; prob: number; cost: number; edge_pts: number; net_pts: number;
}
interface LiveLadder {
  state: string;
  reason?: string;
  event?: string;
  minutes_to_close?: number;
  as_of?: string;
  live_price?: number;
  price_at?: string;
  price_age_minutes?: number;
  price_source?: "hyperliquid" | "cl=f";
  our_level?: number | null;
  market_level?: number | null;
  geo?: { stress_score: number; k: number; partial: boolean } | null;
  best?: StrikePick | null;
  closest?: StrikePick | null;
  rows?: LiveRow[];
}

/**
 * Direction at a glance (Kevin, 2026-11-03 -- the full strike list was not an
 * intuitive way to read direction): the two probability curves against price,
 * with the live print, our 50% level and Kalshi's marked, and the band between
 * the two levels shaded -- that band IS the disagreement, and which side of it
 * our curve sits on is the lean. The full ladder stays one dropdown away.
 */
function DirectionChart({ rows, livePrice, ourLevel, marketLevel }: {
  rows: LiveRow[];
  livePrice?: number;
  ourLevel?: number | null;
  marketLevel?: number | null;
}) {
  const W = 720;
  const H = 196;
  const PL = 36;
  const PR = 12;
  const PT = 48;
  const PB = 22;
  const marks = [livePrice, ourLevel, marketLevel].filter((v): v is number => v !== null && v !== undefined);
  const lo = Math.min(...rows.map((r) => r.strike), ...marks);
  const hi = Math.max(...rows.map((r) => r.strike), ...marks);
  const padX = (hi - lo) * 0.08 || 1;
  const x0 = lo - padX;
  const x1 = hi + padX;
  const X = (v: number) => PL + ((v - x0) / (x1 - x0)) * (W - PL - PR);
  const Y = (p: number) => PT + (1 - p) * (H - PT - PB);
  const line = (pick: (r: LiveRow) => number | null, extend: boolean) => {
    const pts = rows.filter((r) => pick(r) !== null).sort((a, b) => a.strike - b.strike);
    if (pts.length < 2) return "";
    let d = extend
      ? `M ${X(x0).toFixed(1)} ${Y(pick(pts[0])!).toFixed(1)} L ${X(pts[0].strike).toFixed(1)} ${Y(pick(pts[0])!).toFixed(1)}`
      : `M ${X(pts[0].strike).toFixed(1)} ${Y(pick(pts[0])!).toFixed(1)}`;
    for (const r of pts.slice(1)) d += ` L ${X(r.strike).toFixed(1)} ${Y(pick(r)!).toFixed(1)}`;
    if (extend) d += ` L ${X(x1).toFixed(1)} ${Y(pick(pts[pts.length - 1])!).toFixed(1)}`;
    return d;
  };
  // Marker labels take lanes (Kevin's rule: chart labels never overlap).
  // Levels cluster -- our 50% level, Kalshi's and the live print can sit
  // cents apart -- so each label gets the lowest lane its width fits in,
  // and the marker line starts below the lanes.
  const LANE_Y = [14, 28, 42];
  const markerSpecs = [
    { v: marketLevel, cls: "#94a3b8", label: marketLevel != null ? `Kalshi $${marketLevel.toFixed(2)}` : "", dash: true },
    { v: ourLevel, cls: "#fbbf24", label: ourLevel != null ? `Us $${ourLevel.toFixed(2)}` : "", dash: true },
    { v: livePrice, cls: "#f8fafc", label: livePrice != null ? `WTI $${livePrice.toFixed(2)}` : "", dash: false },
  ].filter((m) => m.v !== null && m.v !== undefined);
  const laneRight: number[] = [];
  const placed = markerSpecs
    .map((m) => {
      const half = (m.label.length * 6.4) / 2 + 6;
      const cx = Math.min(Math.max(X(m.v!), PL + half), W - PR - half);
      return { ...m, cx, half };
    })
    .sort((a, b) => a.cx - b.cx)
    .map((m) => {
      let lane = LANE_Y.findIndex((_, i) => m.cx - m.half > (laneRight[i] ?? -Infinity) + 8);
      if (lane === -1) lane = LANE_Y.length - 1;
      laneRight[lane] = m.cx + m.half;
      return { ...m, y: LANE_Y[lane] };
    });
  const marketPts = rows.filter((r) => r.market !== null);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-3 w-full" role="img" aria-label="Chance of settling above each price: us versus Kalshi">
      {ourLevel != null && marketLevel != null && (
        <rect x={X(Math.min(ourLevel, marketLevel))} width={Math.abs(X(ourLevel) - X(marketLevel))}
              y={PT - 2} height={H - PT - PB + 2} fill="rgb(251 191 36 / 0.08)" />
      )}
      <line x1={PL} x2={W - PR} y1={Y(0.5)} y2={Y(0.5)} stroke="#475569" strokeWidth="1" strokeDasharray="2 4" />
      <text x={PL - 6} y={Y(0.5) + 4} textAnchor="end" fontSize="10" fill="#64748b">50%</text>
      <text x={PL - 6} y={Y(0.98) + 4} textAnchor="end" fontSize="10" fill="#64748b">100%</text>
      <text x={PL - 6} y={Y(0.02) + 4} textAnchor="end" fontSize="10" fill="#64748b">0%</text>
      <path d={line((r) => r.market, false)} fill="none" stroke="#94a3b8" strokeWidth="1.6" strokeDasharray="5 4" />
      {marketPts.map((r) => (
        <circle key={r.strike} cx={X(r.strike)} cy={Y(r.market!)} r="2.4" fill="#94a3b8" />
      ))}
      <path d={line((r) => r.ours, true)} fill="none" stroke="#fbbf24" strokeWidth="2.2" />
      {placed.map((m) => (
        <g key={m.label}>
          <line x1={X(m.v!)} x2={X(m.v!)} y1={PT - 2} y2={H - PB} stroke={m.cls} strokeWidth="1.2" strokeDasharray={m.dash ? "4 3" : undefined} />
          <text x={m.cx} y={m.y} textAnchor="middle" fontSize="11" fontWeight="600" fill={m.cls}>{m.label}</text>
        </g>
      ))}
      <text x={PL} y={H - 6} fontSize="10" fill="#64748b">${x0.toFixed(2)}</text>
      <text x={W - PR} y={H - 6} textAnchor="end" fontSize="10" fill="#64748b">${x1.toFixed(2)}</text>
    </svg>
  );
}

const LIVE_REFRESH_MS = 30 * 1000;

/**
 * The LIVE hero (Kevin's redesign, 2026-11-03): the v1 hourly model
 * recomputed against the market as it stands now, polled every 30
 * seconds. Inside the last 20 minutes before a close the endpoint
 * already targets the NEXT hour's event, so there is always a live
 * prediction on screen and it tightens as the market moves. The frozen
 * ladder further down stays the graded record -- this one is labelled
 * LIVE and is never scored.
 */
function LiveHero() {
  const [live, setLive] = useState<LiveLadder | null>(null);
  const [tick, setTick] = useState(0);
  const [howOpen, setHowOpen] = useState(false);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), LIVE_REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    getJson<LiveLadder>("/api/oil/hourly-live").then(setLive).catch(() => setLive(null));
  }, [tick]);

  if (!live) {
    return (
      <section aria-label="Live next hour" className="rounded-xl border border-slate-700 bg-slate-900/60 p-5">
        <h2 className="text-lg font-semibold text-white">Next hour</h2>
        <p className="mt-1 text-sm text-slate-400">Reading the live market…</p>
      </section>
    );
  }
  if (live.state !== "live" || !live.rows || !live.event) {
    return (
      <section aria-label="Live next hour" className="rounded-xl border border-slate-700 bg-slate-900/60 p-5">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <h2 className="text-lg font-semibold text-white">Next hour</h2>
          {live.event && <span className="text-sm text-slate-400">{eventLabel(live.event)}</span>}
        </div>
        <p className="mt-1 text-sm text-slate-400">
          {live.reason ?? "The live ladder is unavailable right now."}
          {live.price_age_minutes != null && <> The last print is {Math.round(live.price_age_minutes)} minutes old.</>}
        </p>
      </section>
    );
  }
  const rows = live.rows;
  const levelText = (v: number | null | undefined) => (v === null || v === undefined ? "outside the ladder" : `$${v.toFixed(2)}`);
  const gap = live.our_level != null && live.market_level != null ? live.our_level - live.market_level : null;
  const asOf = live.as_of ? new Date(live.as_of) : null;
  return (
    <section aria-label="Live next hour" className="rounded-xl border border-slate-700 bg-slate-900/70 p-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <LiveChip />
        <h2 className="text-xl font-semibold text-white">Next hour — {eventLabel(live.event)}</h2>
        <span className="text-xs text-slate-500">
          closes in ~{Math.max(0, Math.round(live.minutes_to_close ?? 0))} min
          {asOf && <> · recomputed {asOf.toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", second: "2-digit" })} ET</>}
        </span>
        {live.geo && (
          <span className="ml-auto rounded-full border border-slate-700 px-2.5 py-0.5 text-[11px] text-slate-300">
            Hormuz stress {live.geo.stress_score} · shadow σ ×{live.geo.k.toFixed(2)}{live.geo.partial ? " · partial feeds" : ""}
          </span>
        )}
      </div>

      <RangeBand rows={rows} />
      <TradeVerdict best={live.best ?? null} closest={live.closest ?? null} priceAge={live.price_age_minutes ?? null} />
      <StrikeBoard rows={rows} best={live.best ?? null} ourLevel={live.our_level ?? null} />

      <div className="mt-4 grid gap-4 text-center sm:grid-cols-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Our 50% level</div>
          <div className="mt-1 text-2xl font-bold tabular-nums text-white">{levelText(live.our_level)}</div>
          <div className="mt-1 text-xs text-slate-500">the settle price we call a coin flip</div>
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Kalshi's 50% level</div>
          <div className="mt-1 text-2xl font-bold tabular-nums text-slate-200">{levelText(live.market_level)}</div>
          <div className="mt-1 text-xs text-slate-500">
            {gap === null ? "no clean crossing in the market ladder" : <>we sit <span className={gap >= 0 ? "text-amber-300" : "text-sky-300"}>{gap >= 0 ? "+" : "−"}${Math.abs(gap).toFixed(2)}</span> vs the market</>}
          </div>
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">WTI live</div>
          <div className="mt-1 text-2xl font-bold tabular-nums text-slate-100">${live.live_price?.toFixed(2)}</div>
          <div className="mt-1 text-xs text-slate-500">
            {live.price_source === "hyperliquid"
              ? "Hyperliquid oil perp, live but not what Kalshi settles on"
              : live.price_age_minutes != null && live.price_age_minutes >= 2
              ? <>print {Math.round(live.price_age_minutes)} min old · the CL=F feed runs delayed</>
              : "the print our probabilities are priced off, right now"}
          </div>
        </div>
      </div>

      {(() => {
        // Zoom to the action: strikes where our probability runs 0.5%-99.5%,
        // plus one strike of run-off at each end so the curves land. Across
        // all 76 strikes the curves pin to the corners and read as no graph.
        const sorted = [...rows].sort((a, b) => a.strike - b.strike);
        const inBand = sorted.filter((r) => r.ours >= 0.005 && r.ours <= 0.995);
        let chartRows = inBand;
        if (inBand.length >= 2) {
          const before = sorted[sorted.indexOf(inBand[0]) - 1];
          const after = sorted[sorted.indexOf(inBand[inBand.length - 1]) + 1];
          chartRows = [before, ...inBand, after].filter(Boolean) as LiveRow[];
        }
        if (chartRows.length < 4) chartRows = sorted;
        return <DirectionChart rows={chartRows} livePrice={live.live_price} ourLevel={live.our_level} marketLevel={live.market_level} />;
      })()}

      <button type="button" aria-expanded={howOpen} onClick={() => setHowOpen((v) => !v)}
              className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-slate-300 underline decoration-dotted underline-offset-4 hover:text-white">
        How to read this graph
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${howOpen ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {howOpen && (
        <div className="mt-2 max-w-3xl space-y-1.5 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2.5 text-[13px] leading-relaxed text-slate-300">
          <div>Each curve reads left to right as price rises: at any price on the bottom axis, the curve's height is the chance the hour <span className="text-white">settles above that price</span>. High on the left (cheap prices are almost surely cleared), low on the right.</div>
          <div><span className="font-semibold text-amber-300">Amber is us</span>, <span className="font-semibold text-slate-300">dashed grey is Kalshi</span> (dots mark the strikes Kalshi actually quotes — early in the hour only the strikes near the money carry quotes). Where a curve crosses the dotted 50% line is that side's coin-flip level, marked at the top.</div>
          <div>The <span className="font-semibold text-white">white line is the live WTI print</span>. The shaded band between the two coin-flip levels is where the two centres disagree; the 80% ranges at the top are read off these same curves, at the 90% and 10% heights. A centre gap is not a direction call — the model has no direction view.</div>
        </div>
      )}

      <p className="mt-3 text-[11px] text-slate-600">
        Recomputed every 30 seconds. Inside the last 20 minutes, this is already the next hour.
      </p>
    </section>
  );
}

function pickLabel(p: StrikePick): string {
  return `${p.side === "yes" ? "Above" : "Below"} $${p.strike.toFixed(2)}`;
}

/** "$100.20 – $104.30"; a missing end means the range runs past the ladder's edge. */
function rangeText(lo: number | null, hi: number | null, first: number, last: number): string {
  if (lo === null && hi === null) return "outside the ladder";
  const loText = lo === null ? `$${first.toFixed(2)}−` : `$${lo.toFixed(2)}`;
  const hiText = hi === null ? `$${last.toFixed(2)}+` : `$${hi.toFixed(2)}`;
  return `${loText} – ${hiText}`;
}

/**
 * The top of the page (Kevin's rebuild, 2026-11-04): the RANGE first — the
 * model's product is a range, not a direction. Our 80% range (the strikes
 * where P(above) crosses 90% and 10%) with Kalshi's implied range beside
 * it, and direction stated plainly: No call. The model centres on the live
 * print, so it has no direction view to sell; the levels below show where
 * its centre sits against Kalshi's.
 */
export function RangeBand({ rows }: { rows: LiveRow[] }) {
  const sorted = [...rows].sort((a, b) => a.strike - b.strike);
  if (sorted.length < 2) return null;
  const first = sorted[0].strike;
  const last = sorted[sorted.length - 1].strike;
  const our = rangeText(crossing(sorted, (r) => r.ours, 0.9), crossing(sorted, (r) => r.ours, 0.1), first, last);
  const kalshiPts = sorted.filter((r) => r.market !== null);
  const kalshi = kalshiPts.length < 2
    ? "not quoted yet"
    : rangeText(crossing(sorted, (r) => r.market, 0.9), crossing(sorted, (r) => r.market, 0.1), first, last);
  return (
    <div className="mt-4 rounded-lg border border-slate-700 bg-slate-950/40 p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Our 80% range</div>
          <div className="mt-1 text-3xl font-bold tabular-nums text-white">{our}</div>
          <div className="mt-1 text-xs text-slate-500">where we put 4-in-5 odds on the settle landing</div>
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Kalshi's 80% range</div>
          <div className="mt-1 text-3xl font-bold tabular-nums text-slate-200">{kalshi}</div>
          <div className="mt-1 text-xs text-slate-500">the same band read off Kalshi's quoted ladder</div>
        </div>
      </div>
      <p className="mt-3 text-sm text-slate-300">
        Direction: <span className="font-semibold text-white">No call</span>
        <span className="text-slate-400"> — the model centres on the live print; it prices the range, not the direction.</span>
      </p>
    </div>
  );
}

/**
 * The trade verdict: either "No trade", or the one strike worth acting on
 * stated as a buy-below limit (the most that can be paid before the fee
 * eats the edge) — never as a bare "best strike" at whatever it costs now.
 */
export function TradeVerdict({ best, closest, priceAge }: { best: StrikePick | null; closest: StrikePick | null; priceAge: number | null }) {
  const stale = priceAge != null && priceAge >= 2;
  return (
    <div className={`mt-4 rounded-lg border p-4 ${best ? (best.side === "yes" ? "border-emerald-500/60 bg-emerald-500/10" : "border-rose-500/60 bg-rose-500/10") : "border-slate-700 bg-slate-950/40"}`}>
      <h3 className="text-sm font-medium text-slate-300">Trade this hour</h3>
      {best ? (
        <>
          <div className={`mt-1 text-4xl font-bold tabular-nums ${best.side === "yes" ? "text-emerald-300" : "text-rose-300"}`}>
            {best.side === "yes" ? "▲" : "▼"} {pickLabel(best)}
          </div>
          <p className="mt-1 text-base text-slate-100 tabular-nums">
            Buy {best.side === "yes" ? "YES" : "NO"} below {cents(buyBelowLimit(best.prob))} · now {cents(best.cost)} · model says {Math.round(best.prob * 100)}% · +{best.net_pts.toFixed(1)} pts after fee at the ask
          </p>
        </>
      ) : (
        <>
          <div className="mt-1 text-2xl font-semibold text-slate-200">No trade</div>
          <p className="mt-1 text-sm text-slate-400 tabular-nums">
            {closest
              ? <>Closest: {pickLabel(closest)}, {closest.side === "yes" ? "YES" : "NO"} at {cents(closest.cost)}, model {Math.round(closest.prob * 100)}%. A pick needs 5+ points over the cost.</>
              : "Kalshi has no two-sided quotes in a tradable range for this hour yet."}
          </p>
        </>
      )}
      <StrikeRecordLine />
      {stale && (
        <p className="mt-1 text-[13px] text-amber-200">
          The model's WTI price is {Math.round(priceAge)} min old, and Kalshi settles on a live feed, so part of any gap can just be the delay.
        </p>
      )}
    </div>
  );
}

/** The strikes as Kalshi lists them: what YES and NO cost at each, the model, and the edge on the better side. */
export function StrikeBoard({ rows, best, ourLevel }: { rows: LiveRow[]; best: StrikePick | null; ourLevel: number | null }) {
  const [all, setAll] = useState(false);
  const sorted = [...rows].sort((a, b) => b.strike - a.strike);
  const quoted = sorted.filter((r) => r.yes_bid != null || r.yes_ask != null);
  const contested = sorted.filter((r) => r.ours >= 0.1 && r.ours <= 0.9);
  const near = quoted.filter((r) => r.ours >= 0.05 && r.ours <= 0.95);
  const base = near.length >= 3 ? near : contested.length >= 3 ? contested : sorted;
  // 9 rows around the pick, or the model's 50% level, so the action never scrolls off.
  const center = best?.strike ?? ourLevel ?? base[Math.floor(base.length / 2)]?.strike ?? 0;
  const levelStrike = ourLevel == null ? null
    : sorted.reduce((a, b) => (Math.abs(b.strike - ourLevel) < Math.abs(a.strike - ourLevel) ? b : a), sorted[0]).strike;
  const window9 = [...base].sort((a, b) => Math.abs(a.strike - center) - Math.abs(b.strike - center)).slice(0, 9);
  // The 50% strike is the reference the pick is read against: it stays in view even when it sits outside the nine.
  const levelRow = levelStrike == null ? null : sorted.find((r) => r.strike === levelStrike) ?? null;
  const withLevel = levelRow && !window9.includes(levelRow) ? [...window9.slice(0, 8), levelRow] : window9;
  const shown = all ? sorted : withLevel.sort((a, b) => b.strike - a.strike);
  const edge = (r: LiveRow) => {
    const yes = r.yes_ask != null ? (r.ours - r.yes_ask) * 100 : null;
    const no = r.yes_bid != null ? (r.yes_bid - r.ours) * 100 : null;
    if (yes == null && no == null) return null;
    return (yes ?? -Infinity) >= (no ?? -Infinity) ? { side: "YES", pts: yes as number } : { side: "NO", pts: no as number };
  };
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full min-w-[28rem] text-sm tabular-nums">
        <thead>
          <tr className="text-left text-xs text-slate-400">
            <th scope="col" className="py-1 font-medium">Settles above</th>
            <th scope="col" className="py-1 text-right font-medium">Model</th>
            <th scope="col" className="py-1 text-right font-medium">YES costs</th>
            <th scope="col" className="py-1 text-right font-medium">NO costs</th>
            <th scope="col" className="py-1 text-right font-medium">Buy below</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => {
            const e = edge(r);
            // The buy-below limit for the row's better side: the most that
            // side can cost before the fee eats the model's edge entirely.
            const limit = e === null ? null
              : e.side === "YES" ? (r.yes_ask != null ? buyBelowLimit(r.ours) : null)
              : (r.yes_bid != null ? buyBelowLimit(1 - r.ours) : null);
            const isBest = best?.strike === r.strike;
            return (
              <tr key={r.strike} className={`border-t border-slate-800/60 ${isBest ? (best?.side === "yes" ? "bg-emerald-500/15" : "bg-rose-500/15") : ""}`}>
                <td className="py-1.5 text-white">
                  ${r.strike.toFixed(2)}
                  {isBest && <span className="ml-2 text-xs font-semibold text-emerald-200">best</span>}
                  {r.strike === levelStrike && !isBest && <span className="ml-2 text-xs text-amber-300">our 50% level</span>}
                </td>
                <td className="py-1.5 text-right text-slate-100">{(r.ours * 100).toFixed(0)}%</td>
                <td className="py-1.5 text-right text-slate-300">{r.yes_ask == null ? "—" : cents(r.yes_ask)}</td>
                <td className="py-1.5 text-right text-slate-300">{r.yes_bid == null ? "—" : cents(1 - r.yes_bid)}</td>
                <td className={`py-1.5 text-right ${e && e.pts >= 5 ? "font-semibold text-emerald-300" : "text-slate-400"}`}>
                  {e && limit !== null ? `${e.side} ≤ ${cents(limit)}` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <button type="button" onClick={() => setAll((v) => !v)} aria-expanded={all}
              className="mt-1 text-xs font-semibold text-slate-300 underline decoration-dotted underline-offset-4 hover:text-white">
        {all ? "Show strikes near the money" : `All ${sorted.length} strikes`}
      </button>
    </div>
  );
}

function NextHourHero({ ours, market }: { ours: JournalFeed | null; market: JournalFeed | null }) {
  const forecasts = ours?.forecasts ?? [];
  // The next hour is the most recently frozen event: freezes land ~65 minutes
  // before each hour, so the freshest event group is the upcoming settle.
  const events = new Map<string, FrozenForecast[]>();
  for (const f of forecasts) {
    const event = f.target.replace(/^kalshi:/, "").replace(/-T[\d.]+$/, "");
    events.set(event, [...(events.get(event) ?? []), f]);
  }
  let event: string | null = null;
  let group: FrozenForecast[] = [];
  for (const [e, g] of events) {
    if (g.length && (event === null || Math.max(...g.map((f) => Date.parse(f.frozen_at))) > Math.max(...group.map((f) => Date.parse(f.frozen_at))))) {
      event = e;
      group = g;
    }
  }
  if (!event || group.length === 0) {
    return (
      <section aria-label="Next hour" className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 className="text-lg font-semibold text-white">Next hour</h2>
        <p className="mt-1 text-sm text-slate-400">No ladder yet — it freezes 65 minutes before the hour.</p>
      </section>
    );
  }
  const marketByTarget = new Map((market?.forecasts ?? []).map((f) => [f.target, f.probability]));
  const rows: LadderRow[] = group
    .map((f) => {
      const strike = Number(f.target.match(/-T([\d.]+)$/)?.[1]);
      return { strike, ours: f.probability, market: marketByTarget.get(f.target) ?? f.market_prob };
    })
    .filter((r) => Number.isFinite(r.strike))
    .sort((a, b) => a.strike - b.strike);
  const ourLevel = crossing(rows, (r) => r.ours);
  const marketLevel = crossing(rows, (r) => r.market);
  const frozenAt = new Date(Math.max(...group.map((f) => Date.parse(f.frozen_at))));
  const band = rows.filter((r) => r.ours >= 0.02 && r.ours <= 0.98);
  const shown = band.length >= 3 ? band : rows;
  const levelText = (v: number | null) => (v === null ? "outside the ladder" : `$${v.toFixed(2)}`);
  return (
    <section aria-label="Next hour" className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-lg font-semibold text-white">Next hour — {eventLabel(event)}</h2>
        <span className="text-xs text-slate-500">
          locked in {frozenAt.toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" })} ET
        </span>
      </div>
      <p className="mt-2 text-base text-slate-100">
        Our 50% level: <span className="font-bold text-white">{levelText(ourLevel)}</span>
        {marketLevel !== null && (
          <> · Kalshi's ladder implies <span className="font-semibold">{levelText(marketLevel)}</span></>
        )}
      </p>
      <p className="mt-1 text-xs text-slate-500">
        Probability the hour settles above each strike — ours beside Kalshi's. Watch the strikes near the 50% level and where the two disagree.
        {shown.length < rows.length && ` Showing the ${shown.length} strikes around the money of ${rows.length}.`}
      </p>
      <table className="mt-3 w-full text-sm tabular-nums">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
            <th className="py-1 font-medium">Strike</th>
            <th className="py-1 font-medium">Us</th>
            <th className="py-1 font-medium">Kalshi</th>
            <th className="py-1 text-right font-medium">Gap</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => {
            const isLevel = ourLevel !== null && Math.abs(r.strike - ourLevel) === Math.min(...shown.map((s) => Math.abs(s.strike - ourLevel)));
            return (
              <tr key={r.strike} className={`border-t border-slate-800/60 ${isLevel ? "bg-slate-800/40" : ""}`}>
                <td className="py-1.5 font-mono text-white">
                  ${r.strike.toFixed(2)}
                  {isLevel && <span className="ml-2 text-[11px] font-semibold uppercase tracking-wide text-amber-300">our 50% level</span>}
                </td>
                <td className="py-1.5 pr-2">
                  <span className="flex items-center gap-2">
                    <span className="h-2 rounded bg-amber-400/80" style={{ width: `${Math.max(2, r.ours * 60)}px` }} />
                    <span className="text-slate-200">{(r.ours * 100).toFixed(0)}%</span>
                  </span>
                </td>
                <td className="py-1.5 pr-2">
                  {r.market === null ? (
                    <span className="text-slate-500">—</span>
                  ) : (
                    <span className="flex items-center gap-2">
                      <span className="h-2 rounded bg-slate-400/80" style={{ width: `${Math.max(2, r.market * 60)}px` }} />
                      <span className="text-slate-300">{(r.market * 100).toFixed(0)}%</span>
                    </span>
                  )}
                </td>
                <td className="py-1.5 text-right text-slate-300">
                  {r.market === null ? "—" : `${r.ours - r.market >= 0 ? "+" : "−"}${Math.abs((r.ours - r.market) * 100).toFixed(0)} pts`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function FrozenRecord({ ours, market }: { ours: JournalFeed | null; market: JournalFeed | null }) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label="Frozen record" className="border border-slate-800">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-900/60"
      >
        <span className="text-base font-semibold text-white">Frozen record</span>
        <span className="text-xs text-slate-500">locked in ~65 minutes before each hour, and graded</span>
        <ChevronDown className={`ml-auto h-5 w-5 shrink-0 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div className="space-y-3 px-4 pb-4">
          
          <NextHourHero ours={ours} market={market} />
          <div className="text-right text-[11px] text-slate-600">Refreshes every 10 minutes.</div>
        </div>
      )}
    </section>
  );
}

function RecordSection({ title, rows }: { title: string; rows: ViewRow[] }) {
  const [open, setOpen] = useState(false);
  if (rows.length === 0) return null;
  return (
    <section aria-label={title} className="border border-slate-800">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-900/60"
      >
        <span className="text-base font-semibold text-white">{title}</span>
        <span className="text-xs text-slate-500">scoring &amp; settlements</span>
        <ChevronDown className={`ml-auto h-5 w-5 shrink-0 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div className="space-y-6 px-4 pb-4">
          {rows.map((row) => (
            <section key={row.key} aria-label={row.label} className="border-t border-slate-800 pt-4">
              <div className="flex items-baseline justify-between gap-4">
                <h3 className="text-lg font-semibold text-slate-100">{row.label}</h3>
                <div className="flex items-center gap-3">
                  <span className="text-lg tabular-nums text-slate-100">{skillText(row.skill)}</span>
                  <Chip tone={STATUS_TONE[row.status]}>{STATUS_WORDS[row.status]}</Chip>
                </div>
              </div>
              <JournalDetail row={row} />
            </section>
          ))}
        </div>
      )}
    </section>
  );
}

export default function Oil() {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [ours, setOurs] = useState<JournalFeed | null>(null);
  const [market, setMarket] = useState<JournalFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    getJson<JournalResponse>("/api/journal").then(setData).catch((e: Error) => setError(e.message));
  }, [tick]);

  useEffect(() => {
    if (!data) return;
    const hourly = data.forecasters.find((s) => s.forecaster_version === HOURLY_HEADLINE)
      ?? data.forecasters.find((s) => s.forecaster === "oil_wti_hourly");
    const implied = data.forecasters.find((s) => s.forecaster === "kalshi_implied_oil_hourly");
    if (hourly) {
      getJson<JournalFeed>(`/api/journal/feed?forecaster=oil_wti_hourly&version=${hourly.forecaster_version}&limit=250`)
        .then(setOurs)
        .catch(() => setOurs(null));
    }
    if (implied) {
      getJson<JournalFeed>(`/api/journal/feed?forecaster=kalshi_implied_oil_hourly&version=${implied.forecaster_version}&limit=250`)
        .then(setMarket)
        .catch(() => setMarket(null));
    }
  }, [data, tick]);

  if (error) return <div className="p-8 text-rose-300">Oil forecasts unavailable: {error}</div>;
  if (!data) return <div className="p-8 text-slate-400">Loading…</div>;

  const rows = viewRows(data.forecasters.filter((s) => OIL.has(s.forecaster)));
  const hourlySplit = split(viewRows(data.forecasters.filter((s) => OIL_HOURLY.has(s.forecaster))));
  const hourlyRows = [...hourlySplit.results, ...hourlySplit.waiting];
  const fifteenRows = viewRows(data.forecasters.filter((s) => OIL_15M.has(s.forecaster)));
  const t = totals(rows);

  return (
    // Stacked at every width (Kevin, 2026-11-08): the split xl grid squeezed the
    // 15-minute calls into a narrow column; the hour module now sits underneath it.
    <div className="flex flex-col gap-3">
      {/* Reading order follows the page: the 15-minute read, the hour, then the record. */}
      <div className="min-w-0"><FifteenMinutePanel /></div>
      <div className="min-w-0"><LiveHero /></div>
      <div className="flex min-w-0 flex-col gap-3">

      <section aria-label="Track record" className="space-y-2">
        <h2 className="text-lg font-semibold text-white">Track record</h2>
        <section aria-label="Totals" className="grid gap-2 sm:grid-cols-2">
          <Stat value={t.frozen} label="forecasts locked in" />
          <Stat value={t.scored} label="scored so far" />
        </section>
        {t.frozen === 0 && <p className="text-slate-400">Nothing locked in yet. The next one locks 2 hours before the settlement.</p>}
        <NextRelease family="oil" title="Next settlement" />
        <FrozenRecord ours={ours} market={market} />
        <RecordSection title="15-minute settlements" rows={fifteenRows} />
        <RecordSection title="Hourly settlements" rows={hourlyRows} />
        <RecordSection title="Daily settlement" rows={rows} />
        <p className="text-sm text-slate-400">
          The paper trades built on these forecasts, the Kalshi gap tracker among them, are on{" "}
          <Link to="/strategies" className="text-emerald-300 underline-offset-2 hover:underline">Strategies</Link>.
        </p>
      </section>
      </div>
    </div>
  );
}
