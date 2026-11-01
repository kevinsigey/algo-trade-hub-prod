# Trading HQ Step 6: Buy/Sell-When Rules and Signals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An idea can say "buy when (all|any of) A, B, C … sell when (all|any of) D, E", where each condition uses one of the
new signals: moving averages and crosses, RSI, MACD, breakouts, volatility, VWAP (Part A) and analyst rating changes and
price targets (Part B). The backtest, gate, shadow track and paper orders all run the same rules.

**Architecture:** `IdeaSpec.rules` (enter group + optional exit group) replaces the single `when` condition. A legacy
`when` is converted into a one-condition enter group on load, so stored runs and live ideas keep working and give
identical results. All signal maths lives in a new pure module, `tradehub/workshop/signals.py`. `engine.condition_mask`
becomes the rule mask: it evaluates every condition, combines each group with all/any, then runs an enter/exit state
machine and applies the existing lag rules. Every caller already goes through `_legs`, so nothing downstream changes.

**Tech Stack:** Python 3.12, pydantic v2, pandas/numpy, yfinance 1.7 (already installed), React + TypeScript (vitest).

**Spec:** [docs/superpowers/specs/2026-10-29-trading-hq-design.md](../specs/2026-10-29-trading-hq-design.md), §4.7 item 2
("rule-based 'buy when X, sell when Y' ideas, Verdict-style"). Kevin's answers on 2026-10-30:
- Signals: VWAP, MACD, forward-looking projections, analyst ratings, moving averages, RSI, breakouts, volatility.
- Combining: all or any, chosen separately for each side.
- Shorts: the same rules apply; side comes from the legs (hold is bought, short is sold short).

## Global Constraints

- Paper only. No new order path. `paper_orders.py` stays the only file that POSTs to Alpaca.
- Anti-goal (spec §2): no number may be fitted on years it reports, and no signal may use data from before it was
  public. Price signals use the prior close (lag 1). FRED and analyst data get one more day (lag 2). Close timing adds 1.
- Old runs keep their stored spec and verdict. A legacy `when` spec must produce the same mask, bit for bit.
- Gate: `.venv/bin/python -m pytest -q`; `ruff check --select F` (pre-existing findings only); `npx tsc --noEmit -p
  tsconfig.app.json`; `npx eslint .`; `VITE_SUPABASE_URL= VITE_SUPABASE_ANON_KEY= VITE_SUPABASE_PUBLISHABLE_KEY= npx
  vitest run`.
- The step 5 budget test still holds: a 20-year run with 1,000 shuffles, now with a 3-condition rule, in under 15 s.

## Rulings in this plan (Kevin can overturn)

- **"Forward-looking projections" = analyst price targets** (Part B). Yahoo dates each price-target change, so a
  backtest can use only targets already published. EPS/revenue estimate history is not available free with dates.
  Using today's estimates in a backtest would leak the future, so estimate revisions are left out. When a dated
  source exists they become a new `source`.
- **Analyst data only covers stocks, from about 2019.** AAPL has 971 dated actions, almost all from 2019 on; ETFs such
  as XLE have none. A rule with an analyst condition starts its test on the first day that signal has data. The
  verdict's existing `data_start` shows when, and the editor warns.
