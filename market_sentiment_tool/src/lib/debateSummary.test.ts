import { describe, expect, it } from "vitest";

import {
  cleanText,
  extractSummary,
  formatPrice,
  parsePriceLevels,
  parseTraderAction,
  previewLine,
  trimToSentences,
} from "@/lib/debateSummary";

// Fixtures shaped like the stored GOOGL run (2026-11-02): `**Label**: value`
// fields run together, exactly as the importer's excerpts store them.
const TRADER =
  "**Action**: Sell **Reasoning**: Both the technical report and research plan align on a bearish outlook. " +
  "The technical analysis shows a structural breakdown on October 29 with gap down on 5x average volume, price below all major moving averages. " +
  "**Entry Price**: 295.0 **Stop Loss**: 315.0 **Position Sizing**: Reduce existing long exposure by 30-50% of standard allocation. " +
  "FINAL TRANSACTION PROPOSAL: **SELL**";

const RISK =
  "**Rating**: Underweight **Executive Summary**: Trim existing GOOGL exposure by 30–50% of standard allocation; " +
  "sell rallies toward $290–300 (lower Bollinger Band to 10 EMA resistance) with tight stops above $315. " +
  "Implement defined-risk put spreads (e.g., Dec/Jan 270/260) for downside protection and theta decay. " +
  "Hold residual position at 1–2% of portfolio with a 2×ATR trailing stop near $258.50. " +
  "**Investment Thesis**: The October 29 gap down on 5× average volume confirmed institutional distribution. " +
  "**Price Target**: not provided **Time Horizon**: not provided";

describe("cleanText / previewLine", () => {
  it("strips markdown noise and the excerpt cut marker", () => {
    expect(cleanText("[…] ## 🎪 **Sentiment Check** - **StockTwits: 70% unlabeled** — retail is confused.")).toBe(
      "🎪 Sentiment Check - StockTwits: 70% unlabeled — retail is confused.",
    );
  });

  it("cuts a preview on a word boundary at ~110 chars", () => {
    const line = previewLine("word ".repeat(60));
    expect(line.length).toBeLessThanOrEqual(111);
    expect(line.endsWith("…")).toBe(true);
    expect(line).not.toContain("  ");
  });

  it("leaves short text whole", () => {
    expect(previewLine("**Rating**: Underweight")).toBe("Rating: Underweight");
  });
});

describe("trimToSentences", () => {
  it("ends on a sentence boundary inside the window", () => {
    const text = "First sentence is here. " + "Second one follows it closely behind. " + "x".repeat(300);
    const out = trimToSentences(text, 80);
    expect(out.endsWith(".")).toBe(true);
    expect(out.length).toBeLessThanOrEqual(80);
  });

  it("falls back to a word-boundary cut with an ellipsis", () => {
    const out = trimToSentences("alpha beta gamma delta ".repeat(30), 60);
    expect(out.endsWith("…")).toBe(true);
    expect(out.length).toBeLessThanOrEqual(61);
  });
});

describe("extractSummary", () => {
  it("prefers the risk panel's Executive Summary, without the Rating prefix", () => {
    const summary = extractSummary(RISK, TRADER);
    expect(summary).not.toBeNull();
    expect(summary!.startsWith("Trim existing GOOGL exposure")).toBe(true);
    expect(summary).not.toContain("Rating");
    expect(summary!.length).toBeLessThanOrEqual(280);
  });

  it("falls back to the trader's Reasoning when the risk text has no Executive Summary", () => {
    const summary = extractSummary("**Rating**: Underweight. The panel was cautious throughout.", TRADER);
    expect(summary!.startsWith("Both the technical report and research plan align")).toBe(true);
  });

  it("falls back to the opening of the risk text, then the trader text", () => {
    expect(extractSummary("**Rating**: Hold. A quiet week with no catalysts.", "not recorded")).toContain("A quiet week");
    expect(extractSummary("not recorded", "**Action**: Buy. The setup is clean.")).toContain("The setup is clean");
  });

  it("returns null when neither text was recorded", () => {
    expect(extractSummary("not recorded", "")).toBeNull();
    expect(extractSummary("", "not recorded")).toBeNull();
  });
});

describe("parseTraderAction", () => {
  it("reads the FINAL TRANSACTION PROPOSAL first", () => {
    expect(parseTraderAction(TRADER)).toBe("SELL");
  });

  it("reads the Action field when there is no proposal line", () => {
    expect(parseTraderAction("**Action**: Buy **Reasoning**: momentum.")).toBe("BUY");
    expect(parseTraderAction("Action: Hold, wait for the print.")).toBe("HOLD");
  });

  it("claims nothing for non-actions or missing text", () => {
    expect(parseTraderAction("**Action**: Start a 3-5% portfolio position here.")).toBeNull();
    expect(parseTraderAction("**Action**: Reduce exposure into strength.")).toBeNull();
    expect(parseTraderAction("not recorded")).toBeNull();
  });
});

describe("parsePriceLevels", () => {
  it("parses the GOOGL entry and stop; an unstated target stays null", () => {
    expect(parsePriceLevels(TRADER, RISK)).toEqual({ entry: 295, stop: 315, targets: [] });
  });

  it("does not read the ATR stop distance or the trailing-stop mention as the stop", () => {
    const levels = parsePriceLevels("Risk 1% of capital using 1.5×ATR ($15.36) stop distance, trailing stop near $258.50.");
    expect(levels.stop).toBeNull();
  });

  it("collects stated targets, with $ and thousands separators", () => {
    const levels = parsePriceLevels("**Entry Price**: $1,240.50 **Price Target**: $1,500 and a stretch Target: 1600.");
    expect(levels.entry).toBe(1240.5);
    expect(levels.targets).toEqual([1500, 1600]);
  });

  it("returns all-null for text without levels or unrecorded text", () => {
    expect(parsePriceLevels("not recorded", "No levels were discussed.")).toEqual({ entry: null, stop: null, targets: [] });
  });
});

describe("formatPrice", () => {
  it("drops decimals on whole dollars and keeps stated cents", () => {
    expect(formatPrice(295)).toBe("$295");
    expect(formatPrice(1240.5)).toBe("$1,240.50");
  });
});
