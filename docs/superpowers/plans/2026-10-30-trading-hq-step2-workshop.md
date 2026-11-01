# Trading HQ Step 2: Workshop (first test type) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kevin types an idea in plain words. Claude drafts a test, Kevin confirms or edits it, and the hub
backtests it on daily prices and FRED data. The result is a PASS / FAIL / NOT ENOUGH DATA verdict against the
idea's own claim, saved forever with its variations.

**Architecture:** One Pydantic model, `IdeaSpec`, is the contract three parts share: Claude's draft
(`messages.parse(output_format=IdeaSpec)`), Kevin's edited form (validated at the API) and the engine's
input. The engine is pure numpy/pandas on daily return series, so it is testable with synthetic data. Data
loaders are injectable. Ideas and runs live in two append-only Supabase tables. All Workshop routes use
step 1's `require_admin`.

**Tech Stack:** FastAPI, Pydantic 2, pandas/numpy/scipy (installed), yfinance (installed) for daily
closes, the existing `fetch_fred_daily`, the `anthropic` SDK (new dependency, the one addition), and
React + recharts.

**Spec:** `docs/superpowers/specs/2026-10-29-trading-hq-design.md` (sections 4.3, 4.4, 4.7 step 2 first test type, 5)

**Out of scope (later plans):** rule-based buy/sell ideas, new test types (earnings drift, implied vs
realized), publishing to the Ideas record, the live-paper gate, and the conversational edit flow.

## Global Constraints

- PASS means **the idea did what it claims**, measured only on **unseen years** (default: the most recent 30%
  of the range). It must also beat random timing at a **Bonferroni bar of 0.05 / n**, where n is the number
  of variations run on this idea, including this one.
- Shuffle test: **1,000** permutations, with a fixed seed per run (the seed is stored with the run).
- Ballast claim, Kevin's definition, verbatim: on SPY's down days it loses less than SPY **and** its overall
  return is positive, **or** it goes up on SPY's down days.
- SPY, QQQ and IWM are shown on every verdict as context. They are the bar only when the claim is
  `beats_benchmark` / `beats_benchmark_when`.
- No lookahead: a condition is evaluated on data available at the **prior** close. FRED values are lagged one
  extra business day for publication.
- A verdict is never overwritten. Runs are insert-only; a DB trigger rejects UPDATE/DELETE on `idea_runs`.
- Kevin always confirms the draft before it runs. No route runs a draft directly.
- No key → the draft route answers 424 with a blank template, and Kevin fills the form himself. Never a 500.
- Model: `claude-opus-5-5`, `output_config.effort = "medium"`. Handle `stop_reason == "refusal"` by answering
  424 with the template.
- Every Workshop route requires `require_admin`. Ideas stay private (publishing is step 3).

## Review Focus

1. Unknown ticker or FRED series in an edited draft → 422 naming the symbol, not a 500 (Task 2, Task 5).
2. An unseen span shorter than 2 years (late-listing ETF, short range) → `NOT ENOUGH DATA`, never a PASS (Task 3).
3. A condition that is never or always true on the unseen span → `NOT ENOUGH DATA` with the reason (Task 3).
4. Lookahead: a condition built from the same day's return must show no edge after the shift (Task 3).
5. Variation count: a second run on the same idea is stored as variation 2 and judged at 0.025 (Task 3, Task 5).

---

## File map

| File | Responsibility |
|---|---|
| `tradehub/workshop/__init__.py` | package marker |
| `tradehub/workshop/spec.py` | `IdeaSpec`, `Condition`, defaults, `blank_spec()` |
| `tradehub/workshop/data.py` | `closes(tickers, start) -> DataFrame`, `fred_series(id, start) -> Series`, CSV cache |
| `tradehub/workshop/engine.py` | `run_test(spec, closes, fred, *, variations, seed) -> dict`, pure |
| `tradehub/workshop/draft.py` | `draft_spec(text, *, client=None) -> IdeaSpec`, `DraftUnavailable` |
| `tradehub/workshop/store.py` | insert/list ideas and runs |
| `tradehub/api/main.py` | five `/api/workshop/*` routes (registered on `app` directly; `include_router` breaks `test_cleanup_gone`) |
| `market_sentiment_tool/supabase/migrations/20261030000002_workshop.sql` | `ideas`, `idea_runs`, trigger |
| `market_sentiment_tool/src/lib/workshop.ts` | types, `adminJson()` (authed fetch), verdict copy |
| `market_sentiment_tool/src/pages/Workshop.tsx`, `WorkshopIdea.tsx` | list + new idea; draft editor + verdicts |
| `market_sentiment_tool/src/App.tsx` | `/workshop`, `/workshop/:id` behind `RequireAdmin`; Admin menu entry |

