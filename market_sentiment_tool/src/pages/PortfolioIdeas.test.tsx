import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Ideas from "@/pages/Ideas";
import Portfolio from "@/pages/Portfolio";

const session = vi.hoisted(() => ({ token: "jwt" as string | null }));
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: session.token ? { access_token: session.token } : null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const PORTFOLIO = {
  state: "live", as_of: "2026-11-10T20:41:00Z", account_number: "PA2", curve: [], composition: [], positions: [],
  scoreboard: { start_at: null, equity: 100000, return_pct: null, spy_return_pct: null, ahead_pts: null, max_drawdown_pct: null, sharpe: null, win_rate: null },
};
const IDEAS = [
  { id: 12, title: "TEST: 1 share XLE", live_at: "2026-10-31T00:00:00Z", killed_at: null, auto_orders: true, size_pct: "0.10503" },
  { id: 6, title: "Old XLE test", live_at: "2026-10-30T00:00:00Z", killed_at: "2026-10-31T00:00:00Z", auto_orders: false, size_pct: "0.010503" },
  { id: 7, title: "Ballast", live_at: null, killed_at: null, auto_orders: false, size_pct: null },
];

function route(map: Record<string, { status?: number; body: unknown }>) {
  const f = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const key = Object.keys(map).sort((a, b) => b.length - a.length).find((k) => url.includes(k));
    const hit = key ? map[key] : { status: 404, body: {} };
    return new Response(JSON.stringify(hit.body), { status: hit.status ?? 200 });
  });
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  session.token = "jwt";
});

describe("Portfolio ↔ Workshop", () => {
  it("lists the live auto-trading ideas with links, signed in, through the signed fetch", async () => {
    const f = route({ "/api/portfolio": { body: PORTFOLIO }, "/api/workshop/ideas": { body: IDEAS } });
    render(<MemoryRouter><Portfolio /></MemoryRouter>);
    const link = await screen.findByRole("link", { name: "TEST: 1 share XLE" });
    expect(link).toHaveAttribute("href", "/workshop/12");
    expect(screen.queryByText("Old XLE test")).not.toBeInTheDocument();
    expect(screen.queryByText("Ballast")).not.toBeInTheDocument();
    const call = f.mock.calls.find(([u]) => String(u).includes("/api/workshop/ideas"));
    expect((call?.[1] as RequestInit).headers).toMatchObject({ Authorization: "Bearer jwt" });
  });

  it("hides the list when the visitor is not signed in", async () => {
    session.token = null;
    route({ "/api/portfolio": { body: PORTFOLIO }, "/api/workshop/ideas": { status: 401, body: { detail: "no" } } });
    render(<MemoryRouter><Portfolio /></MemoryRouter>);
    expect(await screen.findByText(/Paper account · live/)).toBeInTheDocument();
    expect(screen.queryByText("Ideas trading on this account")).not.toBeInTheDocument();
  });
});

describe("Public Ideas record", () => {
  it("shows the whole Workshop record, not just what is published", async () => {
    route({ "/api/ideas/summary": { body: { tested: 10, passed: 1, failed: 8, not_enough_data: 1, published: 1 } }, "/api/ideas": { body: [] } });
    render(<MemoryRouter><Ideas /></MemoryRouter>);
    expect(await screen.findByText("Workshop record: 10 ideas tested · 1 passed · 8 failed · 1 not enough data · 1 published here")).toBeInTheDocument();
  });
});
