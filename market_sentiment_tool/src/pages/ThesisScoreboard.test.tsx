import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import Thesis from "@/pages/Thesis";
import type { Scoreboard } from "@/lib/thesisTracker";

const hook = vi.hoisted(() => ({
  board: null as Scoreboard | null,
  loading: false,
  error: null as string | null,
}));
vi.mock("@/hooks/useThesisScoreboard", () => ({
  useThesisScoreboard: () => hook,
}));
vi.mock("@/components/RequireAdmin", () => ({ sessionToken: async () => null }));
vi.mock("@/hooks/useThesisCards", () => ({ useThesisCards: () => ({ cards: [], loading: false, error: null }) }));
/** A scoreboard block sits behind its dashboard card: click it, then read inside the open view. */
const open = (card: string) => {
  fireEvent.click(screen.getByRole("button", { name: `Open ${card}` }));
  return within(screen.getByRole("dialog"));
};

const BOARD: Scoreboard = {
  generated_at: "2026-11-16T18:00:00+00:00",
  theses: [
    { slug: "event-lab", title: "Event lab (T1 rebuilt)", sleeve: "event_lab",
      status: "live", kill_line_count: 1, spec_ref: "spec#event-lab" },
    { slug: "core", title: "Core beta", sleeve: "core", status: "live",
      kill_line_count: 0, spec_ref: "spec#core" },
  ],
  claims: [
    { claim: "A", thesis_slug: "event-lab", metric: "classification_separation",
      state: "armed", deadline: "2027-03-01", days_to_deadline: 105,
      graded: 4, hits: 3, rate: 0.75, interval: [0.3, 0.95],
      progress_verdict: null, prints_target: 40, prints_remaining: 36,
      window_separation: null, rolling60_separation: null },
    { claim: "B", thesis_slug: "event-lab", metric: "supplier_excess_per_cluster",
      state: "armed", deadline: "2027-11-30", days_to_deadline: 379,
      graded: 0, hits: null, rate: null, interval: null,
      progress_verdict: null, clusters_target: 4, clusters_graded: 0,
      clusters_remaining: 4, mean_excess: null,
      note: "Clusters are the 2027 hyperscaler print rounds; none has completed, so there is nothing to grade yet." },
    { claim: "C", thesis_slug: "event-lab", metric: "play_kind_a_net_after_costs",
      state: "armed", deadline: "2027-03-01", days_to_deadline: 105,
      graded: 1, hits: null, rate: null, interval: null,
      progress_verdict: null, fires_target: 5, fires_remaining: 4, net: 100 },
  ],
  signals: {
    whisper: { graded: 3, hits: 2, rate: 0.6667, interval: [0.2, 0.94] },
    money_flow: { graded: 1, hits: 1, rate: 1, interval: [0.2, 1] },
  },
  play_kinds: {
    a: { links: 1, trades: 1, wins: 1, pnl: 100, hit_rate: 1, interval: [0.2, 1] },
    b: { links: 1, trades: 1, wins: 0, pnl: -30, hit_rate: 0, interval: [0, 0.8] },
  },
  sizing: {
    config: { unit_v2_premium: 5000, unit_v2_top: 10000, unit_fallback: 1500,
              play_kind_c_live: false, cash_floor_pct: 10 },
    health: { last_grader_run_at: "2026-11-16T16:00:00+00:00", last_grader_ok: true },
    governing_unit: { unit: 5000, source: "schedule_v2", fresh: true },
  },
  regime: {
    odds: { state: "ratified", stalemate: 0.55, boom: 0.2, crash: 0.25, as_of: "2026-11-15" },
    capex: { figure_usd_bn: null, crash_below_usd_bn: 620, boom_at_or_above_usd_bn: 950,
             grading: null, state: "unknown", as_of: null },
    crash_triggers: { fired: [], fired_count: 0, state: "unknown" },
    credit_lights: [
      { key: "credit_light_dc_yields", label: "Data-center borrowing yields",
        state: "unknown", as_of: null, age_days: null },
      { key: "credit_light_redemption_gates", label: "Private-credit redemption gates",
        state: "flickering", as_of: "2026-11-16T00:00:00Z", age_days: 0.8 },
      { key: "credit_light_bank_lending", label: "Bank lending tightening",
        state: "off", as_of: "2026-11-16T00:00:00Z", age_days: 0.8 },
    ],
  },
  cash_gauge: {
    floor_pct: 10,
    books: [
      { book: "main", cash_pct: 20, breach: false },
      { book: "big", cash_pct: 5, breach: true },
    ],
  },
  breaches: {
    refusals: [
      { at: "2026-11-16T15:00:00+00:00", route: "POST /api/v1/orders",
        outcome: "refused:tracker",
        detail: "post-trade cash share 8.1% breaches the 10% cash floor",
        cash_floor: true },
    ],
    stale_files: [
      { path: "research/nvda.md", thesis_slug: "event-lab",
        amended_at: "2026-11-10T00:00:00+00:00",
        last_decision_at: "2026-11-12T00:00:00+00:00" },
    ],
  },
};

const close = () => fireEvent.keyDown(document, { key: "Escape" });

describe("Thesis scoreboard page", () => {
  it("renders claims with countdowns, rates and intervals", () => {
    hook.board = BOARD;
    hook.loading = false;
    hook.error = null;
    render(<Thesis />);
    const a = open("Claim A");
    expect(a.getByText(/Claim A — classification_separation/)).toBeTruthy();
    expect(a.getByText(/36 of 40 prints remaining/)).toBeTruthy();
    expect(a.getByText(/75\.0%/)).toBeTruthy();
    close();
    expect(open("Claim B").getByText(/4 of 4 clusters remaining/)).toBeTruthy();
    close();
    expect(open("Claim C").getByText(/4 of 5 fires remaining/)).toBeTruthy();
  });

  it("keeps play kinds and signals in separate ledgers", () => {
    hook.board = BOARD;
    render(<Thesis />);
    const kinds = open("Play kinds");
    expect(kinds.getByText("(a)")).toBeTruthy();
    expect(kinds.getByText("(b)")).toBeTruthy();
    // $100 appears twice by design: Claim C's net and kind (a)'s P&L.
    expect(kinds.getAllByText("$100")).toHaveLength(1);
    close();
    const signals = open("Pre-print signals");
    expect(signals.getByText("Whisper sign")).toBeTruthy();
    expect(signals.getByText("Money flow")).toBeTruthy();
    close();
    expect(open("Claim C").getAllByText("$100")).toHaveLength(1);
  });

  it("shows the regime panel, the cash gauge and the breach log", () => {
    hook.board = BOARD;
    render(<Thesis />);
    expect(screen.getByText(/Governing event-lab unit/)).toBeTruthy();
    const regime = open("Regime");
    expect(regime.getByText(/no figure recorded yet/)).toBeTruthy();
    expect(regime.getByText("flickering")).toBeTruthy();
    expect(regime.getByText("breach")).toBeTruthy();
    close();
    const log = open("Breach log");
    expect(log.getByText(/post-trade cash share 8\.1%/)).toBeTruthy();
    expect(log.getByText("research/nvda.md")).toBeTruthy();
  });

  it("says plainly when the tracker is not seeded", () => {
    hook.board = null;
    render(<Thesis />);
    expect(screen.getByText(/not seeded yet/)).toBeTruthy();
  });
});
