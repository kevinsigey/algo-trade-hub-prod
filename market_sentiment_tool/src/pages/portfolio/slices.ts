import { sectorColor } from "@/components/CompositionMap";
import type { PositionRow } from "@/lib/paperPortfolio";

/** One slice of the Positions donut: how the book divides by thesis. */
export type Slice = { key: string; label: string; tag?: string; pct: number; value: number; color: string };

const IDEA_COLORS = ["#34d399", "#38bdf8", "#a78bfa", "#f472b6", "#fb923c", "#2dd4bf"];
const BROAD = new Set(["Other", "Broad Market"]);
/** A core sector that is this much of the book, and is only "Other"/"Broad Market", splits by symbol. */
const SPLIT_OVER_PCT = 10;

/** "Core/active structure - untouched core (T13)" -> the thing, plus its "(T13)" suffix as a tag. */
function shorten(idea: string): { label: string; tag?: string } {
  const m = /^(.*?)\s*\(([^)]*)\)\s*$/.exec(idea);
  return m && m[1] ? { label: m[1], tag: m[2] } : { label: idea };
}

/**
 * The book by thesis: one slice per idea, cash on its own, no-idea holdings as
 * "Unassigned". The core idea is most of the book, so it splits by sector
 * ("Core · Utilities"), and a core sector that is just "Other" or "Broad Market"
 * and over 10% splits again by symbol ("Core · SGOV"). Shares are of gross market
 * value (shorts count by size) so the donut always sums to 100.
 */
export function slices(positions: PositionRow[]): Slice[] {
  const total = positions.reduce((a, p) => a + Math.abs(p.market_value), 0);
  if (total <= 0) return [];
  const isCore = (p: PositionRow) => p.symbol !== "Cash" && /^core\b/i.test(p.idea ?? "");
  const sectorOf = (p: PositionRow) => p.sector ?? "Other";
  const coreSector = new Map<string, number>();
  for (const p of positions.filter(isCore)) {
    coreSector.set(sectorOf(p), (coreSector.get(sectorOf(p)) ?? 0) + Math.abs(p.market_value));
  }
  const out = new Map<string, Slice>();
  for (const p of positions) {
    const value = Math.abs(p.market_value);
    let s: Omit<Slice, "pct" | "value">;
    if (p.symbol === "Cash") s = { key: "cash", label: "Cash", color: sectorColor("Cash") };
    else if (!p.idea) s = { key: "unassigned", label: "Unassigned", color: "#64748b" };
    else if (isCore(p)) {
      const sector = sectorOf(p);
      const bySymbol = BROAD.has(sector) && ((coreSector.get(sector) ?? 0) / total) * 100 > SPLIT_OVER_PCT;
      const name = bySymbol ? p.symbol : sector;
      s = { key: `core-${name}`, label: `Core · ${name}`, tag: shorten(p.idea).tag, color: sectorColor(sector) };
    } else {
      const { label, tag } = shorten(p.idea);
      s = { key: `idea-${p.idea}`, label, tag, color: "" };
    }
    const have = out.get(s.key);
    if (have) have.value += value;
    else out.set(s.key, { ...s, value, pct: 0 });
  }
  let next = 0;
  return [...out.values()]
    .map((s) => ({ ...s, pct: (s.value / total) * 100 }))
    .sort((a, b) => b.value - a.value)
    .map((s) => (s.color ? s : { ...s, color: IDEA_COLORS[next++ % IDEA_COLORS.length] }));
}

/** The legend: every thesis that is not core always shows (small ones too), the biggest
 * core parts fill the rest of `n` rows, and the leftover small core parts fold into
 * "Core · other (N)". */
export function legendSlices(all: Slice[], n = 10): Slice[] {
  const isCore = (s: Slice) => s.key.startsWith("core-");
  const fold = (parts: Slice[], key: string, label: string): Slice[] =>
    parts.length > 1 ? [{ key, label: `${label} (${parts.length})`, color: "#475569",
      pct: parts.reduce((a, s) => a + s.pct, 0), value: parts.reduce((a, s) => a + s.value, 0) }] : parts;
  // Every thesis of 1% or more keeps its row; slivers share one, so core parts get the room.
  const other = all.filter((s) => !isCore(s));
  const big = other.filter((s) => s.pct >= 1);
  const tiny = fold(other.filter((s) => s.pct < 1), "theses-other", "Other theses");
  const core = all.filter(isCore).sort((a, b) => b.pct - a.pct);
  const room = Math.max(0, n - big.length - tiny.length);
  const coreShown = core.length > room ? core.slice(0, Math.max(0, room - 1)) : core;
  const coreRest = fold(core.slice(coreShown.length), "core-other", "Core · other");
  return [...coreShown, ...big, ...coreRest, ...tiny];
}
