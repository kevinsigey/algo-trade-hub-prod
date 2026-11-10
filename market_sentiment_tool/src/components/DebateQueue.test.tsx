import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import DebateQueue from "@/components/DebateQueue";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const PAYLOAD = {
  snapshot: { id: 3, computed_at: "2026-11-10T00:39:00Z",
              completed_at: "2026-11-10T00:39:30Z", sheet_count: 77,
              banded_count: 49, source: "nightly" },
  counts: { entrants: 0, zone_names: 3, conjunctions: 1, total: 3 },
  generated_at: "2026-11-10T04:47:00Z",
  pending_by_class: { conjunction: 1, entrant: 0, zone: 2 },
  candidates: [
    { ticker: "MU", candidate_class: "conjunction", priority: 5,
      state: "pending",
      sources: { zone: "buy_zone_strong",
                 held: { books: ["big"], sleeves: ["T8 AI winners core"] } },
      verdict_id: null, computed_at: "2026-11-10T04:47:00Z" },
    { ticker: "ABBV", candidate_class: "zone", priority: 20, state: "pending",
      sources: { zone: "short_zone_strong" },
      verdict_id: null, computed_at: "2026-11-10T04:47:00Z" },
    { ticker: "OLD", candidate_class: "zone", priority: 20, state: "rendered",
      sources: { zone: "buy_zone" },
      verdict_id: 4, computed_at: "2026-11-10T04:47:00Z" },
  ],
  excluded: [
    { ticker: "MSFT", reason: "no fact sheet in snapshot #3",
      computed_at: "2026-11-10T04:47:00Z" },
    { ticker: "DHR", reason: "guide rejected by the guard",
      computed_at: "2026-11-10T04:47:00Z" },
  ],
};

function serve(payload: unknown) {
  const f = vi.fn(async () =>
    new Response(JSON.stringify(payload), { status: 200 }));
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("DebateQueue (Round 4)", () => {
  it("shows the stamped queue: pending counts by class, rows, exclusions", async () => {
    serve(PAYLOAD);
    render(<DebateQueue />);
    expect((await screen.findAllByText(/snapshot #3/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/queue generated/)).toBeInTheDocument();
    expect(screen.getByText(/3 pending/)).toBeInTheDocument();
    expect(screen.getByText(/1 conjunction/)).toBeInTheDocument();
    expect(screen.getByText(/2 zone/)).toBeInTheDocument();
    // The held conjunction leads and says what holds it.
    expect(screen.getByText("MU")).toBeInTheDocument();
    expect(screen.getByText(/held · T8 AI winners core/)).toBeInTheDocument();
    expect(screen.getByText("ABBV")).toBeInTheDocument();
    // Non-pending rows are summarized, not queued.
    expect(screen.getByText(/1 already rendered/)).toBeInTheDocument();
    // Exclusions are named with reasons.
    expect(screen.getByText(/2 named exclusions/)).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText(/no fact sheet in snapshot #3/)).toBeInTheDocument();
    expect(screen.getByText("DHR")).toBeInTheDocument();
  });

  it("says the queue is empty rather than rendering nothing", async () => {
    serve({ ...PAYLOAD, candidates: [], excluded: [],
            pending_by_class: { conjunction: 0, entrant: 0, zone: 0 } });
    render(<DebateQueue />);
    expect(await screen.findByText(/queue is empty/)).toBeInTheDocument();
  });
});
