import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import Health from "@/pages/Health";

// The page now reads the re-run state through the signed admin fetch, which loads the
// Supabase client: stub it (no session, so the re-run read simply finds nothing).
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const REPORT = {
  history: {
    days: ["2026-10-16", "2026-10-17"],
    timers: { scan: [
      { date: "2026-10-16", status: "ok" },
      { date: "2026-10-17", status: "silent" },
    ] },
    families: { weather: [
      { date: "2026-10-16", status: "ok", count: 12 },
      { date: "2026-10-17", status: "none", count: 0 },
    ] },
    diagnostics: [
      { date: "2026-10-16", status: "none", flags: [] },
      { date: "2026-10-17", status: "flags", flags: ["labor_nowcast: pay_rev_3m: mostly_zero"] },
    ],
  },
  status: "degraded",
  generated_at: "2026-10-17T12:00:00+00:00",
  frozen_window_hours: 24,
  stale_after_hours: 2,
  timers: {
    scan: { last_success: null, age_seconds: null, status: "not_tracked", tracked: false },
    journal: { last_success: null, age_seconds: null, status: "never", tracked: true },
  },
  untracked_timers: ["scan"],
  tracked_timer_count: 1,
  families: {
    weather_high: { frozen_24h: 20, cadence: "daily", expected_daily: true, silent: false },
  },
  orderbook: { newest_file_age_seconds: null, status: "missing" },
  problems: ["timer journal is never"],
};

function mockFetch(payload: unknown, ok = true, contentType = "application/json") {
  return vi.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 500,
    headers: { get: () => contentType },
    json: async () => payload,
  });
}

describe("Health page", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch({ status: "ok", report: REPORT }));
  });

  it("shows the timer, family and order-book facts and a dash for a missing age", async () => {
    render(<Health />);
    await waitFor(() => expect(screen.getByText("Timers fresh")).toBeTruthy());
    expect(screen.getByText("0/1")).toBeTruthy(); // only journal is tracked, and it never ran
    expect(screen.getByText("Never ran")).toBeTruthy(); // journal chip
    expect(screen.getByText("Not tracked")).toBeTruthy(); // scan chip, not "Never ran"
    expect(screen.getByText("Missing")).toBeTruthy(); // order-book chip
    // A never-run timer and a missing file render as a dash, not 0.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("weather_high")).toBeTruthy();
    expect(screen.getByText("Degraded")).toBeTruthy();
  });

  it("draws the 14-day heatmap with evidence-based cell labels", async () => {
    render(<Health />);
    await waitFor(() => expect(screen.getByText("Last 14 days")).toBeTruthy());
    expect(screen.getByLabelText("scan · 2026-10-17 · silent — a gap inside an active stretch")).toBeTruthy();
    expect(screen.getByLabelText("weather · 2026-10-16 · ran · 12 frozen")).toBeTruthy();
    expect(screen.getByLabelText(/diagnostics · 2026-10-17 · labor_nowcast: pay_rev_3m: mostly_zero/)).toBeTruthy();
  });

  it("offers a re-run for scan and settles it into pending once asked", async () => {
    const calls: { url: string; method?: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method });
      const body = url.includes("/api/health/rerun")
        ? init?.method === "POST"
          ? { status: "pending", job: "scan", requested_by: "k@example.com", requested_at: "2026-10-17T12:05:00+00:00" }
          : { pending: {} }
        : { status: "ok", report: REPORT };
      return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => body } as unknown as Response;
    }));
    const { fireEvent } = await import("@testing-library/react");
    render(<Health />);
    await screen.findByText("Timers fresh");
    // journal is not re-runnable: exactly one Re-run button exists (scan).
    expect(screen.getAllByRole("button", { name: "Re-run" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Re-run" }));
    expect(await screen.findByText(/scan re-run requested/)).toBeTruthy();
    expect(screen.getByText(/Re-run pending/)).toBeTruthy();
    expect(calls.some((c) => c.url.includes("/api/health/rerun") && c.method === "POST")).toBe(true);
    // Once asked, the button is replaced by the pending chip.
    expect(screen.queryByRole("button", { name: "Re-run" })).toBeNull();
  });

  it("shows a healthy report as Healthy with no problems", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        status: "ok",
        report: {
          status: "ok",
          generated_at: "2026-10-17T12:00:00+00:00",
          frozen_window_hours: 24,
          stale_after_hours: 2,
          untracked_timers: ["scan", "settle"],
          tracked_timer_count: 2,
          timers: {
            scan: { last_success: null, age_seconds: null, status: "not_tracked", tracked: false },
            settle: { last_success: null, age_seconds: null, status: "not_tracked", tracked: false },
            journal: { last_success: "2026-10-17T11:50:00+00:00", age_seconds: 600, status: "ok", tracked: true },
            orderbooks: { last_success: "2026-10-17T11:40:00+00:00", age_seconds: 1200, status: "ok", tracked: true },
          },
          families: {
            weather_high: { frozen_24h: 12, cadence: "daily", expected_daily: true, silent: false },
          },
          orderbook: { newest_file_age_seconds: 1200, status: "ok" },
          problems: [],
        },
      }),
    );
    render(<Health />);
    await waitFor(() => expect(screen.getByText("2/2")).toBeTruthy());
    // The whole point: a healthy system with two untracked jobs must not read as degraded.
    expect(screen.queryByText("Degraded")).toBeNull();
    expect(screen.queryByText("Never ran")).toBeNull();
    // By role, not by text: `getByText("Problems")` also matches the stat card's label, so it proves
    // nothing about whether the problems SECTION is hidden.
    expect(screen.queryByRole("heading", { name: "Problems" })).toBeNull();
    // The untracked jobs are named and explained rather than dropped from the page.
    expect(screen.getByText(/write no record of each run/)).toBeTruthy();
    expect(screen.getAllByText("Not tracked").length).toBe(2);
    expect(screen.getByText("2 not tracked")).toBeTruthy();
  });

  it("reports an absent report as an error rather than a healthy page", async () => {
    vi.stubGlobal("fetch", mockFetch({ status: "ok", report: null }));
    render(<Health />);
    await waitFor(() => expect(screen.getByText(/has no health report/)).toBeTruthy());
  });

  it("reports the status when a non-JSON response comes back", async () => {
    vi.stubGlobal("fetch", mockFetch({}, false, "text/html"));
    render(<Health />);
    await waitFor(() => expect(screen.getByText(/status 500/)).toBeTruthy());
  });
});

describe("Health timestamps", () => {
  it("shows times in Central time, not raw ISO", async () => {
    vi.stubGlobal("fetch", mockFetch({ status: "ok", report: REPORT }));
    render(<Health />);
    expect(await screen.findByText(/^Generated 7:00 AM CT, Sat Oct 17$/)).toBeInTheDocument();
    expect(screen.queryByText(/2026-10-17T12:00:00/)).not.toBeInTheDocument();
  });
});
