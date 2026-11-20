import { describe, expect, it } from "vitest";

import { multipleText, type FactSheet } from "./valuation";

const sheet = (over: Partial<FactSheet>) => ({ peer_multiple: 20, band_basis: "eps", ...over }) as FactSheet;

describe("multipleText", () => {
  it("labels the own/peer blend as a blended P/E, not a forward one (#569)", () => {
    const text = multipleText(sheet({ multiple_basis: "blend", own_multiple: 30 }));
    expect(text).toBe("25.00× blended P/E (50/50 own 30.00 / peer 20.00)");
    expect(text).not.toContain("fwd");
  });

  it("keeps fwd P/E for the peer-only multiple", () => {
    expect(multipleText(sheet({ multiple_basis: "peer_only" }))).toBe("20.00× fwd P/E (peer only)");
  });
});
