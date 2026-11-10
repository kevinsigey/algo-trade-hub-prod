import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

import LevelWatcher from "@/pages/LevelWatcher";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const PAYLOAD = {
  stage: 1,
  rung_cap: 1,
  mode: "rung1_alerts_only",
  cpi_blackout_gap: true,
  status: { state: "up", last_heartbeat: "2026-11-09T15:00:00Z" },
  watches: [
    { id: 1, name: "TEST — harness watch", family: "test-family", kind: "level",
      instrument: "SPY", trigger_type: "cross_up", level: 100.0, level_hi: null,
      hold_minutes: null, intent: "long", rung: 3, enabled: true,
      disabled_reason: null, governor_group: "g1" },
  ],
  fires: [
    { id: 1, watch_id: 1, family: "test-family", instrument: "SPY",
      session_date: "2026-11-09", fired_at: "2026-11-09T15:00:00Z",
      rung_effective: 1, trigger_price: 100.6, intent: "long",
      score_1: null, score_5: null, crossing_ids: null },
  ],
  alerts_pending: [
    { id: 1, kind: "trigger", status: "pending",
      title: "Level watcher: SPY fired (Rung 1 alert)",
      body: "SPY cross_up through 100.0 — latest trade 100.6",
      created_at: "2026-11-09T15:00:00Z" },
  ],
  alerts_recent: [],
  families: [],
  governors: [
    { name: "g1", numbers_set: false, disarmed: false,
      note: "Governor numbers not set — Kevin's to set; this group has no active governor." },
  ],
};

function serve(payload: unknown = PAYLOAD) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/level-watcher")) {
      return new Response(JSON.stringify(payload), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Level watcher section", () => {
  it("states stage 1 / rung 1 up front, with health, governor and gap honesty", async () => {
    serve();
    render(<LevelWatcher />);
    const section = await screen.findByTestId("level-watcher");
    expect(await within(section).findByText(/STAGE 1 — RUNG 1 ALERTS ONLY/)).toBeTruthy();
    expect(within(section).getByText(/watcher up/)).toBeTruthy();
    expect(within(section).getByText(/Governor numbers not set/)).toBeTruthy();
    expect(within(section).getByText(/no stored CPI release calendar/)).toBeTruthy();
  });

  it("lists the watch with its rung capped, the pending alert and the fire", async () => {
    serve();
    render(<LevelWatcher />);
    const section = await screen.findByTestId("level-watcher");
    expect(await within(section).findByText(/TEST — harness watch/)).toBeTruthy();
    expect(within(section).getByText(/cross up through 100.00/)).toBeTruthy();
    expect(within(section).getByText(/3 → 1 in Stage 1/)).toBeTruthy();
    expect(within(section).getByText(/Level watcher: SPY fired/)).toBeTruthy();
    expect(within(section).getByText(/Alerts pending delivery \(1\)/)).toBeTruthy();
  });

  it("renders the honest empty state when nothing is armed", async () => {
    serve({ ...PAYLOAD, watches: [], fires: [], alerts_pending: [], governors: [] });
    render(<LevelWatcher />);
    const section = await screen.findByTestId("level-watcher");
    expect(await within(section).findByText(/No watches armed/)).toBeTruthy();
    expect(within(section).getByText(/No triggers yet/)).toBeTruthy();
    expect(within(section).getByText(/No alerts pending/)).toBeTruthy();
  });
});
