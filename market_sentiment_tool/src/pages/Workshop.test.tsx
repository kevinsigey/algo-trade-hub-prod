import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import App from "@/App";
import { claimLabel, conditionText, rulesText } from "@/lib/workshop";
import Workshop from "@/pages/Workshop";
import WorkshopIdea, { DraftEditor } from "@/pages/WorkshopIdea";

const session = vi.hoisted(() => ({ token: "jwt" as string | null }));
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: session.token ? { access_token: session.token } : null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

const SPEC = {
  title: "Gold when rates rise", hold: ["GLD"], otherwise: "SPY", claim: "beats_benchmark_when", benchmark: "SPY",
  cost_bps: 10, start: "2006-01-03", unseen_fraction: 0.3, assumptions: ["rates rising = 10-year yield up 0.25 over 3 months"],
  when: { source: "fred", series: "DGS10", measure: "change", lookback_days: 63, op: ">", threshold: 0.25 },
};
const RUN = {
  id: 1, variation: 4, spec: SPEC, draft_model: "claude-opus-5-5", verdict: "FAIL", created_at: "2026-10-30T00:00:00Z",
  result: {
    verdict: "FAIL", headline: "Worked on the years it was built on, not after.", reason: null, split_date: "2019-01-02",
    data_start: "2006-01-04", data_end: "2026-10-29", variations: 4,
    claim: { built: { holds: true, value: 3.1, label: "+3.1 pts/yr" }, unseen: { holds: false, value: -1.4, label: "-1.4 pts/yr" } },
    shuffle: { beats_pct: 71, p: 0.29, bar: 0.0125, permutations: 1000, seed: 4, method: "random timing" },
    t_test: { mean_daily_diff: 0.02, t: 1.7, p: 0.08 }, periods: { held: 3, of: 5 },
    context: [{ name: "Idea", built_cagr: 9, unseen_cagr: 7, unseen_max_dd: -20 }, { name: "SPY", built_cagr: 8, unseen_cagr: 12, unseen_max_dd: -25 }],
    curve: [{ t: "2006-01-04", idea: 0, benchmark: 0 }, { t: "2026-10-29", idea: 200, benchmark: 300 }],
  },
};

function serve(routes: Record<string, { status?: number; body: unknown }>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => url.includes(k));
    const hit = key ? routes[key] : { status: 200, body: {} };
    return new Response(JSON.stringify(hit.body), { status: hit.status ?? 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  session.token = "jwt";
  window.history.pushState({}, "", "/");
});

describe("workshop copy", () => {
  it("says each claim in plain words", () => {
    expect(claimLabel("ballast")).toMatch(/loses less than SPY/);
    expect(conditionText(SPEC.when as never)).toBe("DGS10 change over 63 trading days > 0.25");
    expect(conditionText(null)).toBe("always");
  });
});

