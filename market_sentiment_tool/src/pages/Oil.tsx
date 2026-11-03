import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Chip, type Tone } from "@/components/Chip";
import { JournalDetail } from "@/components/JournalDetail";
import { getJson } from "@/lib/getJson";
import ChokepointsMap from "@/components/ChokepointsMap";
import { NextRelease } from "@/components/NextRelease";
import { Stat } from "@/components/Stat";
import type { FrozenForecast, JournalFeed, JournalResponse } from "@/lib/journal";
import { STATUS_WORDS, skillText, totals, viewRows, type Status, type ViewRow } from "@/lib/journalView";

/**
 * /oil: the Commodities dashboard (Kevin's redesign, 2026-11-03).
 *
 * The hero is LIVE: the next hour's ladder recomputed every 30 seconds off
 * the current WTI print (the endpoint already rolls to the following hour
 * inside the last 20 minutes before a close), our 50% level against
 * Kalshi's, big and center. Below it the Hormuz chokepoints tracker, then
 * the frozen ladder the journal locked in (~65 minutes before each hour)
 * and the scoring/settlements record behind dropdowns -- the graded truth,
 * kept visibly separate from the live display.
 */
const STATUS_TONE: Record<Status, Tone> = { waiting: "quiet", early: "quiet", ahead: "good", behind: "bad", promoted: "good" };
const OIL = new Set(["oil_wti", "oil_wti_cautious", "kalshi_implied_oil", "baseline_persistence_oil"]);
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

/** The strike where P(above) crosses 50%, interpolated; null when the ladder never crosses. */
function crossing(rows: LadderRow[], pick: (r: LadderRow) => number | null): number | null {
  for (let i = 0; i + 1 < rows.length; i++) {
    const a = pick(rows[i]);
    const b = pick(rows[i + 1]);
    if (a === null || b === null) continue;
    if (a >= 0.5 && b <= 0.5 && a !== b) {
      return rows[i].strike + ((a - 0.5) / (a - b)) * (rows[i + 1].strike - rows[i].strike);
    }
  }
  return null;
}


interface LiveRow { strike: number; ours: number; market: number | null }
interface ItmPick { strike: number; ours: number; market: number; gap_pts: number; clear_bars: number }
interface ItmRecord {
  frozen: number; settled: number; hits: number;
  hit_rate: number | null; ev_per_dollar: number | null;
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
  our_level?: number | null;
  market_level?: number | null;
  geo?: { stress_score: number; k: number; partial: boolean } | null;
  itm?: ItmPick | null;
  rows?: LiveRow[];
}

/** P(settles above x) read off a ladder by interpolation; null when unusable. */
function probAbove(rows: LiveRow[], x: number, pick: (r: LiveRow) => number | null): number | null {
  const pts = rows.filter((r) => pick(r) !== null).sort((a, b) => a.strike - b.strike);
  if (pts.length < 2) return null;
  if (x <= pts[0].strike) return pick(pts[0]);
  if (x >= pts[pts.length - 1].strike) return pick(pts[pts.length - 1]);
  for (let i = 0; i + 1 < pts.length; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    if (x >= a.strike && x <= b.strike) {
      const pa = pick(a)!;
      const pb = pick(b)!;
      return pa + ((x - a.strike) / (b.strike - a.strike)) * (pb - pa);
    }
  }
  return null;
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
  const [strikesOpen, setStrikesOpen] = useState(false);
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
  const band = rows.filter((r) => r.ours >= 0.02 && r.ours <= 0.98);
  const shown = band.length >= 3 ? band : rows;
  const levelText = (v: number | null | undefined) => (v === null || v === undefined ? "outside the ladder" : `$${v.toFixed(2)}`);
  const gap = live.our_level != null && live.market_level != null ? live.our_level - live.market_level : null;
  const asOf = live.as_of ? new Date(live.as_of) : null;
  return (
    <section aria-label="Live next hour" className="rounded-xl border border-amber-500/40 bg-slate-900/70 p-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-rose-500/50 px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wider text-rose-300">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose-400" /> Live
        </span>
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

      <div className={`mt-4 grid gap-4 text-center ${live.itm ? "sm:grid-cols-4" : "sm:grid-cols-3"}`}>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Our 50% level</div>
          <div className="mt-1 text-4xl font-bold tabular-nums text-white">{levelText(live.our_level)}</div>
          <div className="mt-1 text-xs text-slate-500">the settle price we call a coin flip</div>
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Kalshi's 50% level</div>
          <div className="mt-1 text-4xl font-bold tabular-nums text-slate-200">{levelText(live.market_level)}</div>
          <div className="mt-1 text-xs text-slate-500">
            {gap === null ? "no clean crossing in the market ladder" : <>we sit <span className={gap >= 0 ? "text-amber-300" : "text-sky-300"}>{gap >= 0 ? "+" : "−"}${Math.abs(gap).toFixed(2)}</span> vs the market</>}
          </div>
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">WTI live</div>
          <div className="mt-1 text-4xl font-bold tabular-nums text-slate-100">${live.live_price?.toFixed(2)}</div>
          <div className="mt-1 text-xs text-slate-500">
            {live.price_age_minutes != null && live.price_age_minutes >= 2
              ? <>print {Math.round(live.price_age_minutes)} min old · the CL=F feed runs delayed</>
              : "the print our probabilities are priced off, right now"}
          </div>
        </div>
        {live.itm && (
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-emerald-400">In-the-money line</div>
            <div className="mt-1 text-4xl font-bold tabular-nums text-emerald-300">${live.itm.strike.toFixed(2)}</div>
            <div className="mt-1 text-xs text-slate-500">
              we say {(live.itm.ours * 100).toFixed(0)}% · Kalshi {(live.itm.market * 100).toFixed(0)}% (+{live.itm.gap_pts.toFixed(0)}) · clear of the tape {live.itm.clear_bars} min
            </div>
          </div>
        )}
      </div>

      {(() => {
        const pAbove = live.market_level != null ? probAbove(rows, live.market_level, (r) => r.ours) : null;
        if (pAbove === null || live.market_level == null) return null;
        const lean = pAbove > 0.53 ? "higher" : pAbove < 0.47 ? "lower" : "inline";
        return (
          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2.5">
            <span className={`text-2xl font-bold tabular-nums ${lean === "higher" ? "text-emerald-300" : lean === "lower" ? "text-rose-300" : "text-slate-200"}`}>
              {lean === "higher" ? "▲" : lean === "lower" ? "▼" : "◆"} {(pAbove * 100).toFixed(0)}%
            </span>
            <span className="text-sm text-slate-300">
              {lean === "higher" ? "we lean higher than Kalshi" : lean === "lower" ? "we lean lower than Kalshi" : "we sit in line with Kalshi"}
              {" "}— the chance the hour settles above Kalshi's 50% level (${live.market_level.toFixed(2)})
            </span>
          </div>
        );
      })()}
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
          <div>The <span className="font-semibold text-white">white line is the live WTI print</span>. The shaded band between the two coin-flip levels is the disagreement: our level to the right of Kalshi's means we lean higher, and the banner above puts a number on it.</div>
        </div>
      )}

      <button type="button" aria-expanded={strikesOpen} onClick={() => setStrikesOpen((v) => !v)}
              className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-slate-300 underline decoration-dotted underline-offset-4 hover:text-white">
        All strikes
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${strikesOpen ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {strikesOpen && (
      <table className="mt-2 w-full text-sm tabular-nums">
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
            const isLevel = live.our_level != null && Math.abs(r.strike - live.our_level) === Math.min(...shown.map((x) => Math.abs(x.strike - (live.our_level ?? 0))));
            const isItm = live.itm != null && r.strike === live.itm.strike;
            return (
              <tr key={r.strike} className={`border-t border-slate-800/60 ${isItm ? "bg-emerald-500/10" : isLevel ? "bg-slate-800/40" : ""}`}>
                <td className="py-1.5 font-mono text-white">
                  ${r.strike.toFixed(2)}
                  {isLevel && <span className="ml-2 text-[11px] font-semibold uppercase tracking-wide text-amber-300">our 50% level</span>}
                  {isItm && <span className="ml-2 text-[11px] font-semibold uppercase tracking-wide text-emerald-300">ITM line</span>}
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
      )}
      <p className="mt-3 text-[11px] text-slate-600">
        Recomputed every 30 seconds. Inside the last 20 minutes, this is already the next hour.
      </p>
    </section>
  );
}

