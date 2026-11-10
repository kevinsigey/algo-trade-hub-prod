import { describe, expect, it } from "vitest";

import {
  consensusPeriodText, gapText, guideDirection, guideText, humanizeGroup, metricLabel, num,
  summarize, zoneInfo, type FactSheet,
} from "@/lib/valuation";

const sheet = (over: Partial<FactSheet>): FactSheet => ({
  ticker: "AMGN", tier: "watch", status: "banded", band_basis: "eps",
  price: 460.42, price_as_of: "2026-11-06", peer_group: "biotechnology",
  peer_multiple: 16.49, peer_count: 7, peer_basis: "industry_group",
  anchor: { metric: "eps_gaap", period: "full year 2026", period_key: "FY2026",
    low: 18.34, high: 19.28, mid: 18.81, point_guide: false, consensus: null,
    recorded_at: "2026-11-03T21:05:44+00:00", accession: "0000318154-26-000153" },
  bands: { bear: 272.18, base: 310.17, bull: 317.92 },
  implied_eps: 27.92, implied_revenue: null, gap_range_widths: 9.69,
  guidance_percentile: null, baseline_verdict: "short_zone_strong",
  stale: false, falsifier: "Falsified if ...", directions: {
    eps_gaap: { period: "full year 2026", mid: 18.81, prev_mid: 16.36,
      direction: "raised", recorded_at: "2026-11-03T21:05:44+00:00" },
  },
  fundamentals: {}, inputs: { guidance_records: [] },
  computed_at: "2026-11-09T18:00:00Z",
  ...over,
});

describe("num", () => {
  it("parses PostgREST numeric strings and passes numbers through", () => {
    expect(num("16.49")).toBe(16.49);
    expect(num(460.42)).toBe(460.42);
    expect(num(null)).toBeNull();
    expect(num(undefined)).toBeNull();
    expect(num("n/a")).toBeNull();
  });
});

describe("zoneInfo", () => {
  it("labels every verdict in plain words", () => {
    expect(zoneInfo("buy_zone_strong").label).toBe("Strong buy zone");
    expect(zoneInfo("buy_zone").label).toBe("Buy zone");
    expect(zoneInfo("neutral").label).toBe("Neutral");
    expect(zoneInfo("short_zone").label).toBe("Short zone");
    expect(zoneInfo("short_zone_strong").label).toBe("Strong short zone");
    expect(zoneInfo("no_chase_long").label).toBe("No-chase");
    expect(zoneInfo("stale").label).toMatch(/stale/i);
    expect(zoneInfo("no_bands").label).toBe("No bands");
    expect(zoneInfo(null).label).toBe("—");
  });

  it("tones buy zones positive and short zones negative", () => {
    expect(zoneInfo("buy_zone").tone).toBe("buy");
    expect(zoneInfo("buy_zone_strong").tone).toBe("buy");
    expect(zoneInfo("short_zone").tone).toBe("short");
    expect(zoneInfo("short_zone_strong").tone).toBe("short");
    expect(zoneInfo("neutral").tone).toBe("flat");
  });
});

describe("summarize", () => {
  it("counts banded by basis, zones, stale and unbanded from the sheets", () => {
    const sheets = [
      sheet({}),
      sheet({ ticker: "CVS", baseline_verdict: "buy_zone" }),
      sheet({ ticker: "SBUX", baseline_verdict: "neutral" }),
      sheet({ ticker: "LLY", band_basis: "revenue", baseline_verdict: "short_zone_strong",
        anchor: { metric: "revenue", period: "full year 2026", period_key: "FY2026",
          low: 91e9, high: 92e9, mid: 91.5e9, point_guide: false, consensus: null,
          recorded_at: null, accession: null } }),
      sheet({ ticker: "OLD", baseline_verdict: "stale", stale: true }),
      sheet({ ticker: "KO", status: "guide_rejected", baseline_verdict: "no_bands",
        bands: null, anchor: null }),
      sheet({ ticker: "AAPL", status: "no_full_year_guide", baseline_verdict: "no_bands",
        bands: null, anchor: null }),
    ];
    const s = summarize(sheets);
    expect(s.total).toBe(7);
    expect(s.banded).toBe(5);
    expect(s.epsBanded).toBe(4);
    expect(s.revenueBanded).toBe(1);
    expect(s.buyZones).toBe(1);       // CVS only; the stale sheet's zone is held
    expect(s.shortZones).toBe(2);     // AMGN + LLY
    expect(s.flatZones).toBe(1);      // SBUX neutral
    expect(s.stale).toBe(1);
    expect(s.unbanded).toBe(2);
    expect(s.guideRejected).toBe(1);
    expect(s.noFullYearGuide).toBe(1);
  });
});

