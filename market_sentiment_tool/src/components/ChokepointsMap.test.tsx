import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import ChokepointsMap from "@/components/ChokepointsMap";

const VIEW = {
  region: "hormuz", name: "Strait of Hormuz", at: "2026-11-03T05:15:04+00:00",
  feeds: { ais: "live", adsb: "unknown" },
  metrics: [
    { feed: "ais", metric: "vessels_in_region", value: 2, health: "live", baseline: 1, delta_pct: 100.0, baseline_n: 28 },
    { feed: "ais", metric: "tankers_in_gate", value: 12, health: "live", baseline: 10, delta_pct: 20.0, baseline_n: 28 },
    { feed: "adsb", metric: "mil_total", value: 4, health: "live", baseline: 1, delta_pct: 300.0, baseline_n: 28 },
    { feed: "adsb", metric: "mil_tanker", value: 1, health: "live", baseline: 0, delta_pct: null, baseline_n: 28 },
    { feed: "adsb", metric: "mil_isr", value: 2, health: "live", baseline: 1, delta_pct: 100.0, baseline_n: 28 },
  ],
  vessels: [
    { mmsi: "111", name: "TANKER ONE", ship_type: 80, tanker: true, lat: 26.5, lon: 56.3,
      sog: 9, in_gate: true, last_seen: "2026-11-03T05:10:00+00:00" },
    { mmsi: "222", name: null, ship_type: 70, tanker: false, lat: 25.2, lon: 56.4,
      sog: 0.2, in_gate: false, last_seen: "2026-11-03T05:12:00+00:00" },
  ],
  vessels_as_of: "2026-11-03T05:12:00+00:00",
  aircraft: [
    { callsign: "RCH123", type: "K35R", kind: "tanker", lat: 26.9, lon: 55.8 },
  ],
  geometry: {
    bbox: [24.0, 50.5, 28.5, 59.5], gate: [26.1, 56.0, 26.8, 56.9],
    anchorages: { Fujairah: [25.10, 56.30, 25.25, 56.45] },
    terminals: { Fujairah: [25.10, 56.30, 25.25, 56.45] },
  },
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("ChokepointsMap", () => {
  it("renders tiles, feed health, layer chips and delta cards", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(VIEW), { status: 200 })));
    const { container } = render(<ChokepointsMap />);
    expect(await screen.findByText(/Strait of Hormuz/)).toBeInTheDocument();
    expect(screen.getByText(/Ships \(AIS\): live/)).toBeInTheDocument();
    expect(screen.getByText(/Military flights: unknown/)).toBeInTheDocument();
    expect(container.querySelectorAll("img").length).toBeGreaterThanOrEqual(12);
    expect(screen.getByText("Tankers in the gate")).toBeInTheDocument();
    expect(screen.getByText(/\+20% vs median 10/)).toBeInTheDocument();
    expect(container.querySelector('[title="Transit gate"]')).not.toBeNull();
    // Ships and aircraft are plotted as big markers, not text (Kevin, 2026-11-03)
    expect(container.querySelector('[aria-label*="TANKER ONE"]')).not.toBeNull();
    expect(container.querySelector('[aria-label*="RCH123"]')).not.toBeNull();
    expect(screen.getByRole("button", { name: /ships \(2\)/ })).toBeInTheDocument();
    expect(screen.getByText("Vessels tracked")).toBeInTheDocument();
    expect(screen.getByText(/Tankers 1 · ISR 2/)).toBeInTheDocument();
    // the ships layer toggles the markers off
    fireEvent.click(screen.getByRole("button", { name: /ships \(2\)/ }));
    expect(container.querySelector('[aria-label*="TANKER ONE"]')).toBeNull();
    // terminals layer is off by default; toggling shows its boxes
    fireEvent.click(screen.getByRole("button", { name: "terminals" }));
    expect(container.querySelectorAll('[title="Fujairah"]').length).toBe(2);
  });

  it("renders nothing when the read API is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));
    const { container } = render(<ChokepointsMap />);
    await new Promise((r) => setTimeout(r, 30));
    expect(container.firstChild).toBeNull();
  });
});
