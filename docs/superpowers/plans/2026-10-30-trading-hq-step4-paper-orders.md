# Trading HQ Step 4: Automated paper orders per idea — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A live idea Kevin switches on gets its confirmed rule traded automatically in the Alpaca **paper** account:
each trading morning the hub works out what the idea should hold today, and places market-on-open paper orders
for the difference. It is off by default, per idea, behind a server-wide switch, and every order or skip is logged.

**Architecture:** One new module is the only order path in the codebase. It is hard-wired to the paper host and
may POST to `/v2/orders` only. A pure planner turns (idea rule, prices, the idea's current shares, account
equity, every position) into orders or skips. A weekday-morning job runs the planner for each switched-on idea and
records every decision in an append-only table. The Workshop gets the per-idea switch and the order log.

**Tech Stack:** FastAPI, pandas, `requests` (Alpaca paper REST), Supabase, React/TS, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-trading-hq-design.md` (§2 goals and non-goals, §3 paper-only, §4.7
step 4, §5: the 25% per-position limit enforced on every order). Step 3 plan:
`docs/superpowers/plans/2026-10-30-trading-hq-step3-ideas-record.md`.

## Global Constraints

- **Paper only, ever.** The only host any order goes to is `https://paper-api.alpaca.markets`. Tests fail if any
  file in `tradehub/` names the live host, if any module other than `tradehub/portfolio/paper_orders.py` issues
  POST/PATCH/PUT/DELETE to Alpaca, or if `paper_orders.py` sends anything except POST `/v2/orders`.
- **Off by default, two switches.** Orders go out only if the server env `TRADEHUB_PAPER_ORDERS=on` is set **and**
  the idea's own switch is on. Either one off means zero POSTs.
- **Only ideas that passed both gates:** `live_at` set and `killed_at` null.
- **The 25% limit is checked on every order.** If an order would leave any symbol's total position in the
  account (all ideas plus manual) above 25% of equity, it is not sent and the skip is logged with the reason.
- **Every decision is recorded** in the append-only `paper_orders` table (DB trigger, like `idea_runs`):
  sent, skipped or rejected, with the reason. Nothing is ever edited.
- **Same rule as the backtest and the shadow track:** the target comes from `engine` (prior-close data, FRED lagged
  one more day), from the idea's `live_run_id` spec.
- Order tag `idea-<id>-auto-<YYYYMMDD>-<SYMBOL>`. It is unique per idea, day and symbol, so a re-run the same
  morning cannot double-order: Alpaca refuses a duplicate `client_order_id`, and that counts as already sent.
- The site banner changes from "Places no orders" to a paper-only line (spec §3).
- Routes go directly on `app`. Migrations are recorded in `docs/superpowers/plans/migrations-applied.md`.
- Gate: pytest, `ruff --select F` (pre-existing findings only), tsc, eslint, and **vitest with
  `VITE_SUPABASE_URL=` blanked** (CI has no Supabase env; this broke the step 3 deploy).

## Rulings in this plan (Kevin can overturn)

- **Timing: market-on-open.** The job runs at 12:30 UTC Mon-Fri (7:30 or 8:30 New York) and sends `time_in_force:
  "opg"` market orders for today's open. The rule decides today's holding from yesterday's close, so this is the
  first price at which the decision can be acted on. The shadow track measures close to close, so real fills will
  differ from it a little; both are shown.
- **Skip non-trading days** via `GET /v2/calendar` for today. A holiday morning sends nothing and logs one skip.
- **Size:** the idea's `size_pct` (set at go-live) × current account equity, split equally across `hold`. The
  `otherwise` ticker gets the full size; `CASH` means zero. Whole shares only, rounded down (`opg` orders cannot
  be fractional).
- **Current shares** come from the step 3 attribution (`open_lots` by idea id, tags plus relabels). The order is
  the difference between target and current. Differences under 1 share, or under $100, are skipped as noise.
- **Kill and switch-off:** killing an idea, or switching its orders off, sends closing orders for the shares the
  idea holds at the next morning run. The idea then never trades again. Positions are not abandoned unlabelled.
  If Kevin would rather keep them open, this is one flag.
- ~~No shorting~~ **Overturned by Kevin 2026-10-30: short plays and order types are in.** See the amendment below.
- Switch changes are appended to `order_switches` (who, when, on/off), so the history is visible.

