import type { JournalScore } from "@/lib/journal";
import { viewRows } from "@/lib/journalView";
import { beatingCount, league } from "@/lib/league";
import type { ResultsSplit } from "@/lib/paperPortfolio";

/**
 * The landing page's headline numbers (2026-11-12 rework). Pure reads over three public payloads
 * (/api/journal, /api/oil/fifteen-rule, /api/portfolio/closed): no threshold of its own, and every
 * figure the server did not send comes back null so the page prints a dash, never a zero.
 */

const DASH = "—";

// --- Models beating their market -------------------------------------------------------------

export interface JournalLite {
  forecasters?: JournalScore[];
  headline?: { settled_calibrated?: number };
  /** Models the Nov 10 retirement stopped freezing, each counted once; null when the server could not read them. */
  retired_models?: number | null;
}

export interface ModelsBeating {
  beating: number;
  measured: number;
  /** null: unknown (an older server, or the registry would not load). */
  retired: number | null;
  scored: number | null;
}

/** Exactly the Model Tracker's headline count (Journal.tsx: beatingCount(league(viewRows(all)))), so the
 * two pages always agree: every predictor against its own baseline, the market price or climatology. */
export function modelsBeating(j: JournalLite | null | undefined): ModelsBeating | null {
  if (!j || !Array.isArray(j.forecasters)) return null;
  const scored = j.headline?.settled_calibrated;
  return {
    ...beatingCount(league(viewRows(j.forecasters))),
    retired: typeof j.retired_models === "number" ? j.retired_models : null,
    scored: typeof scored === "number" ? scored : null,
  };
}

// --- The 15-minute rules ---------------------------------------------------------------------

interface Stats { n: number; net_per_contract: number | null; total?: number; low95?: number | null }
interface Day { day: string; n: number; total: number }
interface Gate { forward?: Stats; by_series?: Record<string, Stats>; daily?: Record<string, Day[]> }
export interface FifteenLite { gate?: Gate; metals?: { gate?: Gate } }

export interface Interval { perTrade: number; low: number | null; high: number | null; n: number }

/** Gas's gated forward record with its 95% range (the server's mean ± 1.96 se, so high = 2·mean − low). */
export function gasRecord(f: FifteenLite | null | undefined): Interval | null {
  const s = f?.gate?.by_series?.["Natural gas"];
  if (!s || !s.n || s.net_per_contract == null) return null;
  const low = s.low95 ?? null;
  return { perTrade: s.net_per_contract, low, high: low == null ? null : 2 * s.net_per_contract - low, n: s.n };
}

export interface Span { from: string; to: string; perTrade: number; n: number }

/** Each span needs this many trades before the page calls the edge fading or holding. */
export const TREND_MIN_TRADES = 10;

export interface Trend { earlier: Span; recent: Span; verdict: "fading" | "holding" }

/** Gas per forward paper trade over its last `recentDays` days with trades against every day before them.
 * null (the page says nothing) unless both spans hold TREND_MIN_TRADES trades. */
export function gasTrend(f: FifteenLite | null | undefined, recentDays = 3): Trend | null {
  const days = (f?.gate?.daily?.["Natural gas"] ?? []).filter((d) => d.n > 0);
  if (days.length <= recentDays) return null;
  const span = (ds: Day[]): Span => {
    const n = ds.reduce((a, d) => a + d.n, 0);
    return { from: ds[0].day, to: ds[ds.length - 1].day, n, perTrade: ds.reduce((a, d) => a + d.total, 0) / n };
  };
  const earlier = span(days.slice(0, -recentDays));
  const recent = span(days.slice(-recentDays));
  if (earlier.n < TREND_MIN_TRADES || recent.n < TREND_MIN_TRADES) return null;
  return { earlier, recent, verdict: recent.perTrade < earlier.perTrade ? "fading" : "holding" };
}

/** Pooled per-trade net of several gated series (oil = WTI + Brent). null when none traded. */
function pooled(stats: (Stats | undefined)[]): number | null {
  const xs = stats.filter((s): s is Stats => !!s && s.n > 0 && typeof s.total === "number");
  const n = xs.reduce((a, s) => a + s.n, 0);
  return n ? xs.reduce((a, s) => a + (s.total as number), 0) / n : null;
}

export function oilPerTrade(f: FifteenLite | null | undefined): number | null {
  return pooled([f?.gate?.by_series?.WTI, f?.gate?.by_series?.Brent]);
}

export function metalsPerTrade(f: FifteenLite | null | undefined): number | null {
  const s = f?.metals?.gate?.forward;
  return s && s.n > 0 ? s.net_per_contract : null;
}

// --- Tested ideas against manual trades ------------------------------------------------------

export function testedVsManual(c: { results_split?: ResultsSplit } | null | undefined): ResultsSplit | null {
  const s = c?.results_split;
  return s && s.tested && s.discretionary ? s : null;
}

// --- Wording ---------------------------------------------------------------------------------

/** Dollars per contract as signed cents: 0.1233 -> "+12.3¢". */
export function cents(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  const c = v * 100;
  return `${c >= 0 ? "+" : "−"}${Math.abs(c).toFixed(1)}¢`;
}

/** "Nov 6" from "2026-11-06", read as a calendar day (no timezone shift). */
export function shortDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** "Nov 6–9", or "Nov 28–Dec 2" across a month. */
export function dayRange(from: string, to: string): string {
  const a = shortDay(from), b = shortDay(to);
  if (a === b) return a;
  return a.split(" ")[0] === b.split(" ")[0] ? `${a}–${b.split(" ")[1]}` : `${a}–${b}`;
}

/** Under half a cent a trade either way reads as flat, not as a win or a loss. */
export function tone(v: number | null): "up" | "down" | "flat" | "unknown" {
  if (v == null) return "unknown";
  return Math.abs(v) < 0.005 ? "flat" : v > 0 ? "up" : "down";
}

export function count(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? DASH : v.toLocaleString("en-US");
}
