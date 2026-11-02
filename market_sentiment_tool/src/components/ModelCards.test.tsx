import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ModelCards } from "@/components/ModelCards";
import type { JournalScore, SeriesEntry } from "@/lib/journal";
import { viewRows } from "@/lib/journalView";
import { league } from "@/lib/league";

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "spy_quant", forecaster_version: "spy-wf-v1", cadence: "daily", baseline: "market",
    n_targets: 240, n_settled: 210, brier: 0.19, brier_baseline: 0.211, bss: 0.08,
    gap: -0.021, gap_se: 0.008,
    reliability: [], murphy: {}, calibration_ready: true,
    gate_status: "SHADOW", gate_reasons: ["needs a longer settled record"], computed_at: "2026-10-01T13:00:00+00:00",
    ...over,
  };
}

const scores: JournalScore[] = [
  score(),
  score({ forecaster: "sentiment_meter", forecaster_version: "meter-v1", brier: 0.24, brier_baseline: 0.228, bss: -0.05, gap: 0.012, gap_se: 0.004, n_settled: 180, n_targets: 190 }),
  score({ forecaster: "sentiment_meter", forecaster_version: "meter-v0", brier: 0.25, brier_baseline: 0.23, bss: -0.06, gap: 0.014, gap_se: 0.005, n_settled: 90, n_targets: 95 }),
  score({ forecaster: "cpi_nowcast", forecaster_version: "cpi-v1", cadence: "monthly", baseline: "none", n_targets: 3, n_settled: 0, brier: null, brier_baseline: null, bss: null, gap: null, gap_se: null, gate_reasons: [] }),
];

const series: SeriesEntry[] = [
  {
    forecaster: "spy_quant", version: "spy-wf-v1",
    points: [
      { date: "2026-09-28", gap: -0.01, se: 0.004, n: 10 },
      { date: "2026-09-29", gap: -0.02, se: 0.004, n: 11 },
      { date: "2026-09-30", gap: -0.021, se: 0.008, n: 12 },
    ],
  },
];

describe("ModelCards", () => {
  it("renders one card per predictor with its headline edge and status", () => {
    render(<ModelCards rows={league(viewRows(scores))} series={series} />);
    expect(screen.getAllByRole("article")).toHaveLength(4);
    expect(screen.getByText("+0.021")).toBeInTheDocument();
    expect(screen.getByText("Beating the baseline")).toBeInTheDocument();
    expect(screen.getByText("−0.012")).toBeInTheDocument();
    expect(screen.getAllByText("Behind").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Scored 210 \/ 200 needed/)).toBeInTheDocument();
    expect(screen.getByText(/Brier 0.190 vs 0.211/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Edge trend/ })).toBeInTheDocument();
  });

  it("shows a waiting predictor as a muted explanation, not a score", () => {
    render(<ModelCards rows={league(viewRows(scores))} series={series} />);
    expect(screen.getByText("Waiting for results")).toBeInTheDocument();
    expect(screen.getByText(/3 forecasts locked in\. Scoring starts with the first settlement\./)).toBeInTheDocument();
  });

  it("opens the record behind a click: variants and gate reasons", () => {
    render(<ModelCards rows={league(viewRows(scores))} series={series} />);
    const buttons = screen.getAllByRole("button", { name: "Details" });
    fireEvent.click(buttons[0]);
    expect(screen.getByText("needs a longer settled record")).toBeInTheDocument();
  });

  it("says so when nothing is tracked", () => {
    render(<ModelCards rows={[]} series={[]} />);
    expect(screen.getByText("No predictors tracked yet.")).toBeInTheDocument();
  });
});
