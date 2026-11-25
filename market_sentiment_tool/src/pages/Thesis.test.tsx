import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import Thesis from "@/pages/Thesis";
import type { ForecastCard } from "@/lib/thesisTracker";

const hook = vi.hoisted(() => ({ cards: [] as ForecastCard[], loading: false, error: null as string | null }));
vi.mock("@/components/RequireAdmin", () => ({ sessionToken: async () => null }));
vi.mock("@/hooks/useThesisCards", () => ({ useThesisCards: () => hook }));
vi.mock("@/hooks/useThesisScoreboard", () => ({ useThesisScoreboard: () => ({ board: null, loading: false, error: null }) }));
const showAll = () => { fireEvent.click(screen.getByText(/Show all/)); return within(screen.getByRole("dialog")); };

const CARD: ForecastCard = {
  id: 1,
  ticker: "NVDA",
  thesis_id: 1,
  print_at: "2026-11-20T21:00:00+00:00",
  whisper_esp: 0.04,
  whisper_sign: "positive",
  money_flow_direction: "inflow",
  money_flow_evidence: [{ text: "capex raised", source: "https://example.com" }],
  guide_position: "guide below the priced trajectory",
  predicted_direction: "down",
  opposing_case_ref: "research/nvda.md#opposing-case",
  classification: "deteriorated",
  supersedes_id: null,
  frozen_at: "2026-11-20T12:00:00+00:00",
  superseded: false,
};

describe("Thesis tracker page", () => {
  it("renders frozen cards with their two signals kept separate", () => {
    hook.cards = [CARD];
    hook.loading = false;
    hook.error = null;
    render(<Thesis />);
    const full = showAll();
    expect(full.getByText("NVDA")).toBeTruthy();
    expect(full.getByText("positive")).toBeTruthy();
    expect(full.getByText("inflow")).toBeTruthy();
    expect(full.getByText("deteriorated")).toBeTruthy();
    expect(full.getByText("Frozen")).toBeTruthy();
  });

  it("marks a superseded card instead of showing it as live", () => {
    hook.cards = [{ ...CARD, superseded: true }];
    render(<Thesis />);
    const full = showAll();
    expect(full.getByText("Superseded")).toBeTruthy();
    expect(full.queryByText("Frozen")).toBeNull();
  });

  it("says plainly when no cards exist yet", () => {
    hook.cards = [];
    render(<Thesis />);
    expect(screen.getByText(/No forecast cards yet/)).toBeTruthy();
  });
});
