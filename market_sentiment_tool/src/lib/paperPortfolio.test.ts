import { describe, expect, it } from "vitest";

import { aggregateToRow, betaToSpy, curveTradingDays, dailyReturns, dayMovers, drawdownSeries, fmtPct, fmtPts, fmtUsd, ideaScorecard, isTestedTrade, MANUAL_IDEA, maxDrawdown, orderDetailLabel, orderLabel, pnlByIdea, pnlBySector, realizedByWeek, splitOverTime, stateLabel, tradeStats, tradesInRange, volatilityPct, type ClosedTrade, type PositionRow, type TodaySplit } from "@/lib/paperPortfolio";

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

describe("curve trading days and order labels (2026-11-12 fixes)", () => {
  it("counts distinct days in the curve, not snapshots", () => {
    const curve = [
      ...Array.from({ length: 40 }, (_, i) => ({ t: `2026-11-10T${String(14 + Math.floor(i / 10))}:0${i % 10}:00Z`, portfolio_pct: 0, spy_pct: 0 })),
      ...Array.from({ length: 25 }, (_, i) => ({ t: `2026-11-11T15:0${i % 10}:00Z`, portfolio_pct: 0, spy_pct: 0 })),
    ];
    expect(curveTradingDays(curve)).toBe(2);
    expect(curveTradingDays([])).toBe(0);
  });

  it("maps an aggregate line into the row shape the tables read", () => {
    const row = aggregateToRow({
      symbol: "GLD", asset: "stock", qty: 52, market_value: 19000, pct_of_equity: 19,
      pct_of_book: 19, avg_entry: 355, tags: [], sector: "Commodities (Gold)", side: "long",
      last_price: 365.4, change_pct: -0.84, day_pl: -88, cost_basis: 18460, unrealized_pl: 540,
    });
    expect(row).toMatchObject({ symbol: "GLD", qty: 52, avg_price: 355, pct_of_book: 19,
                                day_pl: -88, idea: null, sector: "Commodities (Gold)" });
  });

  it("counts weekdays only, so a weekend live point can't advance the Sharpe guard", () => {
    // Fri Nov 6, Sat Nov 7, Sun Nov 8, Mon Nov 9 2026: four calendar
    // days on the curve, but only two trading days.
    const curve = ["2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09"]
      .map((d) => ({ t: `${d}T15:00:00Z`, portfolio_pct: 0, spy_pct: 0 }));
    expect(curveTradingDays(curve)).toBe(2);
  });

  it("names each leg's side and quantity in the full orders table label", () => {
    const base = { side: "buy", qty: 1, filled_qty: 1, type: "limit", time_in_force: "day",
                   status: "filled", limit_price: 0.31, stop_price: null, filled_avg_price: 0.31,
                   submitted_at: null, filled_at: null, asset: "option" as const, source: "Machine order" };
    const spread = { ...base, symbol: null as unknown as string, legs: [
      { symbol: "SPY261111P00750000", side: "buy_to_open", ratio_qty: 1, qty: 1, filled_qty: 1 },
      { symbol: "SPY261111P00749000", side: "sell_to_open", ratio_qty: 1, qty: 1, filled_qty: 1 },
    ] };
    expect(orderDetailLabel(spread)).toBe(
      "buy 1 SPY Nov 11 2026 $750 put / sell 1 SPY Nov 11 2026 $749 put");
    // The reverse spread must read differently: sides ride with the legs.
    const reversed = { ...spread, legs: [
      { symbol: "SPY261111P00750000", side: "sell_to_close", ratio_qty: 1, qty: 1, filled_qty: 1 },
      { symbol: "SPY261111P00749000", side: "buy_to_close", ratio_qty: 1, qty: 1, filled_qty: 1 },
    ] };
    expect(orderDetailLabel(reversed)).toBe(
      "sell 1 SPY Nov 11 2026 $750 put / buy 1 SPY Nov 11 2026 $749 put");
    expect(orderDetailLabel(reversed)).not.toBe(orderDetailLabel(spread));
    // A plain order's detail label is its symbol label, unchanged.
    expect(orderDetailLabel({ ...base, symbol: "GLD" })).toBe("GLD");
  });

  it("names a multi-leg order by its legs and a plain order by its symbol", () => {
    const base = { side: "buy", qty: 1, filled_qty: 1, type: "limit", time_in_force: "day",
                   status: "filled", limit_price: 0.31, stop_price: null, filled_avg_price: 0.31,
                   submitted_at: null, filled_at: null, asset: "option" as const, source: "Machine order" };
    expect(orderLabel({ ...base, symbol: "GLD" })).toBe("GLD");
    expect(orderLabel({ ...base, symbol: null as unknown as string, legs: [
      { symbol: "SPY261111P00750000", side: "buy_to_open", ratio_qty: 1, qty: 1, filled_qty: 1 },
      { symbol: "SPY261111P00749000", side: "sell_to_open", ratio_qty: 1, qty: 1, filled_qty: 1 },
    ] })).toBe("SPY Nov 11 2026 $750 put / SPY Nov 11 2026 $749 put");
  });
});

