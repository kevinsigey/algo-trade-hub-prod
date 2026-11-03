import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import Agent from "@/pages/Agent";
import { adminJson } from "@/lib/workshop";

vi.mock("@/lib/workshop", () => ({
  adminJson: vi.fn(),
  adminText: vi.fn(async () => ""),
}));

const SPEC = {
  thesis: "Energy majors are mispriced into the print and the complex rerates after.",
  catalysts: ["earnings"],
  invalidation: ["guide cut"],
  universe: ["XLE", "XOM"],
  entry: { rule: "manual", band_pct: null },
  sizing: { kind: "pct_of_equity", value: 10, per_name_cap_pct: 25 },
  stops: { kind: "pct", value: 8 },
  exits: { take_profit_pct: 20, time_stop_days: 30 },
  horizon: { terminal_date: "2026-11-06" },
  monitoring: ["price_cross"],
  scoring: { benchmark: "SPY", review_at: "terminal_date" },
};

const ROW = {
  id: 7,
  title: "Energy rerates",
  spec: SPEC,
  questions: [],
  state: "draft",
  gate: { expressible: true, verdict: "PASS", headline: "Passed the bar", split_date: "2024-01-02",
          data_start: "2020-01-02", data_end: "2026-11-02", shuffle_p: 0.01, claim_holds_unseen: true },
  created_at: "2026-11-03T15:00:00Z",
  updated_at: "2026-11-03T15:00:00Z",
};

const calls: { path: string; init?: RequestInit }[] = [];

function mockApi() {
  vi.mocked(adminJson).mockImplementation(async (path: string, init: RequestInit = {}) => {
    calls.push({ path, init });
    const method = init.method ?? "GET";
    if (path === "/api/agent/specs" && method === "GET") return { specs: [ROW] } as never;
    if (path === "/api/agent/interpret") return { spec: SPEC, questions: ["Which print?"], model: "test-model" } as never;
    if (path === "/api/agent/specs" && method === "POST") return { ...ROW, id: 8, gate: null } as never;
    if (path === "/api/agent/specs/7/state") return { ...ROW, state: "shadow" } as never;
    if (path === "/api/agent/specs/7/gate") return ROW as never;
    throw new Error(`unexpected ${method} ${path}`);
  });
}

beforeEach(() => {
  calls.length = 0;
  mockApi();
});
afterEach(cleanup);

describe("the strategy agent page", () => {
  it("lists stored specs with their state and gate verdict", async () => {
    render(<Agent />);
    expect(await screen.findByText("Energy rerates")).toBeTruthy();
    expect(screen.getByText("draft")).toBeTruthy();
    expect(screen.getByText("gate: PASS")).toBeTruthy();
    expect(screen.getByText(/Passed the bar/)).toBeTruthy();
  });

  it("interprets pasted text, shows the questions, and saves a confirmed draft", async () => {
    render(<Agent />);
    await screen.findByText("Energy rerates");
    fireEvent.change(screen.getByLabelText("Strategy text"), {
      target: { value: "Hold the energy majors into the print; they rerate after." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Interpret" }));
    expect(await screen.findByText("Questions, not guesses")).toBeTruthy();
    expect(screen.getByText("Which print?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Confirm — save as a draft/ }));
    await waitFor(() => {
      const post = calls.find((c) => c.path === "/api/agent/specs" && c.init?.method === "POST");
      expect(post).toBeTruthy();
    });
  });

  it("offers the shadow promotion only with a PASS on record, and moves the state", async () => {
    render(<Agent />);
    await screen.findByText("Energy rerates");
    fireEvent.click(screen.getByRole("button", { name: "Move to shadow" }));
    await waitFor(() => {
      const call = calls.find((c) => c.path === "/api/agent/specs/7/state");
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call!.init?.body))).toEqual({ state: "shadow" });
    });
    expect(await screen.findByText("shadow")).toBeTruthy();
  });
});
