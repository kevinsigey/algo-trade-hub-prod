import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Weather from "@/pages/Weather";
import type { WeatherTodayRow, WeatherSettledRow } from "@/lib/weather";

const baseTodayRow = {
  strike_type: null as string | null,
  floor_strike: null as number | null,
  cap_strike: null as number | null,
  yes_sub_title: null as string | null,
  no_sub_title: null as string | null,
};

const TODAY: WeatherTodayRow[] = [
  { target: "kalshi:KXRAIN-26OCT18-NYC", date: "26OCT18", ensemble: 0.65, kalshi: 0.6, climatology: 0.55, ...baseTodayRow },
  { target: "kalshi:KXRAIN-26OCT18-LAX", date: "26OCT18", ensemble: 0.45, kalshi: 0.5, climatology: 0.52, ...baseTodayRow },
];

const SETTLED: WeatherSettledRow[] = [
  {
    target: "kalshi:KXRAIN-26OCT17-NYC",
    date: "26OCT17",
    ensemble: 0.7,
    kalshi: 0.72,
    climatology: 0.6,
    outcome: 1,
    realized_value: null,
    settled_at: "2026-10-18T00:00:00+00:00",
    ...baseTodayRow,
  },
];

function mockWeather(today: WeatherTodayRow[], settled: WeatherSettledRow[]) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => ({ as_of: "2026-10-18T12:00:00+00:00", today, settled }),
  });
}

const renderWeather = () =>
  render(
    <MemoryRouter>
      <Weather />
    </MemoryRouter>,
  );

describe("weather page", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows the city grid with all three probabilities", async () => {
    vi.stubGlobal("fetch", mockWeather(TODAY, SETTLED));
    renderWeather();
    await waitFor(() =>
      expect(screen.getByText(/ens 65%/)).toBeTruthy()
    );
    expect(screen.getByText(/kalshi 60%/)).toBeTruthy();
    expect(screen.getByText(/clim 55%/)).toBeTruthy();
    // Both cities appear with parsed labels (the rain series names the city)
    expect(screen.getAllByText("NYC rain").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Los Angeles rain").length).toBeGreaterThan(0);
  });

  it("says the pick against climatology in plain words and shows the ensemble record", async () => {
    const journal = {
      as_of: "2026-11-01",
      forecasters: [
        { forecaster: "weather_rain", forecaster_version: "ens-v2.1", brier: 0.141, brier_on_baseline: 0.163, n_baseline: 77, brier_baseline: 0.098, n_settled: 412 },
        { forecaster: "weather_rain", forecaster_version: "ens-v1", brier: 0.187, brier_baseline: 0.093, n_settled: 900 },
        { forecaster: "baseline_climatology_weather_rain", forecaster_version: "v1", brier: 0.210, brier_baseline: null, n_settled: 412 },
      ],
      headline: {},
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes("/api/journal")
        ? journal
        : { as_of: "2026-10-18T12:00:00+00:00", today: TODAY, settled: SETTLED };
      return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => body };
    }));
    renderWeather();
    expect(await screen.findByText(/Our pick leans yes — the ensemble gives it 65%, climatology 55%/)).toBeTruthy();
    expect(screen.getByText(/Our pick leans no — the ensemble gives it 45%, climatology 52%/)).toBeTruthy();
    expect(await screen.findByText(/Ensemble record — settled contracts/)).toBeTruthy();
    expect(screen.getByText("0.163")).toBeTruthy(); // the matched score, not 0.141 over every strike
    expect(screen.queryByText("0.141")).toBeNull();
    expect(screen.getByText("77")).toBeTruthy(); // the matched count
  });

  it("shows settled history with outcome", async () => {
    vi.stubGlobal("fetch", mockWeather(TODAY, SETTLED));
    renderWeather();
    await waitFor(() => expect(screen.getByText("YES")).toBeTruthy());
  });

  it("renders dashes for missing probabilities", async () => {
    const incomplete: WeatherTodayRow[] = [
      { target: "kalshi:KXRAIN-26OCT18-NYC", date: "26OCT18", ensemble: null, kalshi: 0.6, climatology: null, ...baseTodayRow },
    ];
    vi.stubGlobal("fetch", mockWeather(incomplete, []));
    renderWeather();
    await waitFor(() => expect(screen.getByText(/ens —/)).toBeTruthy());
    expect(screen.getByText(/clim —/)).toBeTruthy();
  });

  it("shows empty state when no data", async () => {
    vi.stubGlobal("fetch", mockWeather([], []));
    renderWeather();
    await waitFor(() => expect(screen.getByText(/no rain data/i)).toBeTruthy());
  });

  it("reports an error when the API fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        headers: { get: () => "text/html" },
        json: async () => ({}),
      }),
    );
    renderWeather();
    await waitFor(() => expect(screen.getByText(/status 503/)).toBeTruthy());
  });
});
