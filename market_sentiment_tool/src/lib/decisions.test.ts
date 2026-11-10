import { describe, expect, it } from "vitest";

import { chipHeadline, chipJudgeText, type VerdictChip } from "@/lib/decisions";

const CHIP: VerdictChip = {
  ticker: "GILD", verdict_id: 7, rendered_at: "2026-11-10T06:00:00+00:00",
  judge: "free-ai-proposer", choice_id: "act_at_band_mid", direction: "long",
  confidence: 0.58, rationale: "guide supports it",
  dissent: "The price already pays for the guide.",
  snapshot_id: 3, fact_sheet_id: 103, trigger: "conjunction",
  zone: "buy_zone_strong",
};

describe("verdict chip text", () => {
  it("headlines the verdict, direction, and stated confidence", () => {
    expect(chipHeadline(CHIP)).toBe("Act at the mid band · long · 58% confidence");
  });

  it("says when the seat stated no confidence, rather than implying one", () => {
    expect(chipHeadline({ ...CHIP, confidence: null }))
      .toContain("no stated confidence");
  });

  it("never dresses the free seat as Jev — the Nov 18 state is stated", () => {
    const text = chipJudgeText(CHIP);
    expect(text).toContain("free AI (proposer)");
    expect(text).toContain("Nov 18");
  });

  it("names Jev plainly when the pinned seat actually rendered", () => {
    expect(chipJudgeText({ ...CHIP, judge: "jev:typesafe/jev-1.13" }))
      .toBe("Judge: Jev (typesafe/jev-1.13)");
  });
});
