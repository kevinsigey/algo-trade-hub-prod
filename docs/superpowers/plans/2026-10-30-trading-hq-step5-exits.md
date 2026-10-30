# Trading HQ Step 5: Exits (stop-loss, trailing stop, take-profit, time stop) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An idea can carry exits: a stop-loss %, a trailing stop %, a take-profit % and a time stop in days. The
backtest, the live-paper gate, the daily shadow track and the automated paper orders all apply them the same way.
After an exit, the idea stays out until a fresh signal.

**Architecture:** two parts. Each one ships on its own.
- **Part A, close-based exits.** Exits are checked at each close in the engine's one rule implementation (`_legs`
  / `daily_frame` / `target_today`). The exit-aware position then flows unchanged into the shadow job and the order
  planner. No new order kinds.
- **Part B, intraday stop orders,** as an option per idea. The backtest uses daily open/high/low to estimate an
  intraday trigger and fill. The order path gains real Alpaca `stop` / `trailing_stop` orders and the one extra
  request kind they need: cancelling a stop the hub placed.

**Tech Stack:** pandas/numpy (no numba; a plain loop with a time budget test), yfinance OHLC, Alpaca paper REST,
FastAPI, React/TS.

**Spec:** `docs/superpowers/specs/2026-10-29-trading-hq-design.md`, with Kevin's answers of 2026-10-30:
- Stop style: **both, per idea** (close-based first, intraday as an option).
- Exit kinds: **all four** (stop-loss %, trailing stop %, take-profit %, time stop in days).
- Re-entry: **the next fresh signal** (the condition turns off and back on).

Step 4 plan: `docs/superpowers/plans/2026-10-30-trading-hq-step4-paper-orders.md`.

## Global Constraints

- **One rule implementation.** The backtest, gate, shadow track and `target_today` all go through the same
  exit-aware path. No second copy of the exit logic anywhere.
- **No lookahead.** An exit is decided on the close of day t (or, intraday in Part B, at the moment the day's
  price crosses it), and takes effect with the idea's existing lag rules. Entry price, best price and days held
  come only from data up to that moment.
- **Paper only, as in step 4.** Part B adds exactly one request kind to `paper_orders.py`:
  `DELETE /v2/orders/{id}`, only for an order whose `client_order_id` starts with `idea-<id>-stop-`. Guard tests
  are updated to allow exactly that and nothing else.
- **Old specs load unchanged.** No `exits` field means no exits, and every existing verdict and shadow row keeps
  its meaning.
- **Every decision is logged.** An exit appears in the shadow row (`exit` reason) and in `paper_orders` (reason
  "stop-loss 8% hit", etc.).
- Gate: pytest, ruff F, tsc, eslint, vitest with the Supabase env blanked. A backtest with exits must finish in
  under 15 s on 20 years × 1,000 shuffles (budget test).

## Rulings in this plan (Kevin can overturn)

- **Exits are measured on the idea's sleeve, not per ticker** (Part A): the equal-weight basket of its hold and
  short legs, from the close it entered. A pair trade stops out as a pair. Part B's real stop orders are per
  ticker, so **intraday exits are only offered for single-leg ideas** (one ticker long or short).
- **An idea with no condition has no "fresh signal".** After an exit it re-enters after a **21-trading-day
  cooldown**. Without one, a stopped "always hold" idea would stay out forever.