---

### Task 1: The idea spec

**Files:** Create `tradehub/workshop/__init__.py`, `tradehub/workshop/spec.py` · Test `tests/test_workshop_spec.py`

**Interfaces — Produces:**

```python
class Condition(BaseModel):  # extra="forbid"
    source: Literal["fred", "price"]
    series: str                      # FRED id ("DGS10") or ticker ("SPY")
    measure: Literal["level", "change", "pct_change"]
    lookback_days: int = Field(63, ge=1, le=756)   # trading days; ignored for "level"
    op: Literal[">", "<"]
    threshold: float

class IdeaSpec(BaseModel):  # extra="forbid"
    title: str = Field(min_length=3, max_length=120)
    hold: list[str] = Field(min_length=1, max_length=5)   # equal weight; uppercased
    when: Condition | None = None                          # None = always hold
    otherwise: str = "CASH"                                # ticker or "CASH" (0% return)
    claim: Literal["beats_benchmark", "beats_benchmark_when", "ballast", "smoother_ride"]
    benchmark: str = "SPY"
    cost_bps: float = Field(10, ge=0, le=200)              # per unit of turnover
    start: date = date(2006, 1, 3)
    unseen_fraction: float = Field(0.3, ge=0.1, le=0.5)
    assumptions: list[str] = []

def blank_spec() -> dict    # IdeaSpec defaults with title "", hold [], claim "beats_benchmark"
```

Validators: tickers match `^[A-Z][A-Z0-9.\-]{0,9}$` after uppercasing. `beats_benchmark_when` requires
`when`. `start` is ≥ 1995-01-01 and before today.

