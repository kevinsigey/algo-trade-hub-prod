import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Weather from "@/pages/Weather";

const MAP = {
  cities: [
    {
      sid: "NYC", name: "New York", lat: 40.779, lon: -73.969,
      high: { day: "2026-11-01", mean: 72.4, version: "ens-v1", buckets: [
        { label: "72 to 73 degrees", ours: 0.42, market: 0.38, clim: 0.2 },
      ] },
      low: null, rain: null,
      record: { n: 40, brier_ours: 0.19, brier_market: 0.11 },
    },
    {
      sid: "ORD", name: "Chicago", lat: 41.974, lon: -87.907,
      high: null, low: null,
      rain: { day: "2026-11-01", mean: null, version: "ens-v1", buckets: [
        { label: "Rain", ours: 0.35, market: 0.3, clim: null },
      ] },
      record: null,
    },
  ],
};

function stubFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/api/weather/map") ? MAP
      : url.includes("/api/weather/degree-days") ? { detail: "not built" }
      : { as_of: "2026-11-01T00:00:00Z", today: [], settled: [] };
    return { ok: !url.includes("degree-days"), status: url.includes("degree-days") ? 503 : 200,
      headers: { get: () => "application/json" }, json: async () => body };
  });
}

describe("Weather map (phase-3 §3.1)", () => {
  beforeEach(() => { vi.stubGlobal("fetch", stubFetch()); });

  it("plots a marker per city with its headline and opens the city card", async () => {
    render(<MemoryRouter><Weather /></MemoryRouter>);
    expect(await screen.findByText("72°")).toBeTruthy();           // NYC marker headline (ensemble mean)
    expect(screen.getByText("35% rain")).toBeTruthy();             // Chicago marker headline
    expect(await screen.findByText("72 to 73 degrees")).toBeTruthy(); // default card = first city
    expect(screen.getByText(/ensemble ens-v1/)).toBeTruthy();      // the model is named on the card
    expect(screen.getByText(/Brier ours 0.190 vs Kalshi 0.110/)).toBeTruthy();
    fireEvent.click(screen.getByText("35% rain"));
    expect(await screen.findByText(/No settled record at this station yet/)).toBeTruthy();
  });
});
