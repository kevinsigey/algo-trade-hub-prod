import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { VerdictChipLine } from "@/components/VerdictChip";
import type { VerdictChip } from "@/lib/decisions";

const CHIP: VerdictChip = {
  ticker: "GILD", verdict_id: 7, rendered_at: "2026-11-10T06:00:00+00:00",
  judge: "free-ai-proposer", choice_id: "act_at_band_mid", direction: "long",
  confidence: 0.58, rationale: "guide supports it",
  dissent: "The price already pays for the guide.",
  snapshot_id: 3, fact_sheet_id: 103, trigger: "conjunction",
  zone: "buy_zone_strong",
};

afterEach(() => cleanup());

describe("VerdictChipLine (the per-name verdict element)", () => {
  it("shows verdict, confidence, dissent, judge, and the full-record link", () => {
    render(<MemoryRouter><VerdictChipLine chip={CHIP} ticker="GILD" /></MemoryRouter>);
    const el = screen.getByTestId("verdict-chip-GILD");
    expect(el).toHaveTextContent("Debate: Act at the mid band · long · 58% confidence");
    expect(el).toHaveTextContent("Dissent: The price already pays for the guide.");
    expect(el).toHaveTextContent("free AI (proposer)");
    const link = screen.getByRole("link", { name: "full decision view" });
    expect(link).toHaveAttribute("href", "/valuation?decision=GILD");
  });

  it("renders the honest absence for a name with no verdict", () => {
    render(<MemoryRouter><VerdictChipLine chip={undefined} ticker="MSFT" /></MemoryRouter>);
    expect(screen.getByTestId("verdict-chip-MSFT"))
      .toHaveTextContent("No debate verdict yet");
    expect(screen.queryByRole("link")).toBeNull();
  });
});
