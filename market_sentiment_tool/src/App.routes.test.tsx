import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import App from "@/App";
import type { ModelsResponse } from "@/lib/models";

// `src/lib/supabase.ts` builds a real client at import time and THROWS when the publishable key is
// absent, so importing `App` -- which pulls in `Home` -> `useMarketEdges` --
// fails before a single assertion runs. The stub is a stand-in for a credential this test does not
// need: neither route rendered here reads a Supabase table directly (the API does), so nothing
// calls it. Setting a fake URL instead would be worse: it would let a test that means to prove
// reachability quietly exercise a real network path.
// The operator pages (/scoreboard, /models) sit behind the admin gate, so the stub carries a session
// and `/api/admin/me` answers 200 below: these tests are about the routes, the gate has its own file.
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "jwt" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    },
  },
}));

/**
 * A mount counter for the Journal (Model Tracker) component, so a redirect loop is observable.
 *
 * A `Navigate` that points at itself renders the page over and over, and in jsdom that does not
 * throw and does not fail an assertion -- it just never settles, which reads as a passing test with
 * a slightly odd warning. Counting mounts turns "it settles" into something assertable: `<Navigate>`
 * replaces itself in the tree, so a correct redirect renders the Tracker exactly once, and a loop
 * renders it many times.
 *
 * The mock wraps the real component rather than replacing it, so the heading this file asserts on
 * is still the real page's, and `App.tsx`'s route table is still the only one in play.
 */
let journalRenders = 0;
vi.mock("@/pages/Journal", async () => {
  const actual = await vi.importActual<typeof import("@/pages/Journal")>("@/pages/Journal");
  const Counting = (props: Record<string, unknown>) => {
    journalRenders += 1;
    return <actual.default {...props} />;
  };
  return { ...actual, default: Counting };
});

/**
 * The `/scoreboard`, `/models` and `/shadow` routes are load-bearing, so they are pinned.
 *
 * These names are unreachability-sensitive. `/models` existed because the owner of the product
 * could not work out what the site was for, and a page nobody can reach does not answer that for
 * anybody. The other two are the pair that collided on 2026-09-28, when a visitor went to `/shadow`
 * for the scoreboard and got a 503 from a crypto backtester instead. On 2026-11-02 the owner
 * merged the scoreboard and the models catalogue into the Model Tracker as its Backtests tab:
 * the names still resolve -- to the tab, not to standalone pages -- and the nav entries are gone,
 * because two tabs presenting one dataset next to the forward record confused more than they
 * informed. What this file pins now is the landing: path, tab, and content, together.
 *
 * The route table is NOT re-declared here. A `MemoryRouter` test would have to repeat the routes
 * to render anything, and a duplicated route table passes when the real one loses a route -- which
 * is exactly the deletion this file exists to catch. So the real `BrowserRouter` is used and the
 * path is set on the history before render, which makes the only route table in play `App.tsx`'s
 * own.
 */
const EMPTY_BOARD: ModelsResponse = {
  as_of: "2026-09-27T00:00:00+00:00",
  runs_read: 0,
  rows: [],
  engines: 0,
  promotion_lookup_failed: false,
  rows_total: 0,
  rows_behind_market: 0,
  rows_ahead_of_market: 0,
  rows_level_with_market: 0,
  rows_not_comparable: 0,
  any_beats_market: false,
  headline: "No backtest runs are recorded yet, so no engine has a record to show.",
  headline_kind: "no_runs",
  caveat: null,
  // Every engine the product has, and none of them measured. A board with no catalogue at all would
  // render the "the catalogue came back empty" notice, which is a different page and would make
  // this assertion about the wrong thing.
  catalogue: {
    engines_total: 1,
    engines_measured: 0,
    engines_not_measured: 1,
    engines_unlisted: 0,
    entries: [
      {
        engine: "gas",
        label: "Gasoline — AAA US average, day over day",
        claim: "Whether the AAA US average gasoline price will finish the day above or below a strike.",
        claim_note: "",
        in_catalogue: true,
        cadence: "daily",
        measured: false,
        measured_rows: 0,
        status: "not_measured",
        worst_brier_ratio: null,
        rows: [],
      },
    ],
  },
};