describe("guideText", () => {
  it("renders an EPS range guide with its period", () => {
    expect(guideText(sheet({}))).toBe("FY2026 EPS 18.34–19.28");
  });

  it("renders a point guide as a single figure", () => {
    const s = sheet({ anchor: { metric: "eps_adjusted", period: "full year 2026",
      period_key: "FY2026", low: 8.2, high: 8.2, mid: 8.2, point_guide: true,
      consensus: null, recorded_at: null, accession: null } });
    expect(guideText(s)).toBe("FY2026 EPS 8.20 (point guide)");
  });

  it("renders a revenue guide in billions", () => {
    const s = sheet({ band_basis: "revenue", anchor: { metric: "revenue",
      period: "full year 2026", period_key: "FY2026", low: 31.0e9, high: 31.3e9,
      mid: 31.15e9, point_guide: false, consensus: null, recorded_at: null,
      accession: null } });
    expect(guideText(s)).toBe("FY2026 revenue $31.00–31.30B");
  });

  it("is a dash when there is no anchor", () => {
    expect(guideText(sheet({ anchor: null }))).toBe("—");
  });
});

describe("guideDirection", () => {
  it("reads the anchor metric's direction off the directions block", () => {
    expect(guideDirection(sheet({}))).toBe("raised");
  });

  it("returns null when the anchor metric has no direction entry", () => {
    expect(guideDirection(sheet({ directions: {} }))).toBeNull();
    expect(guideDirection(sheet({ anchor: null }))).toBeNull();
  });
});

describe("labels", () => {
  it("humanizes frozen peer-group slugs", () => {
    expect(humanizeGroup("biotechnology")).toBe("Biotechnology");
    expect(humanizeGroup("health_care_services")).toBe("Health Care Services");
    expect(humanizeGroup("sector:Health Care")).toBe("Health Care (whole sector)");
    expect(humanizeGroup(null)).toBe("—");
  });

  it("labels guide metrics", () => {
    expect(metricLabel("eps_gaap")).toBe("EPS (GAAP)");
    expect(metricLabel("eps_adjusted")).toBe("EPS (adjusted)");
    expect(metricLabel("revenue")).toBe("revenue");
  });

  it("renders the gap in guide-range widths", () => {
    expect(gapText(9.69)).toBe("+9.7 guide widths");
    expect(gapText(-10.32)).toBe("−10.3 guide widths");
    expect(gapText(0)).toBe("0.0 guide widths");
    expect(gapText(null)).toBe("—");
  });
});

describe("consensusPeriodText", () => {
  it("humanizes the yfinance relative period tags", () => {
    expect(consensusPeriodText("0y")).toBe("current year");
    expect(consensusPeriodText("+1y")).toBe("next year");
    expect(consensusPeriodText("0q")).toBe("current quarter");
    expect(consensusPeriodText("+1q")).toBe("next quarter");
  });

  it("passes an unknown tag through rather than hiding it", () => {
    expect(consensusPeriodText("+2y")).toBe("+2y");
    expect(consensusPeriodText(null)).toBeNull();
    expect(consensusPeriodText(undefined)).toBeNull();
  });
});