describe("performance derivations (2026-11-12 redesign PR 2)", () => {
  const pt = (t: string, portfolio_pct: number, spy_pct: number) => ({ t, portfolio_pct, spy_pct });
  // Curve points at 15:00Z (10:00 ET) and 20:00Z (15:00 ET); the day's last
  // point is its close. Mon Nov 9 close +1.0/+0.5, Tue Nov 10 close 0/0,
  // Wed Nov 11 close +2.02/+1.0.
  const curve = [
    pt("2026-11-09T15:00:00Z", 0.2, 0.1), pt("2026-11-09T20:00:00Z", 1.0, 0.5),
    pt("2026-11-10T20:00:00Z", 0.0, 0.0),
    pt("2026-11-11T20:00:00Z", 2.02, 1.0),
  ];

  it("differences each trading day's close against the previous close", () => {
    const daily = dailyReturns(curve, null, new Date("2026-11-12T15:00:00Z"));
    expect(daily.map((d) => d.date)).toEqual(["2026-11-10", "2026-11-11"]);
    expect(daily[0].portfolio_pct).toBeCloseTo(-0.9901, 3);
    expect(daily[0].spy_pct).toBeCloseTo(-0.4975, 3);
    expect(daily[1].portfolio_pct).toBeCloseTo(2.02, 6);
    expect(daily[1].spy_pct).toBeCloseTo(1.0, 6);
    expect(daily.every((d) => !d.provisional)).toBe(true);
  });

  it("skips weekend points instead of inventing weekend trading days", () => {
    const withWeekend = [
      pt("2026-11-13T20:00:00Z", 1.0, 0.5), // Fri close
      pt("2026-11-14T20:00:00Z", 9.0, 9.0), // Sat live point: not a trading day
      pt("2026-11-16T20:00:00Z", 2.0, 1.0), // Mon close, differenced off Friday
    ];
    const daily = dailyReturns(withWeekend, null, new Date("2026-11-16T21:00:00Z"));
    expect(daily).toHaveLength(1);
    expect(daily[0].date).toBe("2026-11-16");
    expect(daily[0].portfolio_pct).toBeCloseTo(0.9901, 3);
  });

  it("marks today provisional and, after the close, reads the split's regular-session figures", () => {
    const withToday = [...curve, pt("2026-11-12T20:30:00Z", 3.03, 1.7)];
    const now = new Date("2026-11-12T20:30:00Z");
    const regular = dailyReturns(withToday, null, now);
    expect(regular[regular.length - 1].date).toBe("2026-11-12");
    expect(regular[regular.length - 1].provisional).toBe(true);
    // Pre-close, the provisional day is the live point differenced: +0.99%.
    expect(regular[regular.length - 1].portfolio_pct).toBeCloseTo(0.9901, 3);

    const split: TodaySplit = {
      state: "after_hours", prior_close_at: null, close_at: "2026-11-12T21:05:00Z",
      regular_pl: 150, regular_pct: 1.5, after_hours_pl: 30, after_hours_pct: 0.3,
      spy_regular_pct: 0.7, spy_after_hours_pct: 0.1,
    };
    const afterHours = dailyReturns(withToday, split, now);
    const last = afterHours[afterHours.length - 1];
    // The live point carries after-hours moves; the day's close figures win.
    expect(last.portfolio_pct).toBe(1.5);
    expect(last.spy_pct).toBe(0.7);
    expect(last.provisional).toBe(true);
  });

  it("builds the drawdown series and finds its bottom", () => {
    const points = [0, 2, 1, 3, -1].map((v, i) => pt(`2026-11-0${i + 1}T20:00:00Z`, v, 0));
    expect(drawdownSeries(points).map((d) => d.dd_pct)).toEqual([0, 0, -1, 0, -4]);
    expect(maxDrawdown(points)).toEqual({ pct: -4, at: "2026-11-05T20:00:00Z" });
    expect(maxDrawdown([])).toEqual({ pct: null, at: null });
  });

  it("computes volatility and beta from daily returns", () => {
    const daily = [1, -1, 1, -1].map((p, i) => ({
      date: `2026-11-0${i + 1}`, portfolio_pct: p, spy_pct: p / 2, provisional: false,
    }));
    expect(betaToSpy(daily)).toBeCloseTo(2.0, 6); // the portfolio moves exactly twice SPY
    expect(volatilityPct(daily)).toBeCloseTo(18.33, 1);
    expect(volatilityPct(daily.slice(0, 1))).toBeNull();
    expect(betaToSpy([{ date: "2026-11-01", portfolio_pct: 1, spy_pct: null, provisional: false }])).toBeNull();
  });

  const trade = (over: Partial<ClosedTrade>): ClosedTrade => ({
    symbol: "GLD", sector: "Commodities (Gold)", qty: 10, entry_price: 100, exit_price: 110,
    entered_at: "2026-11-02T15:00:00Z", exited_at: "2026-11-10T20:00:00Z",
    pnl: 100, return_pct: 10, held_days: 2, idea: "Idea One", ...over,
  });
  const trades = [
    trade({ pnl: 100, held_days: 2, exited_at: "2026-11-10T20:00:00Z", idea: "Idea One", sector: "Technology", symbol: "NVDA" }),
    trade({ pnl: -50, held_days: 4, exited_at: "2026-11-12T20:00:00Z", idea: MANUAL_IDEA, sector: "Energy", symbol: "XLE" }),
    trade({ pnl: 300, held_days: 6, exited_at: "2026-11-17T20:00:00Z", idea: "Idea One", sector: "Technology", symbol: "NVDA" }),
    trade({ pnl: -50, held_days: 8, exited_at: "2026-11-17T21:00:00Z", idea: MANUAL_IDEA, sector: "Energy", symbol: "XLE" }),
  ];

  it("splits tested from discretionary by the backend's own rule", () => {
    expect(isTestedTrade(trades[0])).toBe(true);
    expect(isTestedTrade(trades[1])).toBe(false);
    expect(isTestedTrade(trade({ idea: "" }))).toBe(false);
  });

  it("summarizes closed trades: win rate, average win and loss, profit factor, holding time", () => {
    const s = tradeStats(trades);
    expect(s).toEqual({
      trades: 4, win_rate: 50, avg_win: 200, avg_loss: -50, profit_factor: 4, avg_held_days: 5,
    });
    expect(tradeStats([]).win_rate).toBeNull();
  });

  it("filters trades to the curve ranges the same way the curve slices", () => {
    const now = new Date("2026-11-18T12:00:00Z");
    expect(tradesInRange(trades, "All", now)).toHaveLength(4);
    expect(tradesInRange(trades, "1W", now).map((t) => t.pnl)).toEqual([-50, 300, -50]);
    expect(tradesInRange(trades, "YTD", now)).toHaveLength(4);
  });

  it("merges realized and open P&L by idea and by sector", () => {
    const byIdea = pnlByIdea(trades, [
      { idea: "Idea One", unrealized_pl: 40 }, { idea: MANUAL_IDEA, unrealized_pl: -10 },
    ]);
    expect(byIdea).toEqual([
      { key: "Idea One", realized: 400, open: 40, total: 440 },
      { key: MANUAL_IDEA, realized: -100, open: -10, total: -110 },
    ]);
    const rows: PositionRow[] = [
      { symbol: "GLD", sector: "Commodities (Gold)", qty: 1, side: "long", market_value: 100, pct_of_book: 1, unrealized_pl: 25, idea: null },
      { symbol: "XLE", sector: "Energy", qty: 1, side: "long", market_value: 100, pct_of_book: 1, unrealized_pl: -30, idea: null },
    ];
    expect(pnlBySector(trades, rows)).toEqual([
      { key: "Technology", realized: 400, open: 0, total: 400 },
      { key: "Energy", realized: -100, open: -30, total: -130 },
      { key: "Commodities (Gold)", realized: 0, open: 25, total: 25 },
    ]);
  });

  it("accumulates the tested-vs-discretionary split in exit order", () => {
    expect(splitOverTime([trades[2], trades[0], trades[1]])).toEqual([
      { t: "2026-11-10T20:00:00Z", tested: 100, discretionary: 0 },
      { t: "2026-11-12T20:00:00Z", tested: 100, discretionary: -50 },
      { t: "2026-11-17T20:00:00Z", tested: 400, discretionary: -50 },
    ]);
  });

  it("buckets realized P&L by ET week, Monday first", () => {
    expect(realizedByWeek(trades)).toEqual([
      { week: "2026-11-09", pnl: 50, trades: 2 },
      { week: "2026-11-16", pnl: 250, trades: 2 },
    ]);
  });
});