## Review Focus

1. The job runs twice the same morning, or after a crash mid-loop → no duplicate orders; Alpaca's duplicate
   client-id 422 is logged as `already sent`, not as an error.
2. Alpaca is down, keys are rejected, or one symbol has no price → that idea logs `rejected` or `skipped` with the
   reason, the other ideas still run, the job exits 1, and nothing is half-sent.
3. Two ideas want the same symbol → each sizes against its own lots; the 25% check uses the account's total for that
   symbol including the other idea's pending order from the same run.
4. Equity is $0 or the account isn't connected → no orders and one `skipped: account not connected` row.
5. A manual (untagged) position in a symbol an idea also trades → the idea only ever sells shares it owns, never
   Kevin's manual shares.

## Amendment (Kevin, 2026-10-30): shorts and order types

Kevin asked for short plays and for order types (limit, market-on-close and others) as part of the strategies.
**Task 0** comes before Task 1.

- **Shorts:** `IdeaSpec.short: list[str]` (0-5 tickers), held short while the rule is "on". Legs are
  equal-weighted across `hold` + `short`. A short leg's daily return is `-r` (rebalanced daily, like the long
  legs), and borrow cost is covered by `cost_bps`. `hold` may be empty if `short` is not; a ticker can't be in
  both. `otherwise` stays long or CASH.
- **Execution:** `IdeaSpec.execution = {order_type: "market"|"limit", timing: "open"|"close"|"day",
  limit_offset_bps: 0-500}`, with default market at the open. Timing maps to Alpaca `time_in_force` opg / cls /
  day, so this covers MOO, MOC, LOO, LOC, and day market or limit.
  - A limit price is the last close moved against us by the offset (buy below it, sell above it), rounded to
    cents.