/** The merged board's headline, rendered by the Backtests tab once its read resolves. The tab
 * has no h1 of its own -- the Tracker's "Model Tracker" h1 heads the page -- so the board's
 * summary sentence is the marker that the tab, and not a loading shell, is on screen. */
function boardHeadline(): HTMLElement | null {
  return screen.queryByText(/No backtest runs are recorded yet/);
}

/** The crypto page's h1. A separate query so the shadow describe can assert its absence without
 *  caring what the scoreboard is called. */
function cryptoHeading(): HTMLElement | null {
  return screen.queryByRole("heading", { name: /^Crypto$/, level: 1 });
}

/** The crypto desk's reads, stubbed empty-but-valid: the board with no cells filled and a
 *  verdict whose population is all zero, so the desk renders its frame without inventing a
 *  record. */
const EMPTY_BOARD_CRYPTO = {
  generated_at: "2026-11-01T00:00:00Z",
  note: "Kalshi market data, not a prediction.",
  spots: { BTC: null, ETH: null },
  hourly: { BTC: null, ETH: null },
  quarter: { BTC: null, ETH: null },
};
const EMPTY_VERDICT = {
  record: "sniper_closed_record",
  graded_on: "2026-11-01",
  worker: { first_row: null, last_row: null, stopped: "2026-06-02", venue: "Kalshi demo API" },
  population: { archived_rows: 0, by_status: {}, grading_population: 0, considered: 0, dead_zone: 0, dead_zone_share: null, graded: 0 },
  overall: { count: 0, hit_rate: null, virtual_pnl_pct: 0, brier_score: null },
  by_asset: {},
  buckets: {},
  price_source: "",
  method: "",
};

/** Only `/api/scoreboard` matters here. The sidebar's book read is stubbed too, because `App` mounts
 * it on every route and an unstubbed read would be a real network call from a unit test. */
