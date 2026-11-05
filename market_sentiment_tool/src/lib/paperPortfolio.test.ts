import { describe, expect, it } from "vitest";

import { dayMovers, fmtPct, fmtPts, fmtUsd, ideaScorecard, stateLabel, type PositionRow } from "@/lib/paperPortfolio";

describe("paper portfolio formatting", () => {
  it("shows unknown as a dash, never zero", () => {
    expect(fmtPct(null)).toBe("—");
    expect(fmtPts(undefined)).toBe("—");
    expect(fmtUsd(null)).toBe("—");
  });

  it("always signs percentages and points", () => {
    expect(fmtPct(2.72)).toBe("+2.7%");
    expect(fmtPct(-3.24)).toBe("−3.2%");
    expect(fmtPts(2.72)).toBe("+2.7 pts");
  });

  it("formats dollars", () => {
    expect(fmtUsd(104820, { whole: true })).toBe("$104,820");
    expect(fmtUsd(250, { signed: true })).toBe("+$250.00");
    expect(fmtUsd(-210, { signed: true })).toBe("−$210.00");
  });

  it("labels every state with its time", () => {
    expect(stateLabel("not_connected", null)).toBe("Paper account not connected");
    expect(stateLabel("live", "2026-11-10T20:41:00Z")).toBe("Paper account · live · as of 2:41 PM CT, Tue Nov 10");
    expect(stateLabel("pre_start", "2026-11-10T20:41:00Z")).toMatch(/^Paper account · not the account on record · as of /);
    expect(stateLabel("stale", "2026-11-10T20:41:00Z")).toMatch(/^Paper account · stale, last read /);
  });
});

describe("ideaScorecard", () => {
  const row = (symbol: string, idea: string | null, mv: number, cost: number, day: number) =>
    ({ symbol, idea, market_value: mv, cost_basis: cost, unrealized_pl: mv - cost, day_pl: day,
       qty: 1, side: "long", pct_of_book: null }) as PositionRow;

  it("sums each idea's holdings and says how far it sits from its target size", () => {
    const rows = [row("XLU", "Defensives", 5000, 4900, 20), row("XLV", "Defensives", 4000, 4100, -10),
                  row("IBIT", null, 6000, 6100, -300)];
    const card = ideaScorecard(rows, 100_000, [{ id: 38, title: "Defensives", size_pct: 10 }]);
    expect(card.find((c) => c.id === null)).toMatchObject({ idea: "IBIT (manual)", id: null, value: 6000, positions: 1, target_pct: null });
    const d = card.find((c) => c.idea === "Defensives")!;
    expect(d).toMatchObject({ id: 38, value: 9000, positions: 2, day_pl: 10, unrealized: 0, target_pct: 10 });
    expect(d.pct).toBeCloseTo(9);
    expect(d.return_pct).toBeCloseTo(0);
  });

  it("lists a live idea that holds nothing yet, at zero", () => {
    const card = ideaScorecard([], 100_000, [{ id: 17, title: "Gold", size_pct: 10 }]);
    expect(card).toEqual([expect.objectContaining({ idea: "Gold", value: 0, positions: 0, target_pct: 10 })]);
  });
});

describe("dayMovers", () => {
  it("returns the biggest gains and losses today, skipping flat rows", () => {
    const rows = [1, -5, 0, 3, -2].map((d, i) => ({ symbol: `S${i}`, day_pl: d, market_value: 1 }) as PositionRow);
    const { up, down } = dayMovers(rows, 2);
    expect(up.map((r) => r.symbol)).toEqual(["S3", "S0"]);
    expect(down.map((r) => r.symbol)).toEqual(["S1", "S4"]);
  });
});

describe("ideaScorecard on incomplete or short rows", () => {
  const base = { qty: 1, side: "long", pct_of_book: null } as const;

  it("reads a missing day or open P&L as unknown, never as zero", () => {
    const rows = [{ ...base, symbol: "A", idea: "X", market_value: 100, cost_basis: 90, unrealized_pl: 10, day_pl: 2 },
                  { ...base, symbol: "B", idea: "X", market_value: 100, cost_basis: 100, unrealized_pl: null, day_pl: null }] as PositionRow[];
    const [x] = ideaScorecard(rows, 1000, []);
    expect(x.day_pl).toBeNull();
    expect(x.unrealized).toBeNull();
    expect(x.return_pct).toBeNull();
  });

  it("sizes and returns a short on its gross exposure", () => {
    const rows = [{ ...base, symbol: "S", idea: "Short", side: "short", market_value: -500, cost_basis: -600, unrealized_pl: 100, day_pl: 5 }] as PositionRow[];
    const [s] = ideaScorecard(rows, 1000, []);
    expect(s.pct).toBeCloseTo(50);
    expect(s.return_pct).toBeCloseTo(100 / 600 * 100);
  });
});

describe("dayMovers when day P&L is unknown", () => {
  it("says the day is unknown rather than flat", () => {
    const rows = [{ symbol: "A", day_pl: null, market_value: 1 }] as PositionRow[];
    expect(dayMovers(rows).known).toBe(false);
    expect(dayMovers([{ symbol: "A", day_pl: 0, market_value: 1 } as PositionRow]).known).toBe(true);
  });
});