function ItmRecordStrip() {
  const [rec, setRec] = useState<ItmRecord | null>(null);
  useEffect(() => {
    let stop = false;
    getJson<ItmRecord>("/api/oil/itm-record").then((r) => { if (!stop) setRec(r); }).catch(() => {});
    return () => { stop = true; };
  }, []);
  if (!rec || typeof rec.frozen !== "number" || rec.frozen === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2 text-[13px] text-slate-400">
      <span className="font-semibold text-emerald-300">ITM line record</span>
      <span>{rec.frozen} frozen · {rec.settled} settled</span>
      {rec.hit_rate !== null && <span>{rec.hits} hit ({(rec.hit_rate * 100).toFixed(0)}%)</span>}
      {rec.ev_per_dollar !== null && (
        <span>at Kalshi's price: <span className={rec.ev_per_dollar >= 0 ? "text-emerald-300" : "text-rose-300"}>
          {rec.ev_per_dollar >= 0 ? "+" : "−"}${Math.abs(rec.ev_per_dollar).toFixed(2)} per $1
        </span></span>
      )}
      <span className="text-slate-600">a calibration record — it never trades</span>
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
  const band = rows.filter((r) => r.ours >= 0.02 && r.ours <= 0.98);
  const shown = band.length >= 3 ? band : rows;
  const ourLevel = crossing(rows, (r) => r.ours);
  const marketLevel = crossing(rows, (r) => r.market);
  const frozenAt = new Date(Math.max(...group.map((f) => Date.parse(f.frozen_at))));
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
          <ItmRecordStrip />
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
    const hourly = data.forecasters.find((s) => s.forecaster === "oil_wti_hourly");
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
  const hourlyRows = viewRows(data.forecasters.filter((s) => OIL_HOURLY.has(s.forecaster)));
  const t = totals(rows);

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6 md:p-8">
      <header>
        <h1 className="text-3xl font-bold text-white">Commodities — WTI crude oil</h1>
        <p className="mt-2 text-slate-400">Live hourly oil, Hormuz, and the graded record.</p>
      </header>

      <LiveHero />

      {/* The frozen record hides behind a dropdown (Kevin, 2026-11-03): the
          live next-hour prediction is what the page leads with; the locked-in
          ladder and its grades open only on request. */}
      <FrozenRecord ours={ours} market={market} />

      <ChokepointsMap />

      <NextRelease family="oil" title="Next settlement" />

      <section aria-label="Totals" className="grid gap-3 sm:grid-cols-2">
        <Stat value={t.frozen} label="forecasts locked in" />
        <Stat value={t.scored} label="scored so far" />
      </section>

      {t.frozen === 0 && <p className="text-slate-400">Nothing locked in yet. The next one locks 2 hours before the settlement.</p>}

      <RecordSection title="Daily settlement" rows={rows} />
      <RecordSection title="Hourly settlements" rows={hourlyRows} />
    </div>
  );
}