describe("Workshop pages", () => {
  it("lists ideas with their latest verdict and sends the bearer token", async () => {
    const f = serve({ "/api/workshop/ideas": { body: [{ id: 1, title: "Gold when rates rise", created_at: "", runs: 4, latest_verdict: "FAIL" }] } });
    render(<MemoryRouter><Workshop /></MemoryRouter>);
    expect(await screen.findByText("Gold when rates rise")).toBeInTheDocument();
    expect(screen.getByLabelText("Type an idea in plain words")).toBeInTheDocument();
    expect(screen.getByText("4 runs")).toBeInTheDocument();
    expect((f.mock.calls[0][1] as RequestInit).headers).toMatchObject({ Authorization: "Bearer jwt" });
  });

  it("shows a verdict with the shuffle result and the variation count", async () => {
    serve({ "/api/workshop/ideas/1": { body: { idea: { id: 1, title: "Gold", plain_words: "Gold beats stocks when rates rise", created_at: "" }, runs: [RUN] } } });
    render(<MemoryRouter initialEntries={["/workshop/1"]}><Routes><Route path="/workshop/:id" element={<WorkshopIdea />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("Worked on the years it was built on, not after.")).toBeInTheDocument();
    expect(screen.getByText(/beats 71% of 1,000/)).toBeInTheDocument();
    expect(screen.getByText("4 · bar raised accordingly")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try a variation" })).toBeInTheDocument();
  });

  it("falls back to the hand-fill form when the AI can't draft", async () => {
    serve({
      "/api/workshop/ideas/2": { body: { idea: { id: 2, title: "Bonds", plain_words: "Bonds protect me", created_at: "" }, runs: [] } },
      "/api/workshop/draft": { status: 424, body: { detail: "OPENROUTER_API_KEY is not set", reason: "no_key", template: { ...SPEC, title: "", hold: [], when: null, claim: "beats_benchmark", assumptions: [] } } },
    });
    render(<MemoryRouter initialEntries={["/workshop/2?draft=1"]}><Routes><Route path="/workshop/:id" element={<WorkshopIdea />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("The AI couldn't draft this — fill it in.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run it" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("Bonds")).toBeInTheDocument();
  });

  it("never sends the session to a path built from a non-numeric id", async () => {
    const f = serve({});
    render(<MemoryRouter initialEntries={["/workshop/..%2F..%2Fadmin%2Fme"]}><Routes><Route path="/workshop/:id" element={<WorkshopIdea />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("No such idea.")).toBeInTheDocument();
    expect(f).not.toHaveBeenCalled();
  });

  it("is admin only", async () => {
    session.token = null;
    serve({ "/api/portfolio": { body: { state: "not_connected", as_of: null, scoreboard: {}, curve: [], composition: [], positions: [] } } });
    window.history.pushState({}, "", "/workshop");
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByRole("heading", { name: "Admin only" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /workshop/i })).toHaveAttribute("href", "/workshop");
  });
});


const PASS_RUN = { ...RUN, verdict: "PASS", result: { ...RUN.result, verdict: "PASS", headline: "Did what it claims on the years it hadn't seen." } };
const IDEA = { id: 1, title: "Gold", plain_words: "Gold beats stocks when rates rise", created_at: "", published_at: null, live_at: null, killed_at: null, size_pct: null };
const openIdea = () =>
  render(<MemoryRouter initialEntries={["/workshop/1"]}><Routes><Route path="/workshop/:id" element={<WorkshopIdea />} /></Routes></MemoryRouter>);
const posts = (f: ReturnType<typeof serve>) =>
  f.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST").map(([u, init]) => [String(u), (init as RequestInit).body]);

describe("Workshop live-paper gate", () => {
  it("shows why the gate is waiting and keeps Go live off", async () => {
    serve({
      "/api/workshop/ideas/1": { body: { idea: IDEA, runs: [PASS_RUN], tag: "idea-1-", shadow: null } },
      "/api/workshop/ideas/1/gate": { body: { status: "waiting", new_days: 40, needed: 63, claim: null, size_ok: true, reasons: ["waiting for data: 40 of 63 new trading days since the backtest"] } },
    });
    openIdea();
    fireEvent.change(await screen.findByLabelText("Size (% of account)"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Check the gate" }));
    expect(await screen.findByText(/40 of 63 new trading days/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Go live on paper" })).toBeDisabled();
  });

  it("goes live when the gate is clear", async () => {
    const f = serve({
      "/api/workshop/ideas/1": { body: { idea: IDEA, runs: [PASS_RUN], tag: "idea-1-", shadow: null } },
      "/api/workshop/ideas/1/gate": { body: { status: "ready", new_days: 70, needed: 63, claim: { holds: true, label: "+2.0 pts/yr vs benchmark", days: 70 }, size_ok: true, reasons: [] } },
      "/api/workshop/ideas/1/live": { body: { ...IDEA, live_at: "2026-11-02T15:00:00Z" } },
    });
    openIdea();
    fireEvent.change(await screen.findByLabelText("Size (% of account)"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Check the gate" }));
    const go = await screen.findByRole("button", { name: "Go live on paper" });
    await waitFor(() => expect(go).toBeEnabled());
    fireEvent.click(go);
    await waitFor(() => expect(posts(f)).toContainEqual([expect.stringContaining("/api/workshop/ideas/1/live"), JSON.stringify({ size_pct: 20 })]));
  });

  it("shows the order tag once live and asks before killing", async () => {
    const live = { ...IDEA, published_at: "2026-11-01T00:00:00Z", live_at: "2026-11-02T15:00:00Z", size_pct: 20 };
    const shadow = { days: 3, since: "2026-11-03", as_of: "2026-11-05", state: "live", return_pct: 1.2, bench_return_pct: 0.4, claim: null, failing: false, curve: [] };
    const f = serve({ "/api/workshop/ideas/1": { body: { idea: live, runs: [PASS_RUN], tag: "idea-1-", shadow } } });
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    openIdea();
    expect(await screen.findByText("idea-1-")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy tag" })).toBeInTheDocument();
    expect(screen.getByText("+1.2%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Kill this idea" }));
    expect(confirm).toHaveBeenCalled();
    expect(posts(f)).toEqual([]);
  });

  it("publishes to the Ideas record", async () => {
    const f = serve({
      "/api/workshop/ideas/1": { body: { idea: IDEA, runs: [RUN], tag: "idea-1-", shadow: null } },
      "/api/workshop/ideas/1/publish": { body: { ...IDEA, published_at: "2026-11-01T00:00:00Z" } },
    });
    openIdea();
    fireEvent.click(await screen.findByRole("button", { name: "Publish to the Ideas record" }));
    await waitFor(() => expect(posts(f).map(([u]) => u)).toContainEqual(expect.stringContaining("/api/workshop/ideas/1/publish")));
  });
});

describe("Workshop trade labels", () => {
  it("relabels a fill to an idea", async () => {
    const f = serve({
      "/api/workshop/ideas": { body: [{ id: 1, title: "Gold when rates rise", created_at: "", runs: 1, latest_verdict: "PASS" }] },
      "/api/workshop/fills": { body: { state: "live", fills: [{ order_id: "o-1", symbol: "GLD", side: "buy", qty: 10, price: 300, at: "2026-11-02T15:00:00Z", tag: null, idea_id: null, idea: "No idea yet (manual)", history: [] }] } },
      "/api/workshop/labels": { body: {} },
    });
    render(<MemoryRouter><Workshop /></MemoryRouter>);
    const pick = await screen.findByLabelText("Idea for GLD buy 10 on 2026-11-02");
    fireEvent.change(pick, { target: { value: "1" } });
    await waitFor(() => expect(posts(f)).toContainEqual([expect.stringContaining("/api/workshop/labels"), JSON.stringify({ order_id: "o-1", idea_id: 1 })]));
  });
});


describe("Workshop editor: shorts and orders", () => {
  it("posts short legs and the order type with the run", async () => {
    const f = serve({
      "/api/workshop/ideas/2": { body: { idea: { id: 2, title: "Bonds", plain_words: "Short QQQ", created_at: "" }, runs: [] } },
      "/api/workshop/draft": { body: { spec: { ...SPEC, hold: ["GLD"], short: [], execution: { order_type: "market", timing: "open", limit_offset_bps: 0 } }, model: "x/y:free" } },
      "/api/workshop/ideas/2/runs": { body: RUN },
    });
    render(<MemoryRouter initialEntries={["/workshop/2?draft=1"]}><Routes><Route path="/workshop/:id" element={<WorkshopIdea />} /></Routes></MemoryRouter>);
    fireEvent.change(await screen.findByLabelText("Short (tickers, comma separated)"), { target: { value: "SPY" } });
    fireEvent.change(screen.getByLabelText("Orders"), { target: { value: "limit:close" } });
    fireEvent.change(screen.getByLabelText("Limit offset (bps)"), { target: { value: "15" } });
    fireEvent.click(screen.getByRole("button", { name: "Run it" }));
    await waitFor(() => expect(posts(f).length).toBeGreaterThan(0));
    const body = JSON.parse(String(posts(f).find(([u]) => String(u).includes("/runs"))?.[1]));
    expect(body.spec.short).toEqual(["SPY"]);
    expect(body.spec.execution).toEqual({ order_type: "limit", timing: "close", limit_offset_bps: 15 });
  });
});


describe("Workshop automatic paper orders", () => {
  const live = { ...IDEA, published_at: "2026-11-01T00:00:00Z", live_at: "2026-11-02T15:00:00Z", size_pct: 20, auto_orders: false };
  const ORDER = { id: 1, idea_id: 1, day: "2026-11-03", symbol: "GLD", side: "buy", qty: 66, client_order_id: "idea-1-auto-20261103-GLD-open", status: "skipped", reason: "TRADEHUB_PAPER_ORDERS is off", alpaca_order_id: null, at: "" };

  it("asks before switching orders on, and says when the server switch is off", async () => {
    const f = serve({
      "/api/workshop/ideas/1": { body: { idea: live, runs: [PASS_RUN], tag: "idea-1-", shadow: null, orders_enabled: false, orders: [ORDER] } },
      "/api/workshop/ideas/1/auto": { body: { ...live, auto_orders: true } },
    });
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    openIdea();
    expect(await screen.findByText(/server's paper-order switch is off/)).toBeInTheDocument();
    expect(screen.getByText("TRADEHUB_PAPER_ORDERS is off")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Turn on automatic paper orders" }));
    expect(confirm).toHaveBeenCalled();
    await waitFor(() => expect(posts(f)).toContainEqual([expect.stringContaining("/api/workshop/ideas/1/auto"), JSON.stringify({ on: true })]));
  });
});


describe("Workshop editor: exits", () => {
  it("posts the exits with the run, and only offers intraday for one ticker", async () => {
    const f = serve({
      "/api/workshop/ideas/2": { body: { idea: { id: 2, title: "Gold", plain_words: "Gold with a stop", created_at: "" }, runs: [] } },
      "/api/workshop/draft": { body: { spec: { ...SPEC, hold: ["GLD"], short: [] }, model: "x/y:free" } },
      "/api/workshop/ideas/2/runs": { body: RUN },
    });
    render(<MemoryRouter initialEntries={["/workshop/2?draft=1"]}><Routes><Route path="/workshop/:id" element={<WorkshopIdea />} /></Routes></MemoryRouter>);
    fireEvent.change(await screen.findByLabelText("Stop-loss %"), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("Trailing stop %"), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText("Max days held"), { target: { value: "60" } });
    fireEvent.change(screen.getByLabelText("Exits checked"), { target: { value: "intraday" } });
    fireEvent.click(screen.getByRole("button", { name: "Run it" }));
    await waitFor(() => expect(posts(f).length).toBeGreaterThan(0));
    const body = JSON.parse(String(posts(f).find(([u]) => String(u).includes("/runs"))?.[1]));
    expect(body.spec.exits).toEqual({ stop_loss_pct: 8, trailing_pct: 12, take_profit_pct: null, max_days: 60, mode: "intraday" });
  });
});


describe("Workshop editor: intraday exits", () => {
  it("only offers during-the-day exits for one ticker", async () => {
    serve({
      "/api/workshop/ideas/2": { body: { idea: { id: 2, title: "Pair", plain_words: "Gold vs SPY", created_at: "" }, runs: [] } },
      "/api/workshop/draft": { body: { spec: { ...SPEC, hold: ["GLD"], short: ["SPY"] }, model: "x/y:free" } },
    });
    render(<MemoryRouter initialEntries={["/workshop/2?draft=1"]}><Routes><Route path="/workshop/:id" element={<WorkshopIdea />} /></Routes></MemoryRouter>);
    expect(await screen.findByRole("option", { name: /During the day/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Short (tickers, comma separated)"), { target: { value: "" } });
    expect(screen.getByRole("option", { name: /During the day/ })).toBeEnabled();
  });
});

describe("Workshop rules (step 6)", () => {
  it("renders rules text for legacy when", () => {
    expect(rulesText(SPEC as never)).toBe("while DGS10 change over 63 trading days > 0.25");
    expect(rulesText({ ...SPEC, when: undefined, rules: null } as never)).toBe("always");
    const rsi = { source: "price", series: "XLE", measure: "rsi", lookback_days: 14, slow_days: null, op: "<", threshold: 30 };
    const cross = { ...rsi, series: "SPY", measure: "sma_cross", lookback_days: 50, slow_days: 200, op: ">", threshold: 0 };
    const high = { ...rsi, series: "QQQ", measure: "vs_high", lookback_days: 20, op: ">", threshold: 0 };
    expect(conditionText(cross as never)).toBe("SPY 50-day avg above 200-day avg");
    expect(conditionText(high as never)).toBe("QQQ new 20-day high");
    expect(rulesText({ ...SPEC, when: undefined, rules: { enter: { mode: "all", conditions: [rsi, cross] }, exit: { mode: "any", conditions: [high] } } } as never))
      .toBe("buy when all of XLE RSI(14) < 30, SPY 50-day avg above 200-day avg; sell when QQQ new 20-day high");
  });

  const editor = (onRun = vi.fn()) => {
    render(<DraftEditor initial={{ ...SPEC, when: undefined, rules: null } as never} onRun={onRun} busy={false} />);
    return onRun;
  };

  it("adds and removes a condition", () => {
    editor();
    fireEvent.click(screen.getByLabelText("Buy only when a rule holds"));
    expect(screen.getAllByLabelText("Measure")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Add a buy condition" }));
    expect(screen.getAllByLabelText("Measure")).toHaveLength(2);
    fireEvent.change(screen.getAllByLabelText("Source")[1], { target: { value: "price" } });
    fireEvent.change(screen.getAllByLabelText("Measure")[1], { target: { value: "sma_cross" } });
    expect(screen.getByLabelText("Slow average (days)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove buy condition 1" }));
    expect(screen.getAllByLabelText("Measure")).toHaveLength(1);
    expect(screen.getByText("Sells when the buy rule stops holding.")).toBeInTheDocument();
  });

  it("sell-when toggle adds exit group to the saved spec", () => {
    const onRun = editor();
    fireEvent.click(screen.getByLabelText("Buy only when a rule holds"));
    fireEvent.click(screen.getByLabelText("Sell when its own rule holds"));
    fireEvent.change(screen.getByLabelText("Sell when"), { target: { value: "any" } });
    fireEvent.click(screen.getByRole("button", { name: "Run it" }));
    const sent = onRun.mock.calls[0][0];
    expect(sent.when).toBeUndefined();
    expect(sent.rules.enter.conditions).toHaveLength(1);
    expect(sent.rules.exit.mode).toBe("any");
    expect(sent.rules.exit.conditions).toHaveLength(1);
  });
});

describe("Workshop review fixes (step 6)", () => {
  it("lets Kevin type a slow average shorter than 200", () => {
    const cross = { source: "price", series: "SPY", measure: "sma_cross", lookback_days: 50, slow_days: 200, op: ">", threshold: 0 };
    const onRun = vi.fn();
    render(<DraftEditor initial={{ ...SPEC, when: undefined, rules: { enter: { mode: "all", conditions: [cross] }, exit: null } } as never} onRun={onRun} busy={false} />);
    const slow = screen.getByLabelText("Slow average (days)");
    fireEvent.change(slow, { target: { value: "1" } });
    expect(slow).toHaveValue(1); // mid-typing, not rewritten to 200
    for (const v of ["15", "150"]) fireEvent.change(slow, { target: { value: v } });
    fireEvent.click(screen.getByRole("button", { name: "Run it" }));
    expect(onRun.mock.calls[0][0].rules.enter.conditions[0].slow_days).toBe(150);
  });

  it("shows the server's reason for a rejected rule", async () => {
    serve({ "/api/workshop/ideas/1/runs": { status: 422, body: { detail: [{ loc: ["body"], msg: "Value error, sma_cross needs slow_days longer than lookback_days", type: "value_error" }] } } });
    const { adminJson } = await import("@/lib/workshop");
    await expect(adminJson("/api/workshop/ideas/1/runs", { method: "POST", body: "{}" })).rejects.toThrow("sma_cross needs slow_days longer than lookback_days");
  });
});

describe("Workshop analyst rules (step 6 Part B)", () => {
  const open = () => {
    render(<DraftEditor initial={{ ...SPEC, when: undefined, rules: null } as never} onRun={vi.fn()} busy={false} />);
    fireEvent.click(screen.getByLabelText("Buy only when a rule holds"));
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "analyst" } });
  };

  it("analyst source offers only analyst measures", () => {
    open();
    const options = Array.from((screen.getByLabelText("Measure") as HTMLSelectElement).options).map((o) => o.value);
    expect(options).toEqual(["net_upgrades", "target_upside"]);
  });

  it("warns analyst data starts ~2019 and stocks only", () => {
    open();
    expect(screen.getByText(/stocks only.*2019/i)).toBeInTheDocument();
    expect(conditionText({ source: "analyst", series: "AAPL", measure: "net_upgrades", lookback_days: 63, op: ">", threshold: 0 } as never))
      .toBe("AAPL analyst upgrades minus downgrades over 63 days > 0");
  });
});
