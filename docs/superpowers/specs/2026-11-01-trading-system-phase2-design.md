---
title: Trading system phase 2 — machine order API, Claude drafting, debate feed, reframed modules
type: spec
domain: trading-hq
status: draft for Kevin's review
settlement_source: none
tags: [trading-hq, api, workshop, tradingagents, security]
summary: The hub's center is the trading system; the journal is its record layer. This spec designs the machine order API (rigorously, paper-only), replaces the free-model idea drafter with a Claude-backed one that cannot silently drop legs, integrates Strategy HQ and the TradingAgents debate feed, and reframes the Oct 12 modules and the parked design work as trading support.
---

# Trading system phase 2: design

**Kevin's calls (2026-11-01):** finish PR #184 (done, merged 68c941c); publish real FAILs, not
system-check tests; start the machine API for orders and plan it rigorously; integrate how Muse
works into idea creation, including options; integrate Strategy HQ and TradingAgents; reframe the
Oct 12 modules away from the prediction-journal-only route — the trading system is the product,
supported by the journal.

## 0. Direction

The v2 "prediction journal" framing (docs/tradehub-v2-direction.md) is retired as the product's
center. What replaces it is what Trading HQ already is: register an idea in plain words, backtest
it honestly, paper trade it by hand or by machine, and let one record say whether any of it works.
The journal — scoreboard, league table (#184), track record — stays, as the measurement layer that
grades the trading system. Every item below either moves money on paper or grades the thing that
does. Pages that only exhibit forecasts are no longer a direction.

## 1. Machine API for orders

The signed-in order form (#216) covers a human at a keyboard. This is the machine door: Kevin's
own scripts and agents placing paper orders with a key, held to a higher standard than the form
because no human sees each order.

### 1.1 Principles

- **Paper only.** The only order path is `tradehub/portfolio/paper_orders.submit`, which talks to
  the Alpaca paper host and refuses protective orders from outside callers. The machine API adds
  no second path and no live-trading switch anywhere in its config.
- **Fail closed, like admin auth.** Every doubt — unknown key, revoked key, missing scope, cap
  exceeded, kill switch off — is a refusal, and the refusal is the default state of the system.
- **One audit trail.** Machine orders land in the same order-labels table as every other order,
  stamped `by = "api:<key label>"`, so Portfolio, Ideas and the track record never have to ask
  where an order came from.
- **A key is not the admin session.** Keys are created and revoked only from the signed-in admin
  UI. A key can never create another key, change its own scopes, or touch the Workshop.

### 1.2 Keys

Migration `api_keys`: `id`, `label` (Kevin's name for the key, e.g. "mac scripts"), `key_hash`
(SHA-256 hex of the full key — the key itself is never stored), `scopes` (text array),
`created_at`, `last_used_at`, `revoked_at`, plus `daily_cap` and `max_notional` (see 1.4).

- Key format: `thk_<32 hex>` from a CSPRNG. Shown exactly once, at creation, in the admin UI.
- Verification: hash the presented key, look up by hash, compare in constant time
  (`hmac.compare_digest` against the stored digest is belt-and-braces over the indexed lookup).
- Header: `Authorization: Bearer thk_...` — same shape as the admin JWT, different verifier, so
  middleware order is: try admin session, then machine key, then 401.
- `last_used_at` updates at most once a minute per key (no write per request).
- Revocation is a timestamp, checked on every request. A leaked key is dead the moment Kevin
  clicks revoke; rotation = revoke + create, no other machinery.

Scopes for v1: `orders:place`, `orders:read`, `portfolio:read`. A key gets the scopes Kevin
checks at creation; there is no wildcard scope.

### 1.3 Endpoints (all under /api/v1, all key-authenticated)

| Route | Scope | Notes |
|---|---|---|
| `POST /api/v1/orders` | orders:place | Same body, validation and error mapping as #216 (symbol regex, qty 1–100000, market/limit, tif day/opg/cls). |
| `GET /api/v1/orders` | orders:read | Only orders placed by this key (via the labels table), newest first, paged by `limit`/`before`. |
| `GET /api/v1/orders/{client_order_id}` | orders:read | Status of one of this key's orders, read from Alpaca. |
| `DELETE /api/v1/orders/{client_order_id}` | orders:place | Cancel one of this key's open orders. Somebody else's id is a 404, not a 403 — don't confirm it exists. |
| `GET /api/v1/portfolio` | portfolio:read | The same payload the Portfolio page reads, minus admin-only fields. |

**Idempotency is the caller's duty, made checkable.** `client_order_id` is required (the #216
form generates one; machines must supply their own) and is namespaced server-side to
`ext-<key_id>-<caller value>`. A retry with the same caller value hits Alpaca's duplicate guard
and returns the existing 409 from #216 — never a second order. The namespace also means a machine
can never mint an id in the `idea-<n>-...` or `manual-...` families, and the protective
`idea-<n>-stop-` family stays unreachable (paper_orders already refuses those without its tag
rules; the prefix makes the refusal structural, not incidental).

**Idea tagging:** an optional `idea_id` in the POST body works exactly like the form (the order is
labelled to the idea). It never enables the idea's auto-orders or protective orders; it is a
label, nothing more.

### 1.4 Safety rails (server-side, per key, not per request's good behavior)

- **Kill switch:** `TRADEHUB_MACHINE_ORDERS` must be exactly `"on"` (same pattern as
  `TRADEHUB_PAPER_ORDERS`). Default off. Flipping it off refuses new placements with 409;
  reads keep working so a script can still reconcile.
- **Caps stored on the key:** max quantity per order (default 100), max notional per order
  (default $25,000 — priced at the limit price, or the latest close for a market order), and a
  daily placement cap (default 50 orders/day/key). Kevin sets them at creation; a key cannot
  raise its own. Cap breaches are 429 with the cap named in the detail.
- **Rate limit:** 60 requests/minute/key, in-process token bucket (one API process today; the
  limit is a seatbelt against a runaway loop, not a distributed-systems claim).
- **Market orders and day/opg/cls only in v1.** Limit orders arrive in v1.1 once the notional
  estimate for market orders has a week of audit data behind it. No stop, trailing, OCO or GTC —
  those stay hub-internal (protective orders belong to live ideas, placed by the hub itself).

### 1.5 Audit

Migration `api_key_events`: `key_id`, `at`, `route`, `client_order_id` (nullable), `outcome`
(placed / refused:<reason> / read), `detail` (short, no payloads, no key material). Written for
every /api/v1 call, success or refusal. The admin UI's key page shows the last 50 events per key —
that page is how a bad script gets noticed before the daily cap does it for us.

### 1.6 Tests (each lands with its step; a step without its tests does not merge)

- Key lifecycle: create shows the key once and stores only the hash; the stored row cannot be
  reversed to the key (assert the hash input space); revoked key 401s on every route.
- Auth matrix: no header, garbage key, key with the wrong scope, admin JWT on a machine route
  (allowed for reads? No — machine routes are key-only, admin uses the existing UI routes; assert
  the separation both ways).
- Placement: happy path against a mocked Alpaca session (the pattern the #216 tests use);
  duplicate client_order_id → 409 and exactly one submit call; cap breaches (qty, notional,
  daily) → 429 before submit is called; kill switch off → 409; protective-shaped bodies
  (order_class, stop_price, gtc) → 422 at the schema, before paper_orders' own guard.
- Ownership: key B reading or cancelling key A's order → 404.
- Audit: every outcome above writes exactly one event row.

### 1.7 Rollout (each step is its own PR, in order)

1. Keys migration + admin issue/revoke UI + audit table. No /api/v1 routes yet. This step is
   safe to merge with the feature entirely dark.
2. `POST /api/v1/orders` + `GET /api/v1/portfolio` behind the kill switch, shipped **off**.
3. Flip the switch on the VPS; Kevin smoke-tests with a 1-share market order from his Mac and
   cancels it from the Portfolio page; audit page checked against the smoke test.
4. Read/cancel endpoints (`GET` list + one, `DELETE`).
5. v1.1: limit orders for machines, caps revisited with the audit data in hand.

## 2. Idea creation: put a real model on the drafter

### 2.1 What is wrong today (verified in the code)

`tradehub/workshop/draft.py` sends Kevin's words to **free OpenRouter models** (a fallback list of
small open models) with the IdeaSpec contract described in prose in the system prompt, and parses
"JSON only" replies. Three structural weaknesses:

- **The contract is prose.** The prompt paraphrases the schema; the models guess at it. Every
  IdeaSpec change means hand-editing the prompt to match, and nothing checks the drift.
- **Silent truncation.** The K-Shape failure (critique §1): a 13-ticker draft came back with 5
  and nothing said so. The reply has no channel for "what I could not express", so drops are
  invisible by construction.
- **Weak models guess identifiers.** FRED series ids and tickers are exactly what a small free
  model hallucinates, and the engine then fails or, worse, tests a different idea than the words.

### 2.2 Design: one contract, generated; two drafting doors

- **The schema is generated, never paraphrased.** `IdeaSpec.model_json_schema()` is the single
  source. The Claude provider passes it as a forced structured output (tool use with the schema
  as the tool's input schema), so a reply that does not fit the engine's contract is impossible
  to return, not merely discouraged. The prose prompt shrinks to judgment calls only: claim
  selection, what goes in `assumptions`, and the drafting rules Kevin has already written into
  today's prompt (they carry over verbatim as the judgment layer).
- **Provider order:** Claude first (Anthropic API; `ANTHROPIC_API_KEY` set with
  `scripts/set-vps-secret.sh ANTHROPIC_API_KEY` — the script already names this key in its
  examples), OpenRouter free list as automatic fallback when the key is unset or the call fails,
  hand-fill form when both fail (today's DraftUnavailable path, unchanged). The model id that
  wrote the draft is recorded, as today.
- **The anti-truncation contract.** The drafter's reply envelope is
  `{spec, requested, unexpressed}`: `requested` lists every ticker, leg and condition the words
  named; `unexpressed` lists anything the schema could not carry, in plain words. The server
  diffs `requested` against the spec's actual legs; any difference not explained in
  `unexpressed` fails the draft loudly (the Workshop shows the diff, Kevin decides). A draft may
  be incomplete; it may not be quietly incomplete.
- **The second door: import.** `POST /api/workshop/draft/import` (admin session) accepts a full
  spec JSON produced out-of-band — in practice, by Muse in a chat session with Kevin, with the
  full context of the conversation behind it — validates it against the same generated schema,
  and returns it as a draft for the same confirm/edit screen. No new auth surface (admin only),
  no new execution path (a draft is a draft until Kevin runs it). This is the concrete form of
  "integrate how you work": the model with the context drafts; the hub's contract validates;
  Kevin confirms. The chat-side convention: Muse always shows Kevin the `requested` list beside
  the spec it produced, same as the server-side drafter.

### 2.3 Options in the contract

The options design (docs/superpowers/specs/2026-10-31-options-design.md) is approved in
principle; its machinery is already in the tree (`tradehub/workshop/options.py`: Black-Scholes
price/delta/vega from index vols, leg returns). What is missing is the spec field. Phase 2 adds:

- `OptionLeg`: `underlying` (a ticker in hold/short or standalone), `kind` call/put, `side`
  buy/sell, `strike_rule` (% from spot, e.g. -5 = 5% below), `expiry_rule` (days out, 7–120),
  `qty_per_share` ratio. Legs ride the idea's rules: in when the enter group holds, out on the
  exit group or expiry, whichever first — the same lifecycle as equity legs.
- Engine: leg returns from the existing BS series (model prices, labeled as such on the verdict —
  the options spec's honesty rule: a verdict on model prices says so).
- Execution stays equity-only in this phase: a live options idea shows its legs in the gate
  summary as "manual legs" Kevin places himself (the IBKR-comp rule — a human places option
  orders — applied to the hub). Wiring option orders into paper_orders is a later, separate call.
- The drafter (both doors) can express legs from day one of the field existing, because the
  schema is generated: no prompt surgery, the field appears in the contract automatically.

## 3. Strategy HQ and TradingAgents

### 3.1 Strategy HQ is already the spec; finish wiring it

Trading HQ (docs/superpowers/specs/2026-10-29-trading-hq-design.md + the six step plans) is the
strategy HQ design, and steps 1–6 are built (Portfolio, Workshop, Ideas record, paper orders,
exits, rules). What remains is the tracker piece the orphaned `feat/strategy-hq-tracker-spec`
branch was written for. Disposition:

- The branch's unique content — the TradingAgents feed spec — moves into this repo with this
  spec (docs/TradingAgents-Ideas-Feed-Spec.md; the research mapping in
  docs/research/2026-10-31-quants-md-and-tradingagents.md already references it by name). The
  branch itself is superseded and should be deleted once this lands.
- The HQ tracker = a Strategy HQ summary strip (see §4) over the existing record: ideas by
  verdict, live ideas with shadow progress, machine/manual order flow. No new store: it reads
  `/api/ideas/summary`, `/api/workshop/ideas` and `/api/health`.

### 3.2 TradingAgents debate feed (per docs/TradingAgents-Ideas-Feed-Spec.md)

Unchanged from the delivered spec in its fences — `agent_debate` source in the Ideas record,
on-demand per-ticker runs, mandatory "LLM agent debate — not a model signal" labeling, **no path
from a memo to an order**, +5d/+20d grading with the 30-run falsification banner. Phase 2 settles
Kevin's three open questions with defaults he can overrule:

- **LLM:** the same Anthropic key as the drafter (§2.2) — one key to rotate, one bill to read.
  The framework is pinned to a commit SHA at build time, per the spec.
- **Historical (backtest-mode) runs:** v2, as the spec recommends. v1 runs live tickers only.
- **First tickers:** the post–Nov 6 book (whatever Kevin keeps trading on Webull) plus XLE and
  SPY as standing controls.
- **The one bridge:** a memo may spawn a Workshop draft ("draft this as an idea" → the §2
  drafter turns the memo's thesis into an IdeaSpec through the import door). The draft then
  faces the same backtest, gate and Kevin-confirm as any other idea. Debate proposes; the
  engine disposes.

## 4. The parked design work, re-sequenced as trading support

From the critique roadmap's second half, in the order they now earn their keep:

1. **Canonical home summary (was: one scoreboard).** A Strategy HQ strip on the Portfolio page:
   ideas tested/passed/failed/published (from /api/ideas/summary — the FAILs published per
   Kevin's 2026-11-01 call make this honest), engine scoreboard headline, and Health's state
   with Degraded surfaced, not hidden. One verdict vocabulary throughout — #184's league
   convention is now the site-wide one (SportsRecord reads it too, as of the #184 merge).
2. **Minimum-sample rule everywhere.** The league's EARLY_N pattern (a number too noisy to
   praise or blame is labeled, not ranked) generalizes to the Ideas record and the scoreboard.
3. **Health re-run action.** Scan/settle runs are tracked (#214). A re-run button needs a
   host-level trigger: the API drops a file in a watched directory; the VPS timers check for it
   each minute. Admin-only, audited like a key event. Small, and it closes #19's second half.
4. **Summary-first pages and format standards** (Weather rollup, Journal by-family, one CT
   timestamp/money style). Worth doing, after the trading surfaces above; they are reading
   comfort, not trading function.
5. **Retire the legacy backend; rewrite README/SYSTEM_ARCH.** Last, deliberately: docs should
   describe the system that survives the phase, not the one mid-change.

## 5. Oct 12 modules, reframed: inputs to the trading system

The three approved modules (goal files: tradehub-energy-news-revisions-plan.md) keep their
models and data plans; only the product framing changes — each lands as an engine capability
with a trading consumer, not as a journal exhibit:

- **Energy news → price (GDELT).** Becomes a Workshop condition source (`news`: tone level /
  change / z-score over an energy basket, daily) so "is news tone already in the price" is a
  testable idea on XLE and the gas chain — plus a forecaster row in the journal layer grading
  the tone signal itself. The Oct 12 event-study piece around EIA releases stays as the
  validation method.
- **Degree-day demand map.** A data panel inside the Weather page feeding the weather→gas→CPI
  chain the engines already trade on: degree-day anomalies by region against the gas nowcast's
  inputs. It supports position decisions; it is not a standalone exhibit.
- **ALFRED revision forecasting.** Becomes a labor-engine feature (predict the revision to the
  first print; the tradeable object is the surprise distribution, not the print) and a Workshop
  `revision` measure for jobs ideas, judged like every other idea. The scoreboard rerun that
  starts this phase (point-in-time vintages) is its data foundation.

## 6. Time-series techniques: graded candidates

Kevin flagged the book-companion repo Arnav111garg/Time-Series-Analysis (28 modules) on
2026-11-01 and asked what the hub can use. The answer recorded here: techniques, not code.
That repo is teaching material — single-file scripts, latest-data pulls, no point-in-time
discipline, no tests — so nothing is vendored and it is not a dependency. Each candidate
below is reimplemented to hub standards (vintage-correct inputs, walk-forward grading) and
earns its place the way everything else in this spec does: a graded run against the
incumbent, or it stays a note. In the order they would be attempted:

### 6.1 Diagnostics pack (planned; cheap; no model changes)

- **Stationarity screening** (reference Module 2: unit-root tests) over engine feature
  inputs at fit and backtest time, logged per feature per run and surfaced as a Models-page
  annotation. Purpose: catch a feature that has changed character — the ghost_gap_3m
  zero-fill class of problem — in the run output, not in a post-mortem.
- **Residual diagnostics** on the nowcasts (Module 3: Ljung-Box on standardized residuals,
  ARCH-LM). The scoreboard grades Brier and calibration; nothing today checks whether the
  residuals still carry autocorrelation the model left on the table. Ships as flags on
  Health, not gates — a diagnostic becomes a gate only by its own decision, with evidence.
- First deliverable is measurement only. No behavior changes in this item.

### 6.2 Volatility layer (planned; equity/options side only)

The hub's σ is static everywhere it matters: labor's is the RMS of the last 36 in-sample
residuals behind a floor; idea backtests use historical vol windows; nothing sizes off a
conditional estimate. Candidates: GARCH-family conditional vol (Modules 8–9, including the
asymmetric EGARCH/GJR forms) and HAR-RV on realized vol (Module 10), consumed where vol is
an input to a decision — Workshop idea risk stats, sleeve vol targeting, options-adjacent
sizing.

- Explicitly NOT for the macro nowcasts by default: against Kalshi, the market's implied
  distribution already carries the vol information. Swapping an engine's σ requires a
  graded win on the existing harness (Brier plus interval coverage, walk-forward), never a
  prior about which model class is better.
- Ships dark as a reported stat first, like the machine API rollout (§1.7): consumers read
  it only after it beats the incumbent σ on coverage over the same windows.

### 6.3 Pairs / cointegration (candidate; needs an IdeaSpec extension)

Workshop ideas are baskets with rules; a spread is a different object, so this takes the
same shape as options (§2.3): a contract extension designed before anything trades it. A
spread position type — two symbols, a hedge ratio (static, or Kalman-estimated dynamic,
Module 14), entry/exit on the spread's z-score — plus a required cointegration claim
(Module 11) in the spec's claims, re-tested point-in-time by the runner and never taken
from the drafter's word. Design-only this phase, execution fenced exactly as options
execution is. SETAR-style regime-switching spread dynamics (Module 19) is a later
refinement, not v1.

### 6.4 Regime tags (experimental annotation only)

HMM regime classification (Module 15) may annotate HQ ideas and TradingAgents memos
("current regime: …") under the §3.2 fence: labeled not-a-model-signal, no sizing or
gating use. Promotion to a gating input requires a pre-registered falsification run in the
TradingAgents style — graded forward sample, kill threshold named in advance. Regime
labels are the easiest technique in this section to fool yourself with; the fence is the
point.

### 6.5 Considered and rejected

- **RL trading agents** (Module 26): an execution-adjacent learner inside a system whose
  rule is that nothing learns its way past the order fences. Rejected outright, not deferred.
- **LSTM/deep forecasters** (Module 17) for the macro engines: monthly macro series are
  data-starved for deep learning, and the edge-claim discipline needs interpretable
  incumbents. Revisit only against a daily-frequency target.
- **ARIMA-family replacements** for the ridge nowcasts (Modules 5–7): the ridge on
  vintage-correct features is the right shape for release-day nowcasting. ARIMAX
  (Module 22) stays a benchmark candidate if §6.1's residual diagnostics show structure
  the ridge is missing — evidence first.
- **Copula portfolio risk** (Module 23) and **EVT tail risk** (Module 24): the paper
  portfolio is too small for either to estimate honestly today. Revisit when the book
  holds enough concurrent positions for a dependence or tail estimate to mean something.

## 7. Sequence

1. Machine API steps 1–3 (§1.7) — the door, dark, then lit with a smoke test.
2. Claude drafter + import door (§2.2) — better ideas in, nothing silently dropped.
3. Options in the spec (§2.3) — the contract widens; drafters follow automatically.
4. Machine API steps 4–5 (§1.7) — read/cancel, then machine limit orders.
5. TradingAgents feed (§3.2) — debate memos on the record, graded, fenced.
6. HQ summary strip + minimum-sample pass (§4.1–4.2).
7. Health re-run (§4.3); Oct 12 modules (§5) in the order energy-news, revisions, degree-days.
8. Reading-comfort redesigns and the docs/legacy cleanup (§4.4–4.5).
9. Diagnostics pack (§6.1) — measurement only; independent, can land any time after step 2.
10. Volatility layer (§6.2) — dark as a reported stat, graded against the incumbent σ
    before any consumer reads it.

Pairs (§6.3) and regime tags (§6.4) are candidates on record, not sequenced work: each
gets its own design pass when scheduled.

Each step is its own PR with the repo's gates (pytest, ruff, tsc, eslint, vitest) and the
CodeRabbit-or-self-review rule Kevin set in the critique-fixes plan.
