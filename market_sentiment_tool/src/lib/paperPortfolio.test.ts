import { describe, expect, it } from "vitest";

import { fmtPct, fmtPts, fmtUsd, stateLabel } from "@/lib/paperPortfolio";

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
    expect(stateLabel("not_connected", null)).toBe("Account not connected");
    expect(stateLabel("live", "2026-11-10T20:41:00Z")).toBe("Live · as of 2:41 PM CT, Tue Nov 10");
    expect(stateLabel("pre_start", "2026-11-10T20:41:00Z")).toMatch(/^Pre-start test account · as of /);
    expect(stateLabel("stale", "2026-11-10T20:41:00Z")).toMatch(/^Stale · last read /);
  });
});
