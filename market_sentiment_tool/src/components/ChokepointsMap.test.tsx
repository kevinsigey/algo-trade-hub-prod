import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

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

  it("shows the PortWatch flow strip with its lag stated", async () => {
    const withFlow = { ...VIEW, flow: {
      source: "IMF PortWatch", name: "Strait of Hormuz", as_of: "2026-10-26", lag_days: 8,
      n_tanker_latest: 21, n_total_latest: 55, capacity_tanker_latest: 900000,
      n_tanker_7d: 19.5, n_total_7d: 51, capacity_tanker_7d: 850000,
      tanker_baseline_30d: 26, tanker_delta_pct: -25.0, baseline_n: 30,
      recent: Array.from({ length: 14 }, (_, i) => ({
        date: `2026-10-${13 + i}`, n_tanker: 15 + i, n_total: 40 + i })),
    } };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(withFlow), { status: 200 })));
    render(<ChokepointsMap />);
    expect(await screen.findByText(/Ship flow · IMF PortWatch/)).toBeInTheDocument();
    expect(screen.getByText(/Tankers 19.5\/day/)).toBeInTheDocument();
    expect(screen.getByText(/vs 26 baseline/)).toBeInTheDocument();
    expect(screen.getByText(/Latest day 2026-10-26: 21 tankers · 55 ships/)).toBeInTheDocument();
    expect(screen.getByText(/8-day lag/)).toBeInTheDocument();
    expect(screen.getByText(/a floor, not a total/)).toBeInTheDocument();
  });

  it("renders nothing when the read API is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));
    const { container } = render(<ChokepointsMap />);
    await new Promise((r) => setTimeout(r, 30));
    expect(container.firstChild).toBeNull();
  });

  it("explains each metric and says not visible live instead of a false 0", async () => {
    const blind = { ...VIEW, vessels: [
      { mmsi: "1", name: null, ship_type: null, tanker: false, lat: 25, lon: 55, sog: 0, in_gate: false, last_seen: "2026-11-03T10:00:00Z" },
    ], metrics: [
      { feed: "ais", metric: "tankers_in_gate", value: 0, baseline: null, delta_pct: null, health: "live" },
      { feed: "adsb", metric: "mil_total", value: 4, baseline: 2, delta_pct: 100, health: "live" },
    ] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(blind), { status: 200 })));
    render(<ChokepointsMap />);
    expect(await screen.findByText("Barrels moving")).toBeInTheDocument();
    expect(screen.getByText("Not visible live")).toBeInTheDocument();
    expect(screen.queryByText("See the satellite count below")).not.toBeInTheDocument();
    expect(screen.getByText(/Above normal\./)).toBeInTheDocument();
    expect(screen.getByText(/Oil's range widens/)).toBeInTheDocument();
    expect(screen.getByText("In the oil model's test")).toBeInTheDocument();
  });

  it("masks only the gate cards when the region is seen but the gate is blind", async () => {
    // The Nov 14 2026 live picture: 18 vessels off Dubai, 10 typed, none of
    // them tankers and none in the gate. Region counts are real observations
    // and show; gate counts are unobserved and mask -- per zone, not global.
    const vessels = Array.from({ length: 18 }, (_, i) => ({
      mmsi: `${100 + i}`, name: null, ship_type: i < 10 ? 70 : null, tanker: false,
      lat: 25.0 + i * 0.01, lon: 55.05, sog: 2, in_gate: false,
      last_seen: "2026-11-14T21:29:00Z",
    }));
    const view = { ...VIEW, vessels, metrics: [
      { feed: "ais", metric: "vessels_in_region", value: 18, health: "live", baseline: 17, delta_pct: 5.9, baseline_n: 28 },
      { feed: "ais", metric: "tankers_in_region", value: 0, health: "live", baseline: 1, delta_pct: -100.0, baseline_n: 28 },
      { feed: "ais", metric: "anchored_tankers", value: 0, health: "live", baseline: 2, delta_pct: -100.0, baseline_n: 28 },
      { feed: "ais", metric: "tankers_in_gate", value: 0, health: "live", baseline: 1, delta_pct: -100.0, baseline_n: 28 },
      { feed: "ais", metric: "tankers_gate_entries_1h", value: 0, health: "live", baseline: 1, delta_pct: -100.0, baseline_n: 28 },
    ] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(view), { status: 200 })));
    render(<ChokepointsMap />);
    expect(await screen.findByText("Barrels moving")).toBeInTheDocument();
    // Exactly the two gate cards mask; the two region cards show their
    // zeros. Asserted per card, scoped with `within`: a bare count of "0"
    // texts cannot say which cards masked.
    const card = (label: string) => {
      const el = screen.getByText(label).closest(".rounded-lg");
      if (!el) throw new Error(`no card rendered for ${label}`);
      return within(el as HTMLElement);
    };
    for (const label of ["Tankers in the gate", "Gate entries (1h)"]) {
      expect(card(label).getByText("Not visible live")).toBeInTheDocument();
      expect(card(label).queryByText("0")).not.toBeInTheDocument();
    }
    for (const label of ["Tankers in region", "Anchored tankers"]) {
      expect(card(label).getByText("0")).toBeInTheDocument();
      expect(card(label).queryByText("Not visible live")).not.toBeInTheDocument();
    }
    expect(screen.getByText(/Ship coverage is thin/)).toBeInTheDocument();
  });

  it("trusts the stored coverage metrics over the capped vessel list", async () => {
    // The read API caps the vessel list (250, tankers first), so the list
    // alone can look gate-visible when the strait is actually dark. Here
    // the two listed vessels say covered (both typed, one in the gate),
    // but the snapshot's exact counts say 300 seen and none in the gate:
    // the gate is blind, its card masks, and the banner quotes the exact
    // counts rather than the biased list's.
    const view = { ...VIEW, metrics: [
      { feed: "ais", metric: "vessels_in_region", value: 300, health: "live", baseline: 17, delta_pct: null, baseline_n: 28 },
      { feed: "ais", metric: "vessels_typed", value: 290, health: "live", baseline: null, delta_pct: null, baseline_n: 28 },
      { feed: "ais", metric: "vessels_in_gate", value: 0, health: "live", baseline: null, delta_pct: null, baseline_n: 28 },
      { feed: "ais", metric: "tankers_in_gate", value: 7, health: "live", baseline: 10, delta_pct: -30.0, baseline_n: 28 },
      { feed: "ais", metric: "tankers_in_region", value: 3, health: "live", baseline: 1, delta_pct: 200.0, baseline_n: 28 },
    ] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(view), { status: 200 })));
    render(<ChokepointsMap />);
    expect(await screen.findByText("Barrels moving")).toBeInTheDocument();
    const gateCard = screen.getByText("Tankers in the gate").closest(".rounded-lg");
    if (!gateCard) throw new Error("no gate card rendered");
    expect(within(gateCard as HTMLElement).getByText("Not visible live")).toBeInTheDocument();
    expect(within(gateCard as HTMLElement).queryByText("7")).not.toBeInTheDocument();
    expect(screen.getByText(/300 ships seen, 0 in the transit gate, 290 with a known type/))
      .toBeInTheDocument();
  });

  it("renders the UKMTO incidents panel with source and dates, newest first", async () => {
    const withIncidents = { ...VIEW, incidents: {
      source: "UKMTO", source_url: "https://www.ukmto.org/recent-incidents",
      pulled_at: "2026-11-14T12:23:00+00:00", as_of: "2026-11-11", count: 2,
      incidents: [
        { ref: "UKMTO 204-26", date: "2026-11-11", occurred_at: "2026-11-11T18:00:00Z",
          type: "Attack", place: "Arabian Gulf", lat: 25.9, lon: 55.9, vessel_type: "Tanker",
          description: "A tanker was struck by an unknown projectile in the engine room.",
          url: "https://www.ukmto.org/recent-incidents" },
        { ref: "UKMTO 198-26", date: "2026-11-07", occurred_at: "2026-11-07T06:30:00Z",
          type: "Advisory", place: "Gulf of Oman", lat: 24.6, lon: 58.6, vessel_type: "Bulk Carrier",
          description: "An incident involving a vessel and military forces east of Khor Fakkan.",
          url: "https://www.ukmto.org/recent-incidents" },
      ],
    } };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(withIncidents), { status: 200 })));
    render(<ChokepointsMap />);
    expect(await screen.findByText(/Reported incidents · UKMTO/)).toBeInTheDocument();
    expect(screen.getByText(/Latest 2026-11-11 · 2 in the region/)).toBeInTheDocument();
    expect(screen.getByText(/UKMTO 204-26/)).toBeInTheDocument();
    expect(screen.getByText(/struck by an unknown projectile/)).toBeInTheDocument();
    expect(screen.getByText(/a floor, not a total/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /UKMTO Recent Incidents/ }))
      .toHaveAttribute("href", "https://www.ukmto.org/recent-incidents");
    // Each story carries its time: occurred_at is served as a UTC instant
    // and rendered on the reader's clock (Kevin, 2026-11-16), with the UTC
    // original in the title. The bare served date no longer leads the line.
    const stamp = new Date("2026-11-11T18:00:00Z")
      .toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    const meta = screen.getByTitle(/2026-11-11T18:00:00Z as served \(UTC\)/);
    expect(meta.textContent).toContain(stamp);
    expect(meta.textContent).toContain("UKMTO 204-26");
    expect(screen.queryByText(/2026-11-11 · UKMTO 204-26/)).toBeNull();
    // The panel sits beside the map (same grid wrapper), not under it.
    const panel = screen.getByLabelText("Reported incidents, UKMTO");
    expect(panel.parentElement?.className).toContain("lg:grid-cols");
    expect(panel.parentElement?.firstElementChild).not.toBe(panel);
  });

  it("orders the metric groups with Barrels moving last", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(VIEW), { status: 200 })));
    render(<ChokepointsMap />);
    const barrels = await screen.findByText("Barrels moving");
    const background = screen.getByText("Background");
    const risk = screen.getByText("Chance of trouble");
    // DOCUMENT_POSITION_FOLLOWING on the earlier node: barrels comes after both.
    expect(background.compareDocumentPosition(barrels) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(risk.compareDocumentPosition(barrels) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows collapsed traffic banner when year-ago delta <= -50", async () => {
    const collapsed = {
      ...VIEW,
      vessels: [
        { mmsi: "1", name: null, ship_type: null, tanker: false, lat: 25, lon: 55, sog: 0, in_gate: false, last_seen: "2026-11-03T10:00:00Z" },
      ],
      flow: {
        source: "IMF PortWatch", name: "Strait of Hormuz", as_of: "2026-10-26", lag_days: 8,
        n_tanker_latest: 1, n_total_latest: 5, capacity_tanker_latest: 900000,
        n_tanker_7d: 1.0, n_total_7d: 5, capacity_tanker_7d: 850000,
        tanker_baseline_30d: 26, tanker_delta_pct: -96.0, baseline_n: 30,
        tanker_year_ago: 40.0, tanker_year_ago_delta_pct: -97.5,
        recent: Array.from({ length: 14 }, (_, i) => ({
          date: `2026-10-${13 + i}`, n_tanker: 15 + i, n_total: 40 + i })),
      },
      metrics: [
        { feed: "ais", metric: "tankers_in_gate", value: 0, baseline: null, delta_pct: null, health: "live" },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(collapsed), { status: 200 })));
    render(<ChokepointsMap />);
    expect(await screen.findByText(/The free live feed sees/)).toBeInTheDocument();
    expect(screen.getByText(/collapsed/)).toBeInTheDocument();
    expect(screen.getByText(/1 tankers a day against 40 a year ago/)).toBeInTheDocument();
    // Should NOT show the old "Zero tankers here means..." text
    expect(screen.queryByText(/Zero tankers here means/)).not.toBeInTheDocument();
  });
});
