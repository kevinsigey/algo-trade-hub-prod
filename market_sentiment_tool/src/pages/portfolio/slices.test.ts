import { describe, expect, it } from "vitest";

import type { PositionRow } from "@/lib/paperPortfolio";
import { legendSlices, slices } from "./slices";

const CORE = "Core/active structure - untouched core (T13)";
const row = (symbol: string, market_value: number, idea: string | null, sector: string | null = null): PositionRow =>
  ({ symbol, sector, qty: 1, side: "long", market_value, pct_of_book: null, unrealized_pl: null, idea });

describe("slices", () => {
  it("splits core by sector, keeps the T13 suffix as a tag, and gives cash its own slice", () => {
    const out = slices([
      row("XLU", 400, CORE, "Utilities"), row("VPU", 100, CORE, "Utilities"), row("BND", 200, CORE, "Bonds"),
      row("NVDA", 200, "AI winners", "Technology"), row("Cash", 100, null),
    ]);
    expect(out.map((s) => [s.label, s.pct])).toEqual([
      ["Core · Utilities", 50], ["Core · Bonds", 20], ["AI winners", 20], ["Cash", 10],
    ]);
    expect(out[0].tag).toBe("T13");
    expect(out.reduce((a, s) => a + s.pct, 0)).toBeCloseTo(100);
  });

  it("splits a big Other / Broad Market core sector by symbol, but not a small one", () => {
    const big = slices([row("SGOV", 300, CORE, "Other"), row("XLU", 700, CORE, "Utilities")]);
    expect(big.map((s) => s.label)).toEqual(["Core · Utilities", "Core · SGOV"]);
    // Broad Market is exactly 10% here: not over 10, so it stays a sector slice.
    const small = slices([row("SPY", 100, CORE, "Broad Market"), row("XLU", 900, CORE, "Utilities")]);
    expect(small.map((s) => s.label)).toEqual(["Core · Utilities", "Core · Broad Market"]);
  });

  it("reads a holding with no idea as Unassigned, merges slices of one idea, and sums to nothing when empty", () => {
    const out = slices([row("A", 100, "Thesis X (T1)", "Energy"), row("B", 100, "Thesis X (T1)", "Energy"), row("C", 50, null, "Energy")]);
    expect(out.map((s) => [s.label, s.tag, s.value])).toEqual([["Thesis X", "T1", 200], ["Unassigned", undefined, 50]]);
    expect(slices([])).toEqual([]);
  });

  it("legendSlices always lists non-core theses, fills with the biggest core parts, and folds the rest", () => {
    const core = Array.from({ length: 10 }, (_, i) => row(`C${i}`, 1000 - i * 10, CORE, `Sector ${i}`));
    const small = [row("E", 1, "Event Lab (T2)", "Energy"), row("U", 1, null), row("Cash", 1, null)];
    const legend = legendSlices(slices([...core, ...small]));
    const labels = legend.map((s) => s.label);
    expect(legend).toHaveLength(8);
    expect(labels).toEqual(expect.arrayContaining(["Event Lab", "Unassigned", "Cash", "Core · Sector 0", "Core · Sector 3"]));
    expect(labels).not.toContain("Core · Sector 4");
    const other = legend.find((s) => s.label === "Core · other (6)");
    expect(other?.pct).toBeCloseTo(slices([...core, ...small]).filter((s) => /Sector [4-9]/.test(s.label)).reduce((a, s) => a + s.pct, 0));
    // Few slices: nothing folds.
    expect(legendSlices(slices(core.slice(0, 3)))).toHaveLength(3);
  });
});

describe("curveSince", () => {
  it("starts at the prior close, rebases every line to 0%, and keeps only later points", async () => {
    const { curveSince } = await import("@/lib/paperPortfolio");
    const c = [
      { t: "2026-11-24T21:00:00Z", portfolio_pct: 1, spy_pct: 2, qqq_pct: 3 },
      { t: "2026-11-25T15:00:00Z", portfolio_pct: 1.5, spy_pct: 2.5, qqq_pct: null },
      { t: "2026-11-25T17:21:00Z", portfolio_pct: 0.5, spy_pct: 2, qqq_pct: 3 },
    ];
    const out = curveSince(c, "2026-11-24T21:00:00Z");
    expect(out).toHaveLength(3);
    expect(out[0].portfolio_pct).toBeCloseTo(0);
    expect(out[2].portfolio_pct).toBeCloseTo(((1.005 / 1.01) - 1) * 100);
    expect(curveSince(c, "2026-11-25T17:21:00Z")).toHaveLength(1);
    expect(curveSince(c, null)).toEqual([]);
  });
});
