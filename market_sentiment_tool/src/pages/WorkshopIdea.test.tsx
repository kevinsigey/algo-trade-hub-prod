import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AutopsyNote, LifecyclePanel } from "@/pages/WorkshopIdea";
import type { BookLiveState, IdeaDetail, Run } from "@/lib/workshop";

// The panel's signed-in fetch loads the Supabase client: stub it (no session).
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const RUN: Run = {
  id: 11, variation: 1, draft_model: null, verdict: "PASS", created_at: "2026-10-19T00:00:00Z",
  saved_at: "2026-10-19T00:00:00Z",
  spec: {
    title: "Test idea", hold: ["GLD"], rules: null, otherwise: "CASH", claim: "beats_benchmark",
    benchmark: "SPY", cost_bps: 10, start: "2006-01-03", unseen_fraction: 0.3, assumptions: [],
  },
  result: {
    verdict: "PASS", headline: "Did what it claims.", reason: null, split_date: "2024-01-02",
    data_start: "2006-01-03", data_end: "2026-10-16", claim: null, shuffle: null, t_test: null,
    periods: null, variations: 1, context: [], curve: [],
  },
};

const MAIN_LIVE: BookLiveState = {
  live_at: "2026-10-20T00:00:00Z", size_pct: 10, auto_orders: false, killed_at: null, gate: null, orders_enabled: true,
};

function detail(big: BookLiveState): IdeaDetail {
  return {
    idea: {
      id: 7, title: "Test idea", plain_words: "", created_at: "2026-10-01T00:00:00Z",
      published_at: "2026-10-02T00:00:00Z", tracked_at: "2026-10-03T00:00:00Z",
      live_at: "2026-10-20T00:00:00Z", killed_at: null, size_pct: 10, auto_orders: false,
    },
    runs: [RUN], tag: "idea-7-", shadow: null, orders_enabled: true, orders: [],
    books: { main: MAIN_LIVE, big },
  };
}

const READY_GATE = { status: "ready", new_days: 70, needed: 63, claim: null, size_ok: true, reasons: [] };

function serve(calls: { url: string; init?: RequestInit }[]) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url.includes("/gate?")) return new Response(JSON.stringify(READY_GATE), { status: 200 });
    return new Response(JSON.stringify({}), { status: 200 });
  }));
}

const posted = (calls: { url: string; init?: RequestInit }[], part: string) =>
  calls.filter((c) => c.url.includes(part)).map((c) => JSON.parse(String(c.init?.body ?? "{}")) as Record<string, unknown>);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("LifecyclePanel — the $1M book block", () => {
  it("runs the same gate for the second book and goes live with book=big at its own size", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    serve(calls);
    const onChange = vi.fn();
    render(
      <MemoryRouter>
        <LifecyclePanel id="7" detail={detail({ live_at: null, size_pct: null, auto_orders: false, killed_at: null, gate: null, orders_enabled: true })} onChange={onChange} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "$1M book" })).toBeInTheDocument();
    const goLive = screen.getByRole("button", { name: "Go live on the $1M book" });
    expect(goLive).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Size on the $1M book"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Check the gate" }));
    expect(await screen.findByText(/Clear\. Press Go live to start the \$1M book's record\./)).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/api/workshop/ideas/7/gate?size_pct=5"))).toBe(true);
    fireEvent.click(goLive);
    await waitFor(() => expect(posted(calls, "/api/workshop/ideas/7/live")).toEqual([{ size_pct: 5, book: "big" }]));
    expect(onChange).toHaveBeenCalled();
  });

  it("shows the live state on the $1M book, its own auto switch, and kills only that book", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    serve(calls);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <MemoryRouter>
        <LifecyclePanel
          id="7"
          detail={detail({ live_at: "2026-11-01T00:00:00Z", size_pct: 5, auto_orders: false, killed_at: null, gate: null, orders_enabled: false })}
          onChange={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Live on the \$1M book · since 2026-11-01 · size 5%/)).toBeInTheDocument();
    expect(screen.getByText(/paper-order switch for this book is off/)).toBeInTheDocument();
    // Both books show an auto-orders toggle (the main book's comes first); the
    // $1M one must post book=big.
    const toggles = screen.getAllByRole("button", { name: "Turn on automatic paper orders" });
    fireEvent.click(toggles[toggles.length - 1]);
    await waitFor(() => expect(posted(calls, "/api/workshop/ideas/7/auto")).toEqual([{ on: true, book: "big" }]));
    fireEvent.click(screen.getByRole("button", { name: "Kill this idea on the $1M book" }));
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("/api/workshop/ideas/7/kill?book=big") && c.init?.method === "POST")).toBe(true),
    );
  });
});

describe("AutopsyNote", () => {
  it("names the pattern and what it points at, with no advice once the cap is used", () => {
    const pattern = { implicates: "gate" as const, text: "9 of 10 trades opened in downtrend lost." };
    const { rerender } = render(<AutopsyNote autopsy={{ status: "ok", pattern, suggestion: "Try a rule." }} />);
    expect(screen.getByText("Why it lost")).toBeInTheDocument();
    expect(screen.getByText(/Points at: market condition/)).toBeInTheDocument();
    expect(screen.getByText(/Try a rule\./)).toBeInTheDocument();
    rerender(<AutopsyNote autopsy={{ status: "ok", pattern, suggestion: null }} revising />);
    expect(screen.getByText("What the last run's losses point at")).toBeInTheDocument();
    expect(screen.getByText(/used its 5/)).toBeInTheDocument();
  });

  it("says when there are too few losers and stays quiet when unavailable", () => {
    const { rerender, container } = render(<AutopsyNote autopsy={{ status: "too_few", trades: 4, losers: 1 }} />);
    expect(screen.getByText(/Too few losing trades/)).toBeInTheDocument();
    rerender(<AutopsyNote autopsy={{ status: "unavailable" }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
