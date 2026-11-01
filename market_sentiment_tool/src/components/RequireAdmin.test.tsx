import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import App from "@/App";

const session = vi.hoisted(() => ({ token: null as string | null }));
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: session.token ? { access_token: session.token } : null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

function stub(adminStatus: number) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/admin/me")) {
        expect((init?.headers as Record<string, string>).Authorization).toBe(`Bearer ${session.token}`);
        return new Response(JSON.stringify({ detail: "admin only" }), { status: adminStatus });
      }
      if (url.includes("/api/portfolio")) {
        return new Response(JSON.stringify({ state: "not_connected", as_of: null, scoreboard: {}, curve: [], composition: [], positions: [] }));
      }
      return new Response(JSON.stringify({ as_of: null, rows: [], engines: 0, catalogue: { entries: [] } }));
    }),
  );
}

async function at(path: string) {
  window.history.pushState({}, "", path);
  await act(async () => {
    render(<App />);
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  session.token = null;
  window.history.pushState({}, "", "/");
});

describe("the admin gate", () => {
  it("shows the login prompt on an operator page with no session, keeping the URL", async () => {
    stub(401);
    await at("/scoreboard");
    expect(screen.getByRole("heading", { name: "Admin only" })).toBeInTheDocument();
    // The page's own prompt carries the way back; the menu's Sign in entry is the other link.
    const hrefs = screen.getAllByRole("link", { name: "Sign in" }).map((a) => a.getAttribute("href"));
    expect(hrefs).toContain("/login?next=%2Fscoreboard");
    expect(window.location.pathname).toBe("/scoreboard");
  });

  it("treats an expired session (server says 401) as signed out", async () => {
    session.token = "expired";
    stub(401);
    await at("/health");
    expect(screen.getByRole("heading", { name: "Admin only" })).toBeInTheDocument();
  });

  it("lets the admin through when the server confirms the session", async () => {
    session.token = "jwt";
    stub(200);
    await at("/models");
    expect(screen.queryByRole("heading", { name: "Admin only" })).toBeNull();
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
  });
});

describe("the Trading HQ menu and routes", () => {
  it("makes the portfolio the home page and groups the menu", async () => {
    stub(401);
    await at("/");
    expect(screen.getByRole("heading", { name: "Portfolio", level: 1 })).toBeInTheDocument();
    for (const label of ["Portfolio", "Predictions", "Admin"]) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /closed trades/i })).toHaveAttribute("href", "/portfolio/closed");
    expect(screen.getByRole("link", { name: /overview/i })).toHaveAttribute("href", "/predictions");
    expect(screen.getAllByText("Not connected").length).toBeGreaterThan(0);
  });

  it("has a sign-in page with no sign-up", async () => {
    stub(401);
    await at("/login");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.queryByText(/sign up|create account|register/i)).toBeNull();
  });
});