function stubApi() {
  const answers: Record<string, unknown> = {
    "/api/scoreboard": EMPTY_BOARD,
    "/api/journal": {
      as_of: "2026-10-01T00:00:00+00:00",
      forecasters: [],
      headline: { forecasters: 0, calibrated: 0, settled_calibrated: 0, promoted: 0 },
    },
    "/api/crypto/board": EMPTY_BOARD_CRYPTO,
    "/api/crypto/sniper-verdict": EMPTY_VERDICT,
    "/api/onchain": { chains: [] },
    "/api/admin/me": { email: "kevin@example.com" },
    "/api/ideas": [],
    "/api/portfolio": { state: "not_connected", as_of: null, scoreboard: {}, curve: [], composition: [], positions: [] },
  };
  const spy = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const key = Object.keys(answers).find((path) => url.includes(path));
    return { ok: true, status: 200, json: async () => answers[key ?? ""] ?? {} } as Response;
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

/** Render on a settled tree: every stubbed read resolves inside `act`, so nothing lands after the
 * assertions (which would be React's act() warning, and a flake waiting for a slower machine). */
async function renderAppAt(path: string) {
  stubApi();
  window.history.pushState({}, "", path);
  await act(async () => {
    render(<App />);
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.pushState({}, "", "/");
  // Reset the redirect-loop counter between tests. Without this, an earlier test's mount count
  // would be carried into a later `toBe(1)` and the guard would stop guarding.
  journalRenders = 0;
});

describe("the sidebar link and the route agree", () => {
  it("resolves /scoreboard to the Model Tracker's Backtests tab", async () => {
    await renderAppAt("/scoreboard");

    // The board is rendered only once the read resolves, so this is the tab and not a shell.
    expect(boardHeadline()).toBeInTheDocument();
    expect(window.location.pathname).toBe("/journal");
    expect(window.location.search).toBe("?view=backtests");
    // The standalone nav entries are gone (the merge); the Tracker is the way in.
    expect(screen.queryByRole("link", { name: /engine scoreboard/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /model tracker/i })).toHaveAttribute("href", "/journal");
  });

  it("resolves /models to the Model Tracker's Backtests tab, catalogue included", async () => {
    // The page that answered "what are the models and what are they doing" is a tab now; the
    // name still lands on its content -- the catalogue's unmeasured engine renders in the tab.
    await renderAppAt("/models");

    expect(window.location.pathname).toBe("/journal");
    expect(window.location.search).toBe("?view=backtests");
    expect(screen.getByText("Gasoline — AAA US average, day over day")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^models$/i })).not.toBeInTheDocument();
  });

  it("resolves /ideas to the public Ideas record", async () => {
    await renderAppAt("/ideas");

    expect(screen.getByRole("heading", { name: "Ideas", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^ideas$/i })).toHaveAttribute("href", "/ideas");
  });

  it("resolves /journal to the prediction journal", async () => {
    // The flagship page (v2 spec §11). Pinned like /models: a page nobody can reach answers nothing.
    await renderAppAt("/journal");

    expect(screen.getByRole("heading", { name: "Model Tracker", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /model tracker/i })).toHaveAttribute("href", "/journal");
  });

  it("carries the no-orders line above every page", async () => {
    for (const path of ["/journal", "/models", "/no-such-route"]) {
      await renderAppAt(path);
      expect(screen.getByRole("note")).toHaveTextContent("Paper orders only — never real money.");
      cleanup();
    }
  });

  it("redirects the retired /lab to the journal without a 404", async () => {
    // The Prediction Lab was cut (v2 spec §9). Old links must land somewhere real, not on an empty shell.
    await renderAppAt("/lab");

    expect(screen.getByRole("heading", { name: "Model Tracker", level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/journal");
    expect(screen.queryByRole("link", { name: /prediction lab/i })).not.toBeInTheDocument();
  });

  it("renders no tracker page on a path with no route", async () => {
    // The control. Without it the tests above would also pass if the page rendered unconditionally
    // -- a bug the deletion it guards against and a missing guard both look like.
    await renderAppAt("/no-such-route");

    expect(screen.queryByRole("heading", { name: "Model Tracker", level: 1 })).not.toBeInTheDocument();
    // The shell still renders, so the absence is the route's doing and not a crashed tree.
    expect(screen.getByRole("link", { name: /model tracker/i })).toBeInTheDocument();
  });

  it("renders no backtest board on a path with no route", async () => {
    // The control for the board, same reasoning as above.
    await renderAppAt("/no-such-route");

    expect(boardHeadline()).toBeNull();
    expect(screen.getByRole("link", { name: /model tracker/i })).toBeInTheDocument();
  });
});

/**
 * `/shadow-scoreboard` is a redirect, not a second route for the same component.
 *
 * This is the interesting failure in the whole change, and it is invisible from the page. A
 * `Navigate` that points at its own path, or at a path that redirects back to it, produces a
 * redirect loop: the router navigates forever and the reader sees a blank shell, while every other
 * assertion in this file still passes because the sidebar renders. So three things are checked,
 * and the middle one is the one that catches it:
 *
 *   1. The redirect LANDS ON THE CANONICAL COMPONENT -- the board is on screen. A redirect that
 *      renders nothing would otherwise satisfy "the path changed" and pass.
 *   2. The final path is `/journal?view=backtests` (since the 2026-11-02 merge; before it, the
 *      canonical path was `/scoreboard`). A loop does not settle here, and a redirect to some
 *      third path would also fail.
 *   3. The Journal component is rendered ONCE. `<Navigate>` swaps itself out of the tree rather
 *      than nesting, so a correct redirect never re-enters; a loop renders it over and over. The
 *      spy is what makes that observable, because a loop in a jsdom test does not throw -- it just
 *      stops settling.
 *
 * The spy is on the MODULE, not on a re-declared route. `App.tsx`'s own route table is still the
 * only one in play; the mock replaces the component it points at, not the routing.
 */
describe("the /shadow-scoreboard redirect lands on the canonical route", () => {
  it("renders the backtest board itself, not a blank shell", async () => {
    await renderAppAt("/shadow-scoreboard");

    // The load-bearing assertion. A redirect to a path with no route, or to a route whose element
    // is another redirect, renders nothing here and this fails.
    expect(boardHeadline()).toBeInTheDocument();
  });

  it("settles on /journal?view=backtests rather than re-entering itself", async () => {
    await renderAppAt("/shadow-scoreboard");

    expect(window.location.pathname).toBe("/journal");
    expect(window.location.search).toBe("?view=backtests");
    // And the loop guard: a self-referential Navigate would keep remounting this component.
    expect(journalRenders).toBe(1);
  });

  it("is a redirect and not a second route serving the same component", async () => {
    // The duplication risk, pinned. Two routes both rendering the Tracker would make both paths
    // serve the page, which is the ambiguity this rename exists to remove -- and it would be
    // invisible to every other test here. What distinguishes them: at the alias the Tracker is
    // NOT what the route table selected; the router swapped in a Navigate and then routed again.
    // So exactly one Journal render, and the path has moved on.
    await renderAppAt("/shadow-scoreboard");

    expect(journalRenders).toBe(1);
    expect(boardHeadline()).toBeInTheDocument();
  });
});

/**
 * The word 'shadow', after phase-3 §5 (2026-11-01).
 *
 * The 2026-09-28 collision rulings pinned here for a month said: `/shadow` serves the crypto
 * timeline itself, never a redirect, and never the scoreboard. Phase-3 §5 superseded them on
 * the owner's call: the timeline graded a worker that stopped in June 2026, so the backtester
 * is deleted and `/shadow` redirects to its successor, the crypto research desk at `/crypto`.
 * What survives from the old ruling is the substitution guard, and it is still the point:
 * `/shadow` must land on the CRYPTO successor, not on the scoreboard -- a redirect that quietly
 * replaced a crypto page with an engine scoreboard would be the same collision wearing a hat.
 * The nav says "Crypto" (2026-11-06 redesign; was "Crypto research") and points at `/crypto`; nothing links to `/shadow` any more.
 */
describe("the two pages that share the word 'shadow'", () => {
  it("resolves /shadow to the crypto research desk, not to the scoreboard", async () => {
    await renderAppAt("/shadow");

    expect(window.location.pathname).toBe("/crypto");
    expect(cryptoHeading()).toBeInTheDocument();
    expect(boardHeadline()).toBeNull();
  });

  it("labels the crypto nav entry 'Crypto' and points it at /crypto", async () => {
    // Asserted on the /crypto route rather than on "/" because the sidebar mounts on every
    // route and "/" additionally mounts Home, which opens a realtime Supabase channel this
    // file's stub is not a client for.
    await renderAppAt("/crypto");

    const link = screen.getByRole("link", { name: /^crypto$/i });
    expect(link).toHaveAttribute("href", "/crypto");
    // Nothing in the nav is called plain "Shadow", and nothing links to the retired route.
    expect(screen.queryByRole("link", { name: /^shadow$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /crypto shadow/i })).not.toBeInTheDocument();
  });

  it("resolves /crypto itself to the research desk", async () => {
    await renderAppAt("/crypto");

    expect(cryptoHeading()).toBeInTheDocument();
    expect(boardHeadline()).toBeNull();
  });

  it("renders neither page on a path with no route", async () => {
    await renderAppAt("/no-such-route");

    expect(cryptoHeading()).toBeNull();
    expect(boardHeadline()).toBeNull();
    expect(screen.getByRole("link", { name: /^crypto$/i })).toBeInTheDocument();
  });
});
