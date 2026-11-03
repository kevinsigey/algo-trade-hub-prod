import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import ChokepointsMap from "@/components/ChokepointsMap";

const VIEW = {
  region: "hormuz", name: "Strait of Hormuz", at: "2026-11-03T05:15:04+00:00",
  feeds: { ais: "live", adsb: "unknown" },
  metrics: [
    { feed: "ais", metric: "tankers_in_gate", value: 12, health: "live", baseline: 10, delta_pct: 20.0, baseline_n: 28 },
    { feed: "adsb", metric: "mil_total", value: 4, health: "live", baseline: 1, delta_pct: 300.0, baseline_n: 28 },
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
