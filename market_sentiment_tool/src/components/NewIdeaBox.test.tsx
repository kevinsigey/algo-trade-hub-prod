import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import NewIdeaBox from "@/components/NewIdeaBox";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "t" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const LEDGER = {
  expressible: true, note: "", family: { size: 2, tickers: ["MU", "TXN"] }, prior_attempts: 4,
  best_prior: { idea_id: 7, title: "Chips", value: 3.5, verdict: "PASS", verdict_now: "FAIL" },
  killed: [], duplicate_of_killed: null, bar: { ideas_tested: 53, standard: "the bar" },
};

function serve(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

async function check() {
  render(<MemoryRouter><NewIdeaBox /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("Type an idea in plain words"), { target: { value: "chips keep winning" } });
  fireEvent.click(screen.getByRole("button", { name: "Check against the record" }));
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("NewIdeaBox", () => {
  it("shows what the record says, then offers the test", async () => {
    serve(200, { spec: { thesis: "x" }, questions: ["What size?"], model: "m", preflight: LEDGER });
    await check();
    expect(await screen.findByText(/Same bet as 2 tested ideas \(MU, TXN\), 4 prior attempts/)).toBeInTheDocument();
    expect(screen.getByText("What size?")).toBeInTheDocument();
    expect(screen.getByText(/FAIL today/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn into a test" })).toBeEnabled();
  });

  it("refuses to draft an exact duplicate of a killed idea", async () => {
    serve(200, { spec: null, questions: ["This exact idea was killed (idea 9): crowded."], model: "m",
                 preflight: { ...LEDGER, duplicate_of_killed: 9 } });
    await check();
    expect(await screen.findByText(/This exact idea was killed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn into a test" })).toBeDisabled();
  });

  it("still lets the idea through when the check is down", async () => {
    serve(422, { detail: "no model available" });
    await check();
    expect(await screen.findByText(/The check didn.t run/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn into a test" })).toBeEnabled();
  });
});