- **While stopped out, the idea holds `otherwise`** (or cash), like any other "off" day.
- **Close-based exit fill:** the exit takes effect the same way a rule change does. With open/day timing the
  backtest scores from the next close-to-close day (step 4's accepted drift). With close timing it is one more day
  later, which matches market-on-close.
- **Shuffle test with exits:** the shuffled condition timing goes through the same exit logic, so the null
  includes the exits. Ideas with no condition keep the sign-flip test on the realised daily returns.
- **Trailing stop's best price** is the best close since entry (Part A). In Part B it is Alpaca's intraday
  high-water mark, and the backtest estimates that with daily highs.

## Review Focus

1. Exit then re-entry on the same day the condition flips back on → the idea re-enters only after the condition
   has been off for at least one day after the exit.
2. A gap through the stop (close-based: the close is far below; intraday: the open is below the stop) → the
   backtest uses the worse price (the open), never the stop price.
3. Shadow job catching up 5 missed days during which a stop hit → the rows reproduce exactly the backtest's
   path, with no reset of entry price or days held.
4. The morning job with an idea that exited yesterday while Kevin manually holds the same ticker → it closes only
   its own shares (step 4 rules still hold).
5. Part B: the rule exits on a day an intraday stop already fired → no double sell. The planner sees the
   stop's fill first, and the stale stop is cancelled before any closing order.

---

## Part A: Close-based exits

### Task 1: `Exits` in the spec and the editor

**Files:** `tradehub/workshop/spec.py`, `tradehub/workshop/draft.py` (SYSTEM: exits only when the idea names
them), `market_sentiment_tool/src/lib/workshop.ts`, `src/pages/WorkshopIdea.tsx`.
Tests: `tests/test_workshop_spec.py`, `src/pages/Workshop.test.tsx`.

**Interfaces:**
`Exits(BaseModel, extra="forbid")`, with all fields optional and `None` meaning off:
- `stop_loss_pct: float` in (0, 90]
- `trailing_pct: float` in (0, 90]
- `take_profit_pct: float` in (0, 1000]
- `max_days: int` in [1, 756]
- `mode: Literal["close", "intraday"] = "close"`

`IdeaSpec.exits: Exits = Exits()`. A validator rejects `mode="intraday"` unless the idea has exactly one leg.
Helper `Exits.any() -> bool`.

- [ ] Tests:
  - All four fields round-trip.
  - Bounds are enforced.
  - Intraday with two legs is an error.
  - Old specs load with no exits.
  - The editor has four optional number fields plus a mode select (intraday disabled unless there is one leg),
    and posts `exits` in `/runs`.
- [ ] FAIL → implement → PASS → commit `feat(workshop): exits in the idea spec and editor`.

### Task 2: Exit-aware position path in the engine

**Files:** `tradehub/workshop/engine.py`. Test: `tests/test_workshop_exits.py`.

**Interfaces:**
- `apply_exits(signal: np.ndarray, sleeve: np.ndarray, exits: Exits, cooldown: int | None) -> tuple[np.ndarray,
  np.ndarray]` returns `(held_mask, exit_reason)`.
  - `signal` is the lagged condition mask (bool per day). `sleeve` is the idea's daily sleeve return.
  - `exit_reason` is `""`, `"stop-loss"`, `"trailing"`, `"take-profit"` or `"time"` per day, set on the day the
    exit is decided.
  - The position is held while the signal is on and the idea isn't stopped out. Being stopped out lasts until the
    signal has been off for a day (fresh signal), or until `cooldown` days pass when there is no condition.
  - It is a plain loop, linear in the number of days.
- `_legs` / `daily_frame` / `run_test` / `target_today` call it when `spec.exits.any()`:
  - The extra lag for exits matches the signal lag (the exit decided at close t → off from t+1, +1 more for close
    timing).
  - `daily_frame` gains an `exit` column.
  - `run_test`'s shuffle builds each permutation through `apply_exits`.

- [ ] Tests:
  - A planted sleeve that drops 10% with a 8% stop exits on the first close at or below -8% and not before.
  - Trailing measures from the best close, not the entry.
  - Take-profit at +20%.
  - Time stop after N days.
  - No re-entry while the signal stays on; re-entry after an off-on.
  - A no-condition idea re-enters after 21 days.
  - Gap: one day at -30% with a 8% stop records the -30% day (the stop never caps a close-based loss).
  - `daily_frame` and `run_test` agree on the exit path.
  - `target_today` returns `{}`/otherwise the morning after a stop.
  - **Budget:** 5,000 days × 1,000 permutations with exits in < 15 s.
- [ ] FAIL → implement → PASS → commit `feat(workshop): close-based exits in the one rule implementation`.

### Task 3: Shadow track, records and orders carry the exit

**Files:** migration `20261031000003_shadow_exit.sql` (`idea_shadow_days.exit text`), `tradehub/scripts/ideas_shadow.py`,
`tradehub/workshop/record.py`, `tradehub/portfolio/autotrade.py` (reason text), `tradehub/scripts/paper_orders_run.py`.
Tests: `tests/test_ideas_shadow.py`, `tests/test_paper_orders_run.py`.

- [ ] Tests:
  - A catch-up run over 5 days that include a stop records the same `exit` day as `daily_frame` (Review Focus 3).
  - The morning after, the job sends the close with reason "stop-loss 8% hit".
  - Kevin's manual shares are untouched (Review Focus 4).
  - The public record shows exit days on the curve.
- [ ] Migration applied, probed and recorded. FAIL → implement → PASS → commit `feat(ideas): exits on the paper
  record and in the morning orders`.

### Part A ship: PR, review, merge, deploy (no server change).

---

## Part B: Intraday stop orders (single-leg ideas)

### Task 4: Daily bars (open/high/low/close)

**Files:** `tradehub/workshop/data.py`. Test: `tests/test_workshop_data.py`.
- `bars(tickers, start, *, download=None, cache_dir=None, now=None) -> dict[str, pd.DataFrame]` returns
  open/high/low/close per ticker, with the same last-complete-day cut and the same cache rules as `closes`.
  Cache files are `<T>.ohlc.csv`, so existing close caches are untouched.
- [ ] Tests: the columns; the partial bar is cut; the cache round-trips. FAIL → implement → PASS → commit.

### Task 5: Intraday exit model in the backtest

**Files:** `tradehub/workshop/engine.py`. Test: `tests/test_workshop_exits.py` (add).
- `apply_exits_intraday(signal, bars_of_leg, side, exits, cooldown)` handles, for a long leg:
  - **Stop:** hit when `low <= stop`. Fill at `min(open, stop)`, so a gap down fills at the open.
  - **Trailing:** level is `high-water × (1 - pct)`, where the high-water is the highest daily high since entry.
  - **Take-profit:** fills when `high >= target`, at `max(open, target)`.
  - **Both inside one day:** if a day touches the stop and the take-profit, the stop is assumed first
    (conservative).
  - A short leg mirrors all of this.
  - The exit day's return is entry-side close(t-1) to the fill price. The idea is out from the next day.
- [ ] Tests:
  - The gap-down fill is the open (Review Focus 2).
  - A same-day stop and take-profit takes the stop.
  - The short mirror.
  - Re-entry rules match Part A.
  - Within the budget.
- [ ] FAIL → implement → PASS → commit.

### Task 6: Stop orders and the one cancel path

**Files:** `tradehub/portfolio/paper_orders.py`, `tests/test_portfolio_alpaca_paper.py`,
`tests/test_paper_orders.py`.
- `submit` accepts `order_type` `"stop"` (with `stop_price`) and `"trailing_stop"` (with `trail_percent`), each
  with `time_in_force="gtc"` **only** when `client_order_id` starts with `idea-<n>-stop-`.
- `cancel(order_id, client_order_id)` sends `DELETE PAPER_BASE + "/v2/orders/{order_id}"`, and refuses unless
  `client_order_id` starts with `idea-<n>-stop-`. The master switch gates it too.
- Guards: `paper_orders.py` has exactly one `.post(` and one `.delete(`. No other module writes. No live host.
- [ ] Tests: refusing a cancel of a non-stop or manual order; the stop and trailing bodies; the switch off; the
  guards. FAIL → implement → PASS → commit.

### Task 7: Morning job keeps exactly one stop under each intraday-exit position

**Files:** `tradehub/portfolio/autotrade.py` (`stop_plan`), `tradehub/scripts/paper_orders_run.py`.
Test: `tests/test_paper_orders_run.py`.
- Order of work each morning, for each single-leg idea with `mode="intraday"`:
  1. Read the open stop orders tagged `idea-<id>-stop-`.
  2. If the rule or the exits now want the position closed, **cancel the stop first**, then send the close.
  3. Otherwise make sure one stop exists for the held qty (cancel and replace if the qty changed).
  4. The trailing level is Alpaca's own. A fixed stop is `entry × (1 - pct)`, with the entry from the idea's FIFO
     lots.
  5. Take-profit is a GTC limit order, tagged `idea-<id>-stop-tp-`.
  6. Time stops stay close-based.
- [ ] Tests:
  - A stop is placed after the first fill.
  - The qty changed → cancel and replace.
  - The rule exit → cancel, then close, in that order.
  - A stop that fired yesterday → no double sell (the fills already show it; Review Focus 5).
  - The switch off → nothing.
  - Kill → cancel the stops, then close.
- [ ] FAIL → implement → PASS → commit.

### Task 8: UI and record

**Files:** `WorkshopIdea.tsx` (exit fields and mode; the order log shows stops and cancels), `IdeaRecord.tsx`
(exit markers). Tests in `Workshop.test.tsx`, `Ideas.test.tsx`.
- [ ] FAIL → implement → PASS → commit.

### Part B ship: PR, review, merge, deploy (no new server setting; the timer is unchanged).
