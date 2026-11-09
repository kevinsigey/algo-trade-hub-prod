import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { FifteenSettlements } from "@/components/FifteenSettlements";

function score(over: Record<string, unknown>) {
  return {
    forecaster: "oil_wti_15m", forecaster_version: "wti-15m-v2", cadence: "15min", baseline: "kalshi",
    n_targets: 1422, n_settled: 969, brier: 0.0975, brier_baseline: 0.2396, brier_on_baseline: 0.0975,
    n_baseline: 918, bss: null, gap: -0.1421, gap_se: 0.0059, reliability: [], murphy: {},
    calibration_ready: true, gate_status: "PROMOTED", gate_reasons: [], computed_at: "2026-11-09T16:00:00Z",
    ...over,
  };
}

function serve(forecasters: unknown[]) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(
    JSON.stringify({ as_of: "2026-11-09T16:00:00Z", forecasters, headline: {} }), { status: 200 })));
}

afterEach(() => vi.unstubAllGlobals());

describe("FifteenSettlements", () => {
  it("charts each 15-minute market's model Brier against the market's, with settled counts", async () => {
    serve([
      score({}),
      score({ forecaster: "oil_brent_15m", forecaster_version: "brent-15m-v2", n_settled: 1022,
              brier: 0.1187, brier_on_baseline: 0.1187, brier_baseline: 0.2431, n_baseline: 865, gap: -0.1243 }),
      score({ forecaster: "natgas_15m", forecaster_version: "natgas-15m-v2", n_settled: 1035,
              brier: 0.124, brier_on_baseline: 0.124, brier_baseline: 0.2511, n_baseline: 913, gap: -0.1271 }),
      score({ forecaster: "oil_wti_hourly", forecaster_version: "wti-hourly-v9", cadence: "hourly" }),
    ]);
    render(<FifteenSettlements />);
    const chart = within(await screen.findByLabelText("15-minute settlements scoring"));
    expect(chart.getByText("WTI")).toBeInTheDocument();
    expect(chart.getByText("Brent")).toBeInTheDocument();
    expect(chart.getByText("Natural gas")).toBeInTheDocument();
    expect(chart.getByText(/969 settled/)).toBeInTheDocument();
    expect(chart.getByText("0.098")).toBeInTheDocument();   // WTI model Brier
    expect(chart.getByText("0.240")).toBeInTheDocument();   // WTI market Brier
    expect(chart.getByText("0.251")).toBeInTheDocument();   // natgas market Brier
    expect(chart.getAllByText(/model ahead/)).toHaveLength(3);
    expect(chart.getByText(/lower is better/)).toBeInTheDocument();
    expect(chart.queryByText(/hourly/)).not.toBeInTheDocument();
  });

  it("renders nothing on an empty journal rather than an empty chart", async () => {
    serve([]);
    const { container } = render(<FifteenSettlements />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });
});
