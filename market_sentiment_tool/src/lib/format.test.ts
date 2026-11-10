import { describe, expect, it } from "vitest";

import { ctDateTime, ctTime, ordinal, usd } from "@/lib/format";

describe("format", () => {
  it("renders instants in Chicago time with the CT suffix", () => {
    // 22:00 UTC is 4:00 PM CST (UTC-6) on Nov 1.
    expect(ctTime("2026-11-01T22:00:00Z")).toBe("4:00 PM CT");
    expect(ctDateTime("2026-11-01T22:00:00Z")).toBe("Sun, Nov 1, 4:00 PM CT");
  });

  it("formats money whole at ten dollars and up, cents below", () => {
    expect(usd(77844.4)).toBe("$77,844");
    expect(usd(2263.05)).toBe("$2,263");
    expect(usd(2.5)).toBe("$2.50");
    expect(usd(null)).toBe("—");
    expect(usd(undefined)).toBe("—");
  });
});

describe("ordinal", () => {
  it("renders English ordinals, teens included", () => {
    expect(ordinal(1)).toBe("1st");
    expect(ordinal(2)).toBe("2nd");
    expect(ordinal(3)).toBe("3rd");
    expect(ordinal(4)).toBe("4th");
    expect(ordinal(11)).toBe("11th");
    expect(ordinal(12)).toBe("12th");
    expect(ordinal(13)).toBe("13th");
    expect(ordinal(21)).toBe("21st");
    expect(ordinal(22)).toBe("22nd");
    expect(ordinal(23)).toBe("23rd");
    expect(ordinal(33)).toBe("33rd");
    expect(ordinal(111)).toBe("111th");
  });
});
