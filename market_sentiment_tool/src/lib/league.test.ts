import { describe, expect, it } from "vitest";
import { axisSpan, beatingCount, byGroup, edgeOf, edgeText, groupOf, league, statusOf } from "@/lib/league";
import { viewRows } from "@/lib/journalView";
import type { JournalScore } from "@/lib/journal";

function score(over: Partial<JournalScore>): JournalScore {
  return {
    forecaster: "sports_nfl", forecaster_version: "v1", cadence: "daily", baseline: "market", n_targets: 120,
    n_settled: 100, brier: 0.2, brier_baseline: 0.22, bss: 0.09, reliability: [], murphy: {}, calibration_ready: true,
    gate_status: "SHADOW", gate_reasons: [], computed_at: "x", gap: -0.02, gap_se: 0.005, ...over,
  } as JournalScore;
}

describe("league: one sign convention", () => {
  it("turns the server's negative-is-better gap into a positive edge", () => {
    expect(edgeOf({ gap: -0.02 })).toBeCloseTo(0.02);
    expect(edgeOf({ gap: 0.03 })).toBeCloseTo(-0.03);
    expect(edgeOf({ gap: null })).toBeNull();
  });
  it("agrees in sign with Brier skill for every row (positive skill, positive edge)", () => {
    const rows = league(viewRows([score({}), score({ forecaster: "sports_cfb", gap: 0.04, bss: -0.1 })]));
    for (const r of rows) {
      const skill = r.primary.score.bss as number;
      expect(Math.sign(r.edge as number)).toBe(Math.sign(skill));
    }
  });
  it("prints a signed three-place edge with its 95% half-width", () => {
    expect(edgeText(0.0212, 0.008)).toBe("+0.021 ± 0.016");
    expect(edgeText(-0.05, null)).toBe("−0.050");
    expect(edgeText(null, null)).toBe("—");
  });
});

describe("league: verdicts", () => {
  it("says beating or behind only when the whole interval is on one side of zero", () => {
    expect(statusOf(0.03, 0.005, 100)).toBe("beating");
    expect(statusOf(-0.03, 0.005, 100)).toBe("behind");
    expect(statusOf(0.01, 0.01, 100)).toBe("level");
    expect(statusOf(0.03, 0.005, 10)).toBe("early");
    expect(statusOf(null, null, 100)).toBe("early");
    expect(statusOf(0.03, 0.005, 0)).toBe("waiting");
  });
  it("counts only measured verdicts", () => {
    const rows = league(viewRows([score({}), score({ forecaster: "sports_cfb", n_settled: 5 })]));
    expect(beatingCount(rows)).toEqual({ beating: 1, measured: 1 });
  });
});

describe("league: grouping and variants", () => {
  it("collapses a model and its cautious copy into one predictor row, most evidence first", () => {
    const rows = league(viewRows([
      score({ forecaster: "sports_cfb_total", n_settled: 40 }),
      score({ forecaster: "sports_cfb_total_cautious", n_settled: 90 }),
    ]));
    expect(rows).toHaveLength(1);
    expect(rows[0].primary.forecaster).toBe("sports_cfb_total_cautious");
    expect(rows[0].variants.map((v) => v.forecaster)).toEqual(["sports_cfb_total"]);
  });
  it("never lists the Kalshi mid or a naive baseline as a predictor", () => {
    const rows = league(viewRows([score({}), score({ forecaster: "kalshi_implied_sports_nfl" }), score({ forecaster: "baseline_persistence_gas", baseline: "none" })]));
    expect(rows.map((r) => r.id)).toEqual(["sports_nfl@v1"]);
  });
  it("keeps a different version of the same forecaster as its own predictor", () => {
    const rows = league(viewRows([
      score({ forecaster: "cpi_nowcast", forecaster_version: "cpi-v1" }),
      score({ forecaster: "cpi_nowcast", forecaster_version: "cpi-core-v1" }),
    ]));
    expect(rows.map((r) => r.label).sort()).toEqual(["Core inflation (CPI)", "Inflation (CPI)"]);
  });
  it("groups sports, macro and weather & energy", () => {
    expect(groupOf("sports_nfl_spread")).toBe("sports");
    expect(groupOf("weather_rain_cal")).toBe("weather");
    expect(groupOf("gas")).toBe("weather");
    expect(groupOf("cpi_nowcast")).toBe("macro");
  });
  it("always lists the sports the journal does not score yet, under Sports", () => {
    const g = byGroup(league(viewRows([score({})])));
    expect(g[0].group.id).toBe("sports");
  });
  it("sizes one axis for every interval", () => {
    expect(axisSpan(league(viewRows([score({ gap: -0.071, gap_se: 0.01 })])))).toBe(0.1);
  });
});