- **Honest backtest:** `timing: "close"` adds one more day of lag to the condition in the engine, because a
  market-on-close order fills at the close a day after the decision. Open and day timing stay close-to-close (the
  approximation is written into the draft's assumptions). A limit order may not fill. The next morning's plan
  retries from the actual shares, and the backtest assumes a fill (stated as an assumption).
- **Ruling: no stop, trailing-stop or bracket orders in this step.** The backtest runs on daily closes and cannot
  model an intraday trigger. A stopped-out paper record would be measured against a rule that was never tested.
  It needs an engine change first (a later step).
- **Planner:** signed targets. A long-to-short flip in one symbol is two orders (close, then open), because
  Alpaca won't reverse a position in one order. Tags carry a suffix: `idea-<id>-auto-<YYYYMMDD>-<SYMBOL>-<close|open>`.
  The 25% check uses absolute market value.

### Task 0: Spec, engine and editor for shorts and execution

**Files:** `tradehub/workshop/spec.py`, `tradehub/workshop/engine.py`, `tradehub/workshop/draft.py` (SYSTEM),
`market_sentiment_tool/src/lib/workshop.ts`, `src/pages/WorkshopIdea.tsx`; tests `tests/test_workshop_spec.py`,
`tests/test_workshop_engine.py`, `src/pages/Workshop.test.tsx`.

- [ ] Tests:
  - Spec:
    - Short-only is valid.
    - A ticker in both `hold` and `short` → error.
    - Empty `hold` + empty `short` → error.
    - Execution defaults; a limit offset with a market order is allowed but ignored.
    - Old specs without the new fields load unchanged.
  - Engine:
    - A short leg of a falling planted asset → `beats_benchmark` PASS on synthetic data.
    - Pair `hold=[A]`, `short=[B]` returns `(rA - rB)/2`.
    - `timing: close` shifts the mask one extra day vs `open`.
    - `tickers_for` includes short legs.
  - Editor: a "Short (tickers)" field and an "Orders" select round-trip into the spec posted to `/runs`.
- [ ] FAIL → implement → PASS → commit `feat(workshop): short legs and execution timing in the idea spec`.

---

### Task 1: The one order path (paper only)

**Files:**
- Create: `tradehub/portfolio/paper_orders.py`
- Modify: `tests/test_portfolio_alpaca_paper.py` (guard tests)
- Test: `tests/test_paper_orders.py`

**Interfaces:**
- Produces: `orders_enabled() -> bool` (true only when env `TRADEHUB_PAPER_ORDERS == "on"`);
  `submit(symbol: str, qty: int, side: Literal["buy","sell"], client_order_id: str, *, order_type="market",
  time_in_force="opg", limit_price: float | None = None, session=requests) -> dict`, which POSTs
  `PAPER_BASE + "/v2/orders"` with `{"symbol","qty","side","type","time_in_force","client_order_id"}`, plus
  `limit_price` for limit orders. Any order type other than market or limit is refused. It raises `OrdersDisabled` when the switch is off, `AccountNotConnected` on 401/403, and
  `DuplicateOrder` on 422 with "client_order_id must be unique". Other errors raise `requests.HTTPError` with the
  status only. The key is never in a message.
- Reuses `PAPER_BASE` and `_headers` from `alpaca_paper.py` (a second host string is not allowed).

- [ ] **Step 1: Tests**
  - `test_disabled_by_default` (env unset → `OrdersDisabled`, session never called).
  - `test_posts_one_opg_market_order_to_paper` (exact URL and JSON).
  - `test_duplicate_client_id_is_DuplicateOrder`.
  - `test_rejected_keys_not_connected_without_leaking`.
  - Guard tests:
    - `test_only_paper_orders_module_writes_to_alpaca`: regex over `tradehub/**/*.py` for `.post(`, `.put(`,
      `.patch(` or `.delete(` in any file that names `alpaca`; only `paper_orders.py` may match.
    - `test_paper_orders_posts_only_to_orders_path`: source contains exactly one `.post(` and the path
      `"/v2/orders"`.
    - The existing live-host test is unchanged.
- [ ] **Step 2:** run, expect FAIL. **Step 3:** implement. **Step 4:** run, expect PASS.
- [ ] **Step 5: Commit** `feat(portfolio): the one paper-only order path, off by default`.

### Task 2: Planner (pure)

**Files:**
- Modify: `tradehub/workshop/engine.py`
- Create: `tradehub/portfolio/autotrade.py`
- Test: `tests/test_autotrade.py`, `tests/test_workshop_engine.py` (add)

**Interfaces:**
- `engine.target_today(spec, closes, fred) -> dict[str, float]`: weights for today from data up to the last
  close. Hold tickers get `1/len(hold)` each when the condition holds, otherwise `{otherwise: 1.0}` or `{}` for
  CASH. It appends one phantom next business day to the frame and reads `condition_mask` there, so the lag rule is
  the engine's own.
- `autotrade.plan(idea_id: int, weights: dict[str, float], size_pct: float, equity: float, prices: dict[str,
  float], held: dict[str, float], book: dict[str, float], day: date) -> list[dict]`. Each row is
  `{symbol, side, qty, client_order_id, status: "send"|"skip", reason}`.
  - `held` is this idea's shares; `book` is account-wide market value per symbol.
  - Sells come before buys, so a switch frees cash first.
  - The 25% check uses `book` plus earlier orders in this plan.
  - `close_out(idea_id, held, day)` produces the sell rows for kill/off.

- [ ] **Step 1: Tests**
  - Engine: `test_target_today_uses_yesterdays_close` (price condition flips on the last close → today's target
    flips; changing only a value after the last close changes nothing). Also `test_fred_target_lags_one_more_day`.
  - Planner:
    - Equal split with whole shares rounded down.
    - Switch to `otherwise` produces sell rows before buy rows.
    - Under 1 share or under $100 → skip with reason "too small".
    - 25% breach → skip naming the % (the account total includes another idea's shares).
    - Never sells more than `held` (manual shares untouched).
    - Negative target → 0.
    - `close_out` sells exactly `held`.
    - Tags match `idea-7-auto-20261102-GLD`.
- [ ] **Steps 2-4:** FAIL → implement → PASS. **Step 5: Commit** `feat(autotrade): today's target and the order
  plan`.

### Task 3: Switch, order log, migration

**Files:**
- Create: `market_sentiment_tool/supabase/migrations/20261031000002_paper_orders.sql`
- Modify: `tradehub/workshop/store.py`, `docs/superpowers/plans/migrations-applied.md`
- Test: `tests/test_workshop_store.py` (add)

**Interfaces:**
- SQL:
  - `ideas` gains `auto_orders boolean not null default false`. The step 3 lifecycle trigger is unchanged.
  - `auto_orders` may only be true while `live_at` is set and `killed_at` is null (trigger).
  - `order_switches(id, idea_id, on boolean, by, at)`, append-only.
  - `paper_orders(id, idea_id, day date, symbol, side, qty, client_order_id, status check in
    ('sent','already sent','skipped','rejected'), reason, alpaca_order_id, at)`, append-only, RLS on.
- Python:
  - `set_auto(supa, idea_id, on, by)` updates and appends to `order_switches`.
  - `auto_ideas(supa)` returns ideas with `auto_orders` on.
  - `closing_ideas(supa)` returns ideas switched off or killed that still have open auto shares.
  - `log_orders(supa, rows)` and `order_log(supa, idea_id, limit=100)`.

- [ ] **Steps:** tests → FAIL → implement → apply with Supabase MCP → rolled-back probe (switch on for a non-live
  idea blocked; edit/delete of a `paper_orders` row blocked) → record → PASS → commit `feat(autotrade): per-idea
  switch and append-only order log`.

### Task 4: Morning job

**Files:**
- Create: `tradehub/scripts/paper_orders_run.py`
- Test: `tests/test_paper_orders_run.py`

**Interfaces:**
- `run(now, supa, *, get=paper_get, submit=paper_orders.submit, closes=data.closes, fred=data.fred_series) ->
  (summary: dict[int, dict], failed: dict[int, str])`.
- Order of work:
  1. Calendar check.
  2. Account equity, positions and fills, read once.
  3. For each idea from `auto_ideas`: build the plan with `target_today` and `plan`.
  4. For each idea from `closing_ideas`: build `close_out`.
  5. Submit `send` rows in plan order. Log every row with its outcome: `DuplicateOrder` → `already sent`; an HTTP
     error → `rejected` with the status; the master switch off → `skipped: TRADEHUB_PAPER_ORDERS is off`.
- An exception in one idea is caught and recorded, and the loop goes on.
- `main()` exits 1 if any idea failed.

- [ ] **Step 1: Tests**
  - A holiday → no POST, one skip row.
  - Master switch off → no POST, rows `skipped`.
  - A happy path sends in order.
  - A re-run sends again and the 422 is logged `already sent`.
  - One idea's missing price doesn't stop another.
  - A killed idea with shares gets closing sells, then nothing the next day.
  - Account not connected → one skip, no POST.
- [ ] **Steps 2-4:** FAIL → implement → PASS. **Step 5: Commit** `feat(autotrade): weekday-morning order job`.

### Task 5: API and Workshop UI, banner

**Files:**
- Modify: `tradehub/api/main.py`, `market_sentiment_tool/src/pages/WorkshopIdea.tsx`,
  `market_sentiment_tool/src/lib/workshop.ts`, `market_sentiment_tool/src/App.tsx` (banner)
- Test: `tests/test_workshop_api.py`, `market_sentiment_tool/src/pages/Workshop.test.tsx`,
  `market_sentiment_tool/src/App.routes.test.tsx`

**Interfaces:**
- `POST /api/workshop/ideas/{id}/auto {on: bool}` (admin) → 409 unless live and not killed when turning on.
- `GET /api/workshop/ideas/{id}` adds `auto_orders`, `orders_enabled` (the server switch), and `orders` (latest 50
  log rows).
- Workshop live panel:
  - The "Automatic paper orders" switch. Turning it on asks for confirmation and states the size and the 25% rule.
  - A note when the server switch is off.
  - The order log table: day, symbol, side, qty, status, reason.
- Banner: "Paper orders only — never real money." (the App route test asserts the new line).

- [ ] **Steps:** tests → FAIL → implement → PASS (vitest with Supabase env blanked) → commit
  `feat(autotrade): Workshop switch, order log, paper-only banner`.

### Server step (Kevin's terminal tab; prod change; only after deploy)

- [ ] Add `paper-orders)` to `/opt/stack/bin/tradehub-job`, plus `tradehub-paper-orders.service` and `.timer`
  (`OnCalendar=Mon..Fri *-*-* 12:30:00 UTC`, `Persistent=false`, so a late boot never sends stale opening
  orders).
- [ ] Compose forwards `TRADEHUB_PAPER_ORDERS`. It is **left unset (off)** until Kevin turns it on with
  `scripts/set-vps-secret.sh TRADEHUB_PAPER_ORDERS` and types `on`.
- [ ] Verify with a manual run (switch off → rows `skipped`, zero POSTs).
