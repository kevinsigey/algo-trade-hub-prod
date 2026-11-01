import { describe, expect, it } from "vitest";

import { ctDateTime, ctTime, usd } from "@/lib/format";

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
