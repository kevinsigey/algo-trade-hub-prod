import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: null } }), onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }) } },
}));

import { DebateCard } from "@/components/AgentDebates";
import type { AgentDebateCard } from "@/lib/workshop";

// Section texts shaped like the stored GOOGL run (2026-11-02): markdown-ish
// excerpts with `**Label**: value` fields, long enough that the old card was
// a wall of text.
const BULL_TAIL = "The trend is your friend — until it ends. This trend ended on October 29th.";
const BEAR_TAIL = "I'll short the rallies. You catch the knives. Let's reconvene at $260.";

function card(over: Partial<AgentDebateCard> = {}): AgentDebateCard {
  return {
    source: "agent_debate",
    chip: "LLM agent debate — not a model signal",
    run_id: "googl-20261102-120000",
    ticker: "GOOGL",
    decision: "Underweight",
    run_at_ct: "2026-11-02T12:00:00",
    as_of_date: "2026-11-02",
    historical: false,
    historical_label: null,
    framework_version: "0.2.0abcdef",
    framework_short: "0.2.0ab",
    llm_provider: "google",
    llm_model: "gemini-test",
    status: "complete",
    error: null,
    market_anchor: null,
    live: null,
    stale: false,
    cost_usd: 0,
    inputs_note: "test inputs",
    analyst_summaries: {
      fundamentals: "# Alphabet Inc. (GOOGL) - Fundamental Analysis Report. Revenue growth is robust.",
      news: "not recorded",
      sentiment: "**Overall Sentiment:** **Mixed** (Score: 5.2/10). The labeled ratio is 2:1 bullish.",
      technicals: "# GOOGL Technical Analysis Report. RSI at 21.2 signals extreme oversold conditions.",
    },
    bull_case: `[…] ## 🎪 **Sentiment Check: Contrarian Fuel** - **StockTwits: 70% unlabeled** — retail is confused, not bearish. ${BULL_TAIL}`,
    bear_case: `[…] The bear case relies on broken technicals and surging CapEx. ${BEAR_TAIL}`,
    trader_rationale:
      "**Action**: Sell **Reasoning**: Both the technical report and research plan align on a bearish outlook. " +
      "**Entry Price**: 295.0 **Stop Loss**: 315.0 **Position Sizing**: Reduce existing long exposure. FINAL TRANSACTION PROPOSAL: **SELL**",
    risk_verdict:
      "**Rating**: Underweight **Executive Summary**: Trim existing GOOGL exposure by 30–50% of standard allocation; " +
      "sell rallies toward $290–300 with tight stops above $315. Hold residual position at 1–2% of portfolio. " +
      "**Price Target**: not provided **Time Horizon**: not provided",
    has_report: false,
    grades: { "+5d": "pending", "+20d": "pending" },
    ...over,
  };
}

function renderCard(c: AgentDebateCard) {
  return render(
    <ul>
      <DebateCard card={c} />
    </ul>,
  );
}

describe("DebateCard summary-first layout", () => {
  it("leads with the verdict, the trader action chip, and the extracted summary", () => {
    renderCard(card());
    expect(screen.getByText("GOOGL")).toBeTruthy();
    expect(screen.getByText("Underweight")).toBeTruthy();
    expect(screen.getByText("Trader: SELL")).toBeTruthy();
    // The summary paragraph; the same words also open the Risk panel's preview line.
    expect(screen.getAllByText(/Trim existing GOOGL exposure by 30–50% of standard allocation/).length).toBeGreaterThan(0);
    expect(screen.getByText("+5d pending")).toBeTruthy();
    expect(screen.getByText("+20d pending")).toBeTruthy();
  });

  it("draws the stated levels as a ladder and invents no target", () => {
    renderCard(card());
    expect(screen.getByText("Stated levels")).toBeTruthy();
    expect(screen.getByText("Entry $295")).toBeTruthy();
    expect(screen.getByText("Stop $315")).toBeTruthy();
    expect(screen.queryByText(/Target/)).toBeNull();
  });

  it("the list card carries no case text; each point opens under its own dropdown", () => {
    const { container } = renderCard(card());
    // Summary-only list (Kevin, 2026-11-03): no bull/bear text, no previews --
    // but every recorded point has its own closed dropdown.
    expect(screen.queryByText(/trend is your friend/)).toBeNull();
    expect(screen.queryByText(/reconvene at \$260/)).toBeNull();
    expect(screen.getByRole("button", { name: /Bull case/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Bear case/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Bull case/ }));
    expect(screen.getByText(/trend is your friend/)).toBeTruthy();
    expect(screen.queryByText(/reconvene at \$260/)).toBeNull(); // the bear stays closed
    // Formatted, never a raw dump: markdown headings become titles, no <pre>.
    expect(container.querySelector("pre")).toBeNull();
    expect(screen.queryByText(/# Alphabet Inc/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Bear case/ }));
    expect(screen.getByText(/reconvene at \$260/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Bull case/ }));
    expect(screen.queryByText(/trend is your friend/)).toBeNull();
  });

  it("skips sections the run did not record", () => {
    renderCard(card());
    expect(screen.queryByRole("button", { name: /News/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Fundamentals/ })).toBeTruthy();
  });

  it("renders the framework report as a document, tables included", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      "# Final Report\n\n| Case | Price |\n| --- | --- |\n| Bear | $61 |\n\nThe end.",
      { status: 200 })));
    const { container } = renderCard(card({ has_report: true }));
    fireEvent.click(screen.getByRole("button", { name: /Framework report/ }));
    expect(await screen.findByText("The end.")).toBeTruthy();
    expect(container.querySelector("table")?.textContent).toContain("$61");
    expect(container.querySelector("pre")).toBeNull();
  });

  it("renders no ladder and no action chip when the text states neither", () => {
    renderCard(
      card({
        trader_rationale: "**Action**: Reduce exposure into strength and wait.",
        risk_verdict: "**Rating**: Underweight. The panel was cautious throughout the session.",
      }),
    );
    expect(screen.queryByText("Stated levels")).toBeNull();
    expect(screen.queryByText(/Trader:/)).toBeNull();
    expect(screen.getAllByText(/The panel was cautious throughout/).length).toBeGreaterThan(0); // summary fallback still shows
  });
});

describe("the market anchor (Kevin, 2026-11-03)", () => {
  it("shows the traded price and flags levels that sit far from it", () => {
    renderCard(card({
      market_anchor: { price: 200, prev_close: 198, year_high: 220, year_low: 150, at: "2026-11-02T17:00:00Z" },
      live: { price: 205, at: "2026-11-03T14:00:00Z" },
    }));
    // The GOOGL fixture states Entry 295 / Stop 315 -- far from a $200 tape.
    expect(screen.getByText(/Traded at/)).toBeInTheDocument();
    expect(screen.getByText(/far from the traded price/)).toBeInTheDocument();
  });

  it("no flag when the stated levels sit near the traded price", () => {
    renderCard(card({
      market_anchor: { price: 300, prev_close: 298, year_high: 320, year_low: 240, at: "2026-11-02T17:00:00Z" },
    }));
    expect(screen.getByText(/Traded at/)).toBeInTheDocument();
    expect(screen.queryByText(/far from the traded price/)).not.toBeInTheDocument();
  });
});