- **Enter/exit state machine:** with an exit group, the idea enters when the enter group is true and stays in until
  the exit group is true. If both are true on the same day, exit wins: it stays out, or gets out. With no exit group
  it holds while the enter group is true (today's behaviour). "Crosses above" ideas are written as enter
  `cross > 0`, exit `cross < 0`.
- **A missing value (lookback not filled yet, no analyst actions in the window) makes that condition false.** That
  matches today's `measured.notna()` rule.
- **MACD is fixed at 12/26/9.** It is measured as (MACD line − signal line) / close × 100, so a threshold of 0 means
  bullish and the threshold is comparable across prices. RSI uses Wilder smoothing.
- **VWAP is a rolling N-day VWAP from daily bars:** Σ(typical price × volume) / Σ volume, where typical price is
  (high+low+close)/3. Intraday VWAP needs minute bars we don't have.
- **Each group holds 1-5 conditions.** The shuffle test keeps "random timing" by shifting the final in/out mask, so a
  multi-condition rule is judged exactly like a one-condition rule.
- **Price-bars cache becomes `<T>.ohlcv.csv`** (it adds volume). Old `.ohlc.csv` files are ignored, and the next
  fetch refills them.

## Review Focus

1. A stored legacy spec (`when`, no `rules`) re-validated by the jobs gives the same mask, verdict inputs and
   target as before. Test: `test_legacy_when_mask_identical`.
2. No signal peeks ahead: changing tomorrow's bar must not change today's mask, for every measure. Test:
   `test_no_signal_reads_the_future` (parametrised over all measures).
3. Phantom-day padding in `target_and_reason` copies the last row, including the new `.high/.low/.volume` columns.
   A VWAP rule's target must equal the backtest's last position. Test: `test_target_matches_backtest_vwap`.
4. An analyst rule on a ticker with no analyst data (an ETF) gives a clear 422, not an all-false mask that FAILs.
   Test: `test_analyst_etf_unknown`.
5. Exit wins on a both-true day, and an exit group on an idea with stops still re-enters only on a fresh signal.
   Tests: `test_exit_wins_same_day`, `test_stop_then_fresh_signal_with_exit_group`.

---

## Part A — rules + price signals (one PR)

### Task 1: Spec — rules, groups, new measures, legacy `when`

**Files:** Modify `tradehub/workshop/spec.py`; Test `tests/test_workshop_spec.py`.

**Interfaces — Produces:**
- `Condition.source: Literal["fred","price","analyst"]` (`"analyst"` is accepted only in Part B; Part A rejects it
  with "analyst signals arrive in Part B").
- `Condition.measure: Literal["level","change","pct_change","vs_sma","sma_cross","rsi","macd","vs_high","vs_low",
  "volatility","vs_vwap","net_upgrades","target_upside"]`.
- `Condition.slow_days: int | None = Field(None, ge=2, le=756)`, required for `sma_cross` and greater than `lookback_days`.
- `class Group(BaseModel)`: `mode: Literal["all","any"] = "all"`, `conditions: list[Condition] = Field(min_length=1, max_length=5)`.
- `class Rules(BaseModel)`: `enter: Group`, `exit: Group | None = None`.
- `IdeaSpec.rules: Rules | None = None`. `IdeaSpec.when` stays as an input only. A `mode="before"` model validator
  turns `when` into `{"enter": {"mode": "all", "conditions": [when]}}`, pops `when`, and refuses both being set.
  After validation `spec.when` is always `None`. Delete the field if pydantic allows popping it; otherwise keep it
  `None`, documented as legacy.
- Measures allowed per source: fred → level, change, pct_change, vs_sma, volatility. price → everything except
  net_upgrades and target_upside. analyst → net_upgrades, target_upside.
- `beats_benchmark_when` needs `rules`.
- `blank_spec()` gets `"rules": None` in place of `"when": None`.

- [ ] **Step 1: Failing tests:**
  - `test_legacy_when_becomes_rules`: the step 2 condition dict comes back as `rules.enter.conditions[0]`, with
    `when is None`.
  - `test_when_and_rules_refused`.
  - `test_cross_needs_slow_gt_fast`: fails for slow ≤ fast and for slow missing.
  - `test_measure_source_matrix`: `vs_vwap` + fred refused, `rsi` + price ok, `net_upgrades` + price refused.
  - `test_group_size_1_to_5`.
  - `test_spec_roundtrip_dump`: `model_dump(mode="json")` then `model_validate` gives the same spec.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_workshop_spec.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement. **Step 4:** Rerun. Expected: PASS. Then run the full suite: legacy fixtures must still pass.
- [ ] **Step 5:** Commit `feat(workshop): buy/sell-when rules in the idea spec`.

### Task 2: Signals module

**Files:** Create `tradehub/workshop/signals.py`; Test `tests/test_workshop_signals.py`.

**Interfaces — Produces:** `measure(values: pd.Series, how: str, lookback: int, *, slow: int | None = None,
bars: pd.DataFrame | None = None) -> pd.Series`. It is pure; the value on day t uses data up to and including t.
`bars` has high/low/close/volume columns and is only needed for `vs_vwap`. `level`/`change`/`pct_change` move here
from `engine._measure`, which is deleted. Units as in the rulings:
- `vs_sma`: (close / SMA_N − 1) × 100.
- `sma_cross`: (SMA_fast / SMA_slow − 1) × 100.
- `rsi`: Wilder RSI_N, 0-100.
- `macd`: (EMA12 − EMA26 − EMA9 of that) / close × 100.
- `vs_high`: (close / max of the **prior** N closes − 1) × 100, so a value above 0 is a new N-day high.
- `vs_low`: (close / min of the prior N closes − 1) × 100.
- `volatility`: std of daily returns over N × √252 × 100.
- `vs_vwap`: (close / rolling N-day VWAP − 1) × 100.

- [ ] **Step 1: Failing tests** with hand-checked values on short series:
  - `test_vs_sma_known`: [1,2,3,4] with N=2 gives last = (4/3.5 − 1) × 100.
  - `test_sma_cross_known`.
  - `test_rsi_all_up_is_100_all_down_is_0`.
  - `test_rsi_matches_wilder_reference`: a 20-value fixture checked against a hand-computed reference.
  - `test_macd_zero_on_flat`.
  - `test_vs_high_breakout`: the close that beats the prior 3-day max is > 0; the day before is ≤ 0.
  - `test_volatility_constant_returns_zero`.
  - `test_vwap_known`: 2 bars, hand-computed.
  - `test_no_signal_reads_the_future`: for every measure, a random series with its last value changed leaves every
    earlier value identical.
- [ ] **Step 2:** Run. Expected: FAIL (module missing). **Step 3:** Implement. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(workshop): price signals (MA, cross, RSI, MACD, breakouts, volatility, VWAP)`.

### Task 3: Engine — rule mask and the `when` → `rules` sites

**Files:** Modify `tradehub/workshop/engine.py`, `tradehub/scripts/paper_orders_run.py:70`; Test
`tests/test_workshop_engine.py`, `tests/test_workshop_exits.py`.

**Interfaces:**
- Consumes: Task 1 `Rules/Group/Condition`; Task 2 `signals.measure`.
- Produces:
  - `condition_mask(spec, closes, fred) -> pd.Series` keeps its name and signature. It evaluates each condition
    (price series = `closes[c.series]`; bars for `vs_vwap` = `closes[[f"{T}.high", f"{T}.low", T, f"{T}.volume"]]`;
    fred as today). It combines each group with `all`/`any` and shifts each condition by its own lag before
    combining, since FRED and price lags differ. Then it runs the state machine (`_hold_state(enter, exit) ->
    np.ndarray`, a numpy loop) and the close-timing extra lag.
  - `tickers_for(spec)` adds every price-source series. `rule_series_ids(spec) -> list[str]` returns the FRED ids.
  - Every `spec.when is not None` becomes `spec.rules is not None`: engine lines 299, 407, 422, 477 and
    paper_orders_run 70.
  - The `beats_benchmark_when` label reads "…while the rule was in".

- [ ] **Step 1: Failing tests:**
  - `test_legacy_when_mask_identical`: the old fixture specs' masks are equal before and after.
  - `test_all_vs_any`.
  - `test_enter_exit_hysteresis`: enter at A>0 stays in while A<0 until B>0.
  - `test_exit_wins_same_day`.
  - `test_mixed_lags`: a FRED and a price condition each shifted by their own lag.
  - `test_target_matches_backtest_vwap`.
  - `test_stop_then_fresh_signal_with_exit_group`.
  - Budget test: a 3-condition rule, 20 years, 1,000 shuffles, under 15 s.
- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Rerun the full suite. Expected: PASS.
- [ ] **Step 5:** Commit `feat(workshop): rule mask with enter/exit groups`.

### Task 4: Data — volume, signal bars, one series helper

**Files:** Modify `tradehub/workshop/data.py`, `tradehub/api/main.py` (2 sites), `tradehub/scripts/ideas_shadow.py`,
`tradehub/scripts/paper_orders_run.py`; Test `tests/test_workshop_data.py`, `tests/test_ideas_shadow.py`,
`tests/test_workshop_api.py`.

**Interfaces — Produces:**
- `bars()` returns open/high/low/close/volume, cached as `<T>.ohlcv.csv`.
- `add_bars` adds `<T>.volume`.
- `with_rule_bars(spec, prices, start, *, bars_fn)` attaches bars for the intraday leg **and** for every `vs_vwap`
  series, in one `bars_fn` call.
- `rule_series(spec, start, *, fred) -> dict[str, pd.Series]` replaces the four copies of
  `{spec.when.series: fred(...)}`. It fetches every FRED id from `rule_series_ids` and keeps each caller's start
  offset (FRED_LEAD and `_fred_start`), passed in by the caller.

- [ ] **Step 1: Failing tests:**
  - `test_bars_include_volume`.
  - `test_old_ohlc_cache_ignored`.
  - `test_vwap_rule_gets_bars`.
  - `test_rule_series_two_fred_ids`.
  - An API run with a two-FRED-condition rule returns 200 and fetches both ids.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS, full suite.
- [ ] **Step 5:** Commit `feat(workshop): signal data for multi-condition rules`.

### Task 5: Draft prompt + Workshop editor

**Files:** Modify `tradehub/workshop/draft.py` (SYSTEM text), `market_sentiment_tool/src/lib/workshop.ts`,
`market_sentiment_tool/src/pages/WorkshopIdea.tsx`; Test `tests/test_workshop_draft.py`,
`market_sentiment_tool/src/pages/Workshop.test.tsx`.

**Interfaces — Produces:**
- TS types `Group`, `Rules`, and `Condition` with the new `measure` union and `slow_days`.
- `conditionText(c)` gives plain words per measure, e.g. "SPY 50-day avg above 200-day avg", "XLE RSI(14) < 30",
  "QQQ new 20-day high".
- `rulesText(spec)` reads "buy when all of …; sell when any of …". It understands a legacy `when` in stored run JSON.
- `RulesEditor` (in WorkshopIdea.tsx) replaces the single-condition block:
  - Buy-when group: all/any select; condition rows with source, series, measure (filtered by source), N, slow N
    (cross only), op and threshold; add and remove buttons, up to 5.
  - "Sell when" checkbox: unchecked reads "sells when the buy rule stops holding"; checked shows a second group.
  - A units hint under each measure, e.g. "% above its N-day average".
- Draft SYSTEM text gets one sentence on rules: separate buy/sell conditions, all/any, the measure names, and that
  MACD is 12/26/9.

- [ ] **Step 1: Failing tests:**
  - vitest `renders rules text for legacy when`.
  - vitest `adds and removes a condition`.
  - vitest `sell-when toggle adds exit group to the saved spec`.
  - pytest `test_draft_prompt_mentions_rules`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. Run tsc, eslint and vitest (env blanked).
- [ ] **Step 5:** Commit `feat(workshop): buy/sell-when rule editor`.

**Part A finish:** fresh opus reviewer over the branch, with the Review Focus above. One fix pass, then a PR. I
self-merge with `--match-head-commit` and the deploy runs. Live check: a "SPY 50/200 cross" idea runs end to end on
the site API.

---

## Part B — analyst ratings and price targets (second PR)

### Task 6: Analyst data + measures

**Files:** Modify `tradehub/workshop/data.py`, `signals.py`, `spec.py` (lift the Part A refusal), `engine.py`;
Test `tests/test_workshop_analyst.py`.

**Interfaces — Produces:**
- `data.analyst(ticker, *, fetch=None, cache_dir=None, now=None) -> pd.DataFrame`, built from yfinance
  `Ticker(t).upgrades_downgrades`:
  - Index: tz-naive action timestamp. Columns: action (up/down/main/init/reit) and target (currentPriceTarget, NaN
    when ≤ 0).
  - Cached as `<T>.analyst.csv` and refreshed once per last complete day.
  - Empty or 404 raises `UnknownSymbol(f"no analyst data for {T} (ETFs and funds have none)")`.
- `rule_series` also returns `f"{T}@analyst"` frames for analyst conditions. `@` can't appear in a series id, so
  the key can't collide.
- Signals (each action is mapped to the trading day it happened, or the next one; lag 2 like FRED, since actions
  land during the day):
  - `net_upgrades`: rolling N-day count of `up` minus `down`. NaN before the first action.
  - `target_upside`: (mean target over actions in the last N days / close − 1) × 100. NaN when the window has no
    target. Needs the ticker's closes, so `tickers_for` adds it.
- `_frame` starts at the first day every analyst condition has a non-NaN value, so years before the coverage don't
  count as "off" days.

- [ ] **Step 1: Failing tests (fake fetch):**
  - `test_net_upgrades_window`.
  - `test_target_upside_known`.
  - `test_analyst_lag_two_days`.
  - `test_analyst_etf_unknown`.
  - `test_frame_starts_at_analyst_coverage`.
  - `test_analyst_cache_refresh`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS, full suite.
- [ ] **Step 5:** Commit `feat(workshop): analyst rating and price-target signals`.

### Task 7: Editor + draft for analyst signals

**Files:** `workshop.ts`, `WorkshopIdea.tsx`, `draft.py`; tests as in Task 5.

- [ ] **Step 1: Failing tests:**
  - vitest `analyst source offers only analyst measures`.
  - vitest `warns analyst data starts ~2019 and stocks only`.
  - pytest `test_draft_prompt_mentions_analyst`.
- [ ] **Step 2-4:** FAIL, implement, PASS, full frontend gate.
- [ ] **Step 5:** Commit `feat(workshop): analyst signals in the editor`.

**Part B finish:** reviewer, fix pass, PR, self-merge, deploy. Live check: an "AAPL buy when net upgrades > 0 over
63 days" run returns a verdict with `data_start` ≥ 2019.

## Ops

None. No new secrets, timers or migrations. Specs are JSON columns, and old rows stay valid.