- [ ] **Step 1: Write failing tests:** the example idea from the mockup ("hold GLD when DGS10 change over 63 days >
  0.25, otherwise SPY, claim beats_benchmark_when") validates. A lowercase ticker is uppercased.
  `beats_benchmark_when` without `when` → ValidationError. An unknown field → ValidationError. `cost_bps=500`
  → ValidationError. `IdeaSpec.model_json_schema()` has `additionalProperties: false` at the top level.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_workshop_spec.py -v` → FAIL.
- [ ] **Step 3: Implement.** **Step 4: Run** → PASS. **Step 5: Commit** `feat(workshop): IdeaSpec contract`.

### Task 2: Data loaders

**Files:** Create `tradehub/workshop/data.py` · Test `tests/test_workshop_data.py`

**Interfaces — Produces:**
- `class UnknownSymbol(ValueError)` (message names the symbol)
- `closes(tickers: list[str], start: date, *, download=None, cache_dir: Path | None = None, today: date | None = None) -> pd.DataFrame`.
  Returns adjusted daily closes, columns = tickers, DatetimeIndex. It uses `yf.download(tickers, start=..., auto_adjust=True,
  progress=False)["Close"]`. Cache: one CSV per ticker in `cache_dir` (env `TRADEHUB_PRICE_CACHE`, default none),
  reused when its last row is from today or the last weekday. A ticker with no rows → `UnknownSymbol`.
- `fred_series(series_id: str, start: date, *, fetch=fetch_fred_daily) -> pd.Series`. A float series on a
  DatetimeIndex; empty → `UnknownSymbol`.

- [ ] **Step 1: Write failing tests** with a fake `download` (returns a DataFrame shaped like yfinance's
  multi-column result) and a fake `fetch`: columns come back in requested order; an empty ticker →
  `UnknownSymbol("XYZ")`; a fresh cache file means no download call; a stale one triggers a download.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(workshop): daily closes and FRED loaders`.

### Task 3: The test engine (the core)

**Files:** Create `tradehub/workshop/engine.py` · Test `tests/test_workshop_engine.py`

**Interfaces:**
- Consumes: `IdeaSpec`, `Condition` (Task 1).
- Produces: `run_test(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series], *, variations: int, seed: int,
  permutations: int = 1000) -> dict`. `closes` holds every ticker in `hold` + `otherwise` (unless CASH) + `benchmark`
  + `SPY`/`QQQ`/`IWM`. Returns:

```python
{"verdict": "PASS" | "FAIL" | "NOT ENOUGH DATA",
 "headline": str,                         # one plain sentence, e.g. "Beat SPY on the years it was built on, not after."
 "reason": str | None,                    # set for NOT ENOUGH DATA
 "split_date": "YYYY-MM-DD", "data_start": ..., "data_end": ...,
 "claim": {"built": {"holds": bool, "value": float, "label": str},
           "unseen": {"holds": bool, "value": float, "label": str}},
 "shuffle": {"beats_pct": float, "p": float, "bar": float, "permutations": 1000, "seed": int},
 "t_test": {"mean_daily_diff": float, "t": float, "p": float} | None,
 "periods": {"held": int, "of": 5},
 "variations": int,
 "context": [{"name": "Idea"|"SPY"|"QQQ"|"IWM", "built_cagr": float, "unseen_cagr": float, "unseen_max_dd": float}],
 "curve": [{"t": "YYYY-MM-DD", "idea": float, "benchmark": float}]}   # cumulative %, ≤ 600 points (downsampled)
```

The rules this task pins (the decisions; the implementer writes the arithmetic):
1. **Position:** `in_cond[t] = condition evaluated on values up to t-1` (FRED: up to t-2). Daily return =
   mean(hold returns) where `in_cond`, else `otherwise` return (0 for CASH). With no `when`, always hold.
   Cost = `cost_bps/1e4 × |Δ position|` on switch days.
2. **Measure:** `level` = value; `change` = value − value `lookback_days` earlier; `pct_change` = % change.
3. **Split:** `split_date` = the first trading day of the last `unseen_fraction` of the common date range.
4. **Claims**, computed on a span (built or unseen) of daily idea returns `r` and benchmark returns `b`:
   - `beats_benchmark`: CAGR(r) − CAGR(b) > 0. The value is the gap in pts/yr.
   - `beats_benchmark_when`: mean(r − b) on `in_cond` days × 252 > 0, with `b` = the benchmark (the relationship
     case: "gold beats stocks when rates rise").
   - `ballast`, with `s` = SPY returns: (mean(r[s<0]) > mean(s[s<0]) **and** total return of r > 0) **or**
     mean(r[s<0]) > 0. The value is mean(r[s<0]) − mean(s[s<0]) in % per down day.
   - `smoother_ride`: maxDD(r) > maxDD(b) (shallower) **and** CAGR(r) ≥ CAGR(b) − 2 pts.
5. **Shuffle (random timing), on the unseen span only.** With `when`: circularly shift the `in_cond` mask by a
   random offset (≥ 21 days from 0), rebuild r, and recompute the claim value. Without `when`: circularly shift
   the held asset's returns against `b`/`s`. `p = (1 + #(perm ≥ actual)) / (1 + permutations)`,
   `beats_pct = 100 × #(perm < actual)/permutations`, `bar = 0.05 / variations`. Use `np.random.default_rng(seed)`.
6. **Verdict:** NOT ENOUGH DATA when the unseen span is under 504 trading days, or (with `when`) `in_cond` is true on
   fewer than 21 or more than (n−21) unseen days. Otherwise PASS iff `claim.unseen.holds and shuffle.p < bar`.
7. **Supporting:** `t_test` = `scipy.stats.ttest_1samp(r − b, 0)` on the unseen claim days (`None` for ballast).
   `periods` = 5 equal chunks of the full range, counting chunks where the claim holds.
8. **Headline** (exact copy): PASS → `"Did what it claims on the years it hadn't seen."`; FAIL with built-holds and
   unseen-fails → `"Worked on the years it was built on, not after."`; FAIL with unseen holding but the shuffle
   failing → `"Held up, but no better than random timing."`; other FAIL → `"Did not do what it claims."`;
   NOT ENOUGH DATA → `"Not enough data to judge."`.

- [ ] **Step 1: Write failing tests** on synthetic data (seeded numpy, ~5,000 business days):
  - `test_planted_edge_passes`: the asset returns +0.1%/day more than the benchmark exactly when a FRED series is
    rising, and the series is a smooth random walk → PASS, `shuffle.p < 0.05`.
  - `test_noise_fails`: an unrelated asset → FAIL.
  - `test_lookahead_is_impossible`: condition = "asset's own price change over 1 day > 0" (a perfect
    same-day predictor) on i.i.d. returns → not PASS.
  - `test_ballast_definition`: an asset that is flat on SPY down days, slightly up overall → `claim.unseen.holds`;
    an asset that is −0.5×SPY on down days but has negative total return → holds via neither branch.
  - `test_short_unseen_span_is_not_enough_data` (400 unseen days) and `test_condition_never_true_is_not_enough_data`.
  - `test_bonferroni_bar`: the same inputs with `variations=1` and `variations=4` → bar 0.05 and 0.0125, and a
    result with p = 0.02 flips from PASS to FAIL.
  - `test_costs_reduce_returns`: cost_bps 0 vs 100 on a frequently switching rule → lower unseen CAGR.
  - `test_same_seed_same_result`.
  - `test_curve_is_downsampled_to_600`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS (keep the file under 10 s).
- [ ] **Step 5: Commit** `feat(workshop): test engine with unseen split, shuffle test and Bonferroni bar`.

### Task 4: Claude drafts the test

**Files:** Create `tradehub/workshop/draft.py` · Modify `pyproject.toml` (add `"anthropic>=1.0"`) · Test `tests/test_workshop_draft.py`

**Interfaces — Produces:** `class DraftUnavailable(Exception)` (`.reason`: `"no_key" | "refused" | "error"`), and
`draft_spec(text: str, *, client=None) -> IdeaSpec`.

Call (from the claude-api skill; verify against the installed SDK):
`client.messages.parse(model="claude-opus-5-5", max_tokens=4000, output_config={"effort": "medium"},
system=SYSTEM, messages=[{"role": "user", "content": text}], output_format=IdeaSpec)`. Then use
`response.parsed_output`. Check `stop_reason == "refusal"` first. `client` defaults to `anthropic.Anthropic()` only when
`ANTHROPIC_API_KEY` is set, else `DraftUnavailable("no_key")`. SDK errors → `DraftUnavailable("error")`.
Server-side refusal fallbacks are left off: Kevin confirms every draft, and a refusal falls back to the hand form.

`SYSTEM` (exact copy):

> You turn one plain-words trading idea into a backtest spec. Use only daily ETF/stock tickers and FRED series ids
> you are confident exist. Pick the claim that matches what the idea says success is: beating the benchmark
> overall (beats_benchmark), beating it only while a condition holds (beats_benchmark_when), protecting on SPY's
> down days (ballast), or a shallower worst drop at similar return (smoother_ride). Every choice the words do
> not pin down goes in assumptions as one short sentence, for example "rates rising = 10-year yield up more
> than 0.25 points over 3 months". Never invent results.

- [ ] **Step 1: Write failing tests** with a fake client whose `messages.parse` returns an object with `stop_reason` and
  `parsed_output`: success returns the IdeaSpec; refusal → `DraftUnavailable("refused")`; no env key and no client
  → `"no_key"`; the fake records that the model is `claude-opus-5-5` and the effort is `medium`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS. `uv pip install anthropic` into `.venv` first.
- [ ] **Step 5: Commit** `feat(workshop): Claude drafts the test (Kevin confirms before it runs)`.

### Task 5: Storage and API

**Files:** Create the migration and `tradehub/workshop/store.py` · Modify `tradehub/api/main.py`, `docs/superpowers/plans/migrations-applied.md` · Test `tests/test_workshop_api.py`

Migration:

```sql
create table if not exists public.ideas (
  id bigint generated always as identity primary key,
  title text not null,
  plain_words text not null,
  created_at timestamptz not null default now()
);
create table if not exists public.idea_runs (
  id bigint generated always as identity primary key,
  idea_id bigint not null references public.ideas(id),
  variation int not null,
  spec jsonb not null,
  draft_model text,
  verdict text not null check (verdict in ('PASS','FAIL','NOT ENOUGH DATA')),
  result jsonb not null,
  data_end date not null,
  created_at timestamptz not null default now(),
  unique (idea_id, variation)
);
create or replace function public.idea_runs_append_only() returns trigger language plpgsql as $$
begin raise exception 'idea_runs is append-only: a verdict is never changed'; end $$;
create trigger idea_runs_no_update before update or delete on public.idea_runs
  for each row execute function public.idea_runs_append_only();
alter table public.ideas enable row level security;
alter table public.idea_runs enable row level security;
```

**Interfaces — Produces** (all with `Depends(admin.require_admin)`):
- `POST /api/workshop/draft {text}` → `{spec, model}`; on `DraftUnavailable` → 424 `{detail, reason, template: blank_spec()}`.
- `POST /api/workshop/ideas {title, plain_words}` → the idea row.
- `GET /api/workshop/ideas` → `[{id, title, created_at, runs, latest_verdict}]`, newest first.
- `GET /api/workshop/ideas/{id}` → `{idea, runs: [...]}`, runs by variation; 404 if missing.
- `POST /api/workshop/ideas/{id}/runs {spec, draft_model?}` → validates `IdeaSpec` (422 with Pydantic's message),
  loads data (`UnknownSymbol` → 422 naming it), sets `variation = runs + 1`, `seed = idea_id*1000 + variation`,
  calls `run_test`, inserts, and returns the run. Plain `def` (blocking I/O in the threadpool).
- `store.py`: `create_idea`, `list_ideas`, `get_idea`, `insert_run(idea_id, spec, draft_model, result) -> dict`.
  It never updates.

- [ ] **Step 1: Write failing tests** (fake Supabase as in `tests/test_portfolio_api.py`; `run_test`/loaders
  monkeypatched): every route → 401 without admin. The draft with no key → 424 with `template`. A run with
  an unknown field → 422. A run with `UnknownSymbol` → 422 naming the ticker. Two runs → variations 1 and 2, and
  `run_test` got `variations=2` the second time. List shows `latest_verdict`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS. Record the migration (row + watermark); `test_migrations_recorded` passes.
- [ ] **Step 5: Commit** `feat(workshop): append-only ideas and runs, admin-only API`.

### Task 6: Workshop pages

**Files:** Create `src/lib/workshop.ts` (+ test), `src/pages/Workshop.tsx`, `src/pages/WorkshopIdea.tsx` (+ tests) · Modify `src/App.tsx`, `src/App.routes.test.tsx`

**Interfaces:**
- `adminJson<T>(path: string, init?: RequestInit): Promise<T>` adds `Authorization: Bearer <sessionToken()>`
  (from `RequireAdmin.tsx`) and throws `Error(detail)` on non-2xx, keeping a parsed body on `.body` for the 424 template.
- `verdictTone(v): "ok" | "bad" | "flat"`. `claimLabel(claim)`: plain words for the four claims.

Layout (mockup `.superpowers/brainstorm/.../workshop-flow.html`):
- `/workshop`: a textarea ("Type an idea in plain words") and a **Turn into a test** button. That creates the idea, drafts, then navigates
  to `/workshop/:id?draft=1`. Below: the idea list (title, runs, latest verdict chip).
- `/workshop/:id`: the plain words at the top. **Draft card**: an editable form of every `IdeaSpec` field, with
  assumptions listed and editable, and a **Run it** button. A 424 shows "Claude couldn't draft this — fill it in"
  with the blank template. **Verdicts**: newest first. Each has a big PASS/FAIL/NOT ENOUGH DATA tile, the headline,
  a recharts line chart of `curve` with a `ReferenceLine` at `split_date` labelled "unseen years →", and a checks table
  (claim built, claim unseen, shuffle "beats N% of 1,000 · needs p < bar", t-test, periods held, variations).
  A context row shows SPY/QQQ/IWM. **Try a variation** reopens the draft card prefilled with that run's spec.
- The menu: add **Workshop** at the top of the Admin group. Routes are wrapped in `RequireAdmin`.

- [ ] **Step 1: Write failing tests:** `claimLabel("ballast")` is plain words; Workshop renders the textarea and the list;
  WorkshopIdea renders a FAIL run's headline, "beats 71% of 1,000", and the variation count; the 424 path shows
  the hand-fill message with the form; `/workshop` without admin shows "Admin only".
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS. Full frontend gate: `npx vitest run`, `npx tsc --noEmit -p tsconfig.app.json`, `npx eslint .`.
- [ ] **Step 5: Commit** `feat(web): Workshop pages`.

### Task 7: Ship

- [ ] Apply the migration (Supabase MCP) and check the trigger: an `update idea_runs ...` in a rolled-back transaction raises.
- [ ] Full gate (pytest, ruff F, tsc, vitest, eslint) → PR → merge pinned to the full head sha → deploy green.
- [ ] VPS (Kevin approved Workshop prod setup when approving this plan): add `ANTHROPIC_API_KEY` and
  `TRADEHUB_PRICE_CACHE: /cache/prices` names to the tradehub `environment:` block. Kevin enters the key value
  with `scripts/set-alpaca-paper-keys.sh`-style hidden prompt (generalise it to `scripts/set-vps-secret.sh NAME`).
- [ ] Live check, signed in: run the mockup idea (gold vs SPY when 10-year yields rise) end to end. Report the
  verdict, the shuffle p, and the time it took.
