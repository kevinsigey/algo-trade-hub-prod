import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

import { fmtFund } from "@/pages/Valuation";

/** Round 4, Item 4 (F5 discipline): every number on the fundamentals line
 * carries its unit -- a bare "Diluted EPS 1.02" fails this. The EDGAR
 * concepts behind the line are USD per share (EarningsPerShareDiluted)
 * and a share count (WeightedAverageNumberOfDilutedSharesOutstanding). */
describe("fmtFund unit labels", () => {
  it("labels diluted EPS as dollars per share", () => {
    expect(fmtFund("eps_diluted", 1.02)).toBe("$1.02 per share");
  });

  it("labels diluted shares as a share count", () => {
    expect(fmtFund("shares_diluted", 532_400_000)).toBe("532.4M shares");
  });

  it("keeps the currency label on money fields", () => {
    expect(fmtFund("cash", 9_129_000_000)).toBe("$9.13B");
    expect(fmtFund("revenue", 412_000_000)).toBe("$412.0M");
  });
});
