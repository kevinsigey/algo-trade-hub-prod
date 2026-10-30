# Trading HQ Step 3: Ideas record + live-paper gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kevin can publish a Workshop idea to a public Ideas record, take a PASSed idea through a live-paper gate
into a daily shadow track that is checked against its own claim, kill it on record, and see his real paper trades
attributed to ideas by order tag or relabel. Drafting moves from the Claude API to OpenRouter free models.

**Architecture:** The engine's per-day return construction is extracted so the backtest, the gate recheck and the
shadow job share one rule implementation. New append-only tables hold shadow days and order labels; `ideas` gains
once-only lifecycle timestamps. A weekday systemd timer appends shadow days. The portfolio reads Alpaca orders
(GET only) to map fills to ideas.

**Tech Stack:** FastAPI, pandas/numpy, Supabase (Postgres), `requests` (OpenRouter + Alpaca paper REST), React/TS,
vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-trading-hq-design.md` (§4.1, §4.5, §4.6, §5). Step 2 plan:
`docs/superpowers/plans/2026-10-30-trading-hq-step2-workshop.md`.

## Global Constraints

- Paper only. No order is placed anywhere in this step; Alpaca calls stay GET-only via `paper_get`.
- Every verdict, shadow day and relabel is append-only (DB trigger), as `idea_runs` is today.
- Failed and killed ideas stay visible once published. Every public number carries its as-of and live/stale state.
- Ideas are private until Kevin publishes them. A public request for an unpublished idea is indistinguishable
  from a missing one (404, same body).
- Live-paper gate (spec §5): the claim still holds on data that arrived **after** the backtest's `data_end`, using
  at most the most recent 12 months (252 trading days) of it; each position within 25% of the account; Kevin's
  button. Too little new data → "waiting for data".
- "Claim failing on paper" = the claim check over the shadow track's most recent 3 months (63 trading days). The
  system flags, never kills.
- Order tag format: Alpaca `client_order_id` starting `idea-<id>-` (e.g. `idea-12-001`).
- Routes register directly on `app` in `tradehub/api/main.py` (not `include_router`; breaks `test_cleanup_gone`).
- Migrations recorded in `docs/superpowers/plans/migrations-applied.md`.
- Gate: `.venv/bin/python -m pytest -q`, `ruff --select F` (pre-existing findings only), `npx tsc --noEmit -p
  tsconfig.app.json`, `npx vitest run`, `npx eslint .`.

## Rulings in this plan (Kevin can overturn)

- **Gate minimum: 63 new trading days (~3 months).** A fresh PASS run on today's data shows "waiting for data
  (n of 63 new trading days)" until then. Cost if wrong: one constant.
- **Idea size is entered at go-live** as % of account; each ticker gets `size_pct / len(hold)`, which must be
  ≤ 25. Stored on the idea; step 4 orders will use it.
- **Shadow days start the trading day after go-live** (the decision is made on that close, like every rule).
- **Drafting: OpenRouter free models, with fallback list.** Kevin's ANTHROPIC key would bill API credits, not his
  Pro plan. No in-app refine loop: Kevin edits the draft form, or pastes it to Claude Code for a correction.
- **The Alpaca web dashboard may not let Kevin set `client_order_id`.** Relabel is therefore a first-class path,
  not a fallback.

## Review Focus

1. Shadow job misses days (VPS down, timer skipped) → next run appends every missing day since the last row, in
   order, and never a day before go-live or after a kill.
2. A ticker with no close today (holiday, delisting, yfinance gap) → no shadow row that day (never a 0% day); the
   public page shows "stale" when the last row is more than 3 weekdays old.
3. Go-live / publish / kill pressed twice or concurrently → second call 409, timestamps never move.
4. A fill whose tag names a missing or unpublished idea id, or a relabel to a deleted idea → shows as manual, no
   crash, and the public page never reveals the unpublished idea's title.
5. Partial closes and shorts across two ideas in one symbol → open quantity splits by FIFO lots per idea.

---

### Task 1: Drafting through OpenRouter free models

**Files:**
- Modify: `tradehub/workshop/draft.py`, `pyproject.toml` (drop `anthropic>=1.0`)
- Test: `tests/test_workshop_draft.py` (rewrite its 3 tests)

**Interfaces:**
- Produces: `MODELS: tuple[str, ...]` (primary first), `MODEL = MODELS[0]` (keeps `main.py`'s `DRAFT_MODEL`
  import), `draft_spec(text, *, post=requests.post) -> tuple[IdeaSpec, str]` returning the spec and the model id
  OpenRouter reports. `DraftUnavailable(reason)` unchanged, reasons `no_key|refused|error`.
- `MODELS = ("nvidia/nemotron-3.5-super-vl:free", "dots-studio/dots-3-note-preview:free",
  "xingchen-agi/xing4.0-29b-a4b:free")` — the free models OpenRouter lists with `structured_outputs` on 2026-10-30.
  Overridable by env `OPENROUTER_MODELS` (comma-separated).

- [ ] **Step 1: Tests** — `test_no_key_is_draft_unavailable` (env unset → reason `no_key`, `post` never called);
  `test_request_shape_and_parse` (fake `post` asserts URL `https://openrouter.ai/api/v1/chat/completions`, bearer
  header from `OPENROUTER_API_KEY`, `models == list(MODELS)`, `response_format.type == "json_schema"` with
  `strict: True` and `IdeaSpec.model_json_schema()`, `SYSTEM` as the system message; returns a JSON body whose
  `choices[0].message.content` is a valid spec → returns `(IdeaSpec, "nvidia/…:free")`);
  `test_bad_json_or_http_error_is_error` (content `"not json"` → `error`; HTTP 429 → `error`, detail names the
  status only); `test_refusal` (`finish_reason == "content_filter"` or empty content → `refused`).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_workshop_draft.py -q` → FAIL.
- [ ] **Step 3: Implement.** `post(url, headers=..., json=..., timeout=60)`; `resp.raise_for_status()`; parse with
  `IdeaSpec.model_validate_json(content)`. Any exception → `DraftUnavailable("error", f"the draft failed:
  {type(exc).__name__}")`; never put the key or response body in the detail. Update the `/api/workshop/draft`
  route to return the reported model id as `draft_model`. Keep `SYSTEM`, append: "Reply with JSON only."
- [ ] **Step 4: Run** the file plus `tests/test_workshop_api.py` → PASS.
- [ ] **Step 5: Commit** `feat(workshop): draft with OpenRouter free models`.

### Task 2: One rule implementation; gate recheck; paper claim check

**Files:**
- Modify: `tradehub/workshop/engine.py`
- Test: `tests/test_workshop_engine.py` (add), `tests/test_workshop_gate.py` (new)

**Interfaces:**
- Produces: `daily_frame(spec, closes, fred) -> pd.DataFrame` indexed by date, columns `ret` (idea return after
  costs), `on` (bool, condition held), `bench`, `spy`; exactly what `run_test` uses today (`r`, `mask`, `b`, `s`).
  `run_test` calls it; output unchanged.
- `claim_check(spec, rows: pd.DataFrame) -> dict` `{"holds": bool, "label": str, "days": int}` via `_claim`.
- `gate_check(spec, frame: pd.DataFrame, data_end: date, size_pct: float | None) -> dict`
  `{"status": "ready"|"waiting"|"fails", "new_days": int, "needed": 63, "claim": dict|None, "size_ok": bool|None,
  "reasons": list[str]}`. `MIN_GATE_DAYS = 63`, `GATE_WINDOW = 252`, `MAX_POSITION_PCT = 25`.

- [ ] **Step 1: Tests** — `test_daily_frame_matches_run_test` (existing planted-edge fixture: `daily_frame`'s
  `ret`/`on` equal what `run_test` scored; all 11 existing tests unchanged); `test_gate_uses_only_new_days`
  (frame where the claim holds before `data_end` and fails after → `fails`; reversed → `ready`);
  `test_gate_waits` (40 new days → `waiting`, `new_days == 40`, reason "40 of 63 new trading days");
  `test_gate_window_is_last_252` (400 new days, claim fails in the oldest 148, holds in the last 252 → `ready`);
  `test_gate_size` (`hold` of 2 tickers, `size_pct=60` → `size_ok False`, `fails`, reason names 30% > 25%;
  `size_pct=None` → `size_ok None`, status never `ready`).
- [ ] **Step 2: Run** both files → new tests FAIL.
- [ ] **Step 3: Implement** the extraction first (run the old tests green), then the two functions.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(workshop): shared daily rule frame, live-paper gate check`.

### Task 3: Lifecycle, shadow and label storage

**Files:**
- Create: `market_sentiment_tool/supabase/migrations/20261031000001_ideas_live.sql`
- Modify: `tradehub/workshop/store.py`, `docs/superpowers/plans/migrations-applied.md`
- Test: `tests/test_workshop_store.py` (new); extend the `DB` fake in `tests/test_workshop_api.py` with `update`,
  `is_` and `gt` as needed (move it to `tests/workshop_fake.py` if two files use it).

**Interfaces:**
- SQL: `ideas` add `published_at timestamptz`, `live_at timestamptz`, `killed_at timestamptz`, `size_pct numeric`,
  `live_run_id bigint references idea_runs(id)`, `gate jsonb`. Trigger: once one of `published_at|live_at|killed_at`
  is non-null it cannot change; `killed_at` needs `live_at`. New `idea_shadow_days(idea_id, day date, ret, on bool,
  bench, spy, created_at, unique(idea_id, day))` and `order_labels(id, order_id text, idea_id bigint null, by text,
  at timestamptz default now())`, both append-only by trigger (reuse `idea_runs_append_only()`). RLS on all.
- Python: `publish(supa, idea_id)`, `go_live(supa, idea_id, run_id, size_pct, gate)`, `kill(supa, idea_id)` — each
  updates `where <col> is null` and raises `AlreadySet` when no row changed. `shadow_days(supa, idea_id) -> list`,
  `append_shadow(supa, idea_id, rows)`, `live_ideas(supa)` (live, not killed), `published_ideas(supa)`,
  `add_label(supa, order_id, idea_id, by)`, `labels(supa) -> dict[order_id, idea_id|None]` (latest per order).

- [ ] **Step 1: Tests** for the store against the fake: second `publish` raises `AlreadySet`; `labels` returns the
  latest row per order id; `live_ideas` excludes killed.
- [ ] **Step 2: Run** → FAIL. **Step 3:** implement; apply the migration with the Supabase MCP; prove the triggers
  with a rolled-back probe (update a set `live_at`, update a shadow row → both raise, 0 rows changed); record it.
- [ ] **Step 4: Run** store tests + `tests/test_migrations_recorded.py` → PASS.
- [ ] **Step 5: Commit** `feat(workshop): idea lifecycle, shadow days, order labels`.

### Task 4: Shadow job

**Files:**
- Create: `tradehub/scripts/ideas_shadow.py`
- Test: `tests/test_ideas_shadow.py`

**Interfaces:**
- Consumes: `store.live_ideas`, `store.shadow_days`, `store.append_shadow`, `engine.daily_frame`,
  `workshop.data.closes/fred_series`.
- Produces: `main(now=None, supa=None, closes=..., fred=...) -> dict[idea_id, rows_added]`.

- [ ] **Step 1: Tests** — first run after go-live on day D appends rows for D+1.. only; a 5-day gap is filled in
  order; a killed idea gets no rows after the kill day; a day where a held ticker has no close produces no row;
  running twice adds nothing the second time.
- [ ] **Step 2: Run** → FAIL. **Step 3:** implement (fetch closes from `live_at - 3*366 days` so lookbacks are
  warm). **Step 4:** PASS. **Step 5: Commit** `feat(workshop): daily shadow track job`.

### Task 5: Workshop API for the gate, lifecycle and labels

**Files:**
- Modify: `tradehub/api/main.py`
- Test: `tests/test_workshop_api.py` (add)

**Interfaces (all `Depends(admin.require_admin)`):**
- `GET /api/workshop/ideas/{id}/gate?size_pct=` → `gate_check` on the latest run (404 no idea; `fails` with
  reason "the latest run did not PASS" when it didn't).
- `POST /api/workshop/ideas/{id}/publish`, `POST .../live {size_pct}` (re-runs the gate server-side; 409 unless
  `ready`; 409 when already live), `POST .../kill` (409 unless live and not killed).
- `GET /api/workshop/ideas/{id}` adds `published_at, live_at, killed_at, size_pct, tag: "idea-<id>-", shadow:
  {curve, claim_check (last 63), failing: bool, as_of, state}`.
- `GET /api/workshop/fills` (recent fills with `order_id`, symbol, side, qty, time, current label), `POST
  /api/workshop/labels {order_id, idea_id|null}` (422 if idea id missing; `by` = admin email). Each fill carries
  its label history `[{from, to, by, at}]`, with the original tag as the first `from` (spec §4.6: never erased).

- [ ] **Step 1: Tests** for each 409/404/422 path and the happy path; no route answers without a session (401).
- [ ] **Steps 2-4:** FAIL → implement → PASS. **Step 5: Commit** `feat(workshop): gate, publish, go-live, kill,
  labels API`.

### Task 6: Portfolio attribution

**Files:**
- Modify: `tradehub/portfolio/book.py`, `tradehub/portfolio/service.py`
- Test: `tests/test_portfolio_book.py`, `tests/test_portfolio_api.py` (add)

**Interfaces:**
- `service._orders()` pages `GET /v2/orders` (`status=all`, `direction=asc`, `limit=500`, `after=`) → `{order_id:
  client_order_id}`.
- `book.tag_fills(fills, client_ids, labels, titles: dict[int, str]) -> list[dict]` adds `idea` (title or
  `MANUAL`): label wins over tag; tag parsed with `^idea-(\d+)-`; unknown/unpublished id → `MANUAL`.
- `closed_trades` uses the entry lot's `idea`. New `book.open_lots(fills) -> dict[symbol, dict[idea, signed_qty]]`;
  `positions_view(account, positions, open_by_idea=None)` splits each position row by idea in proportion to open
  lot quantity; uncovered quantity stays `MANUAL`.
- Public titles: only published ideas get their title; unpublished tags show `MANUAL` on the public portfolio.

- [ ] **Step 1: Tests** — two ideas buy the same symbol, one partially sells → open split correct; short lots;
  relabel beats tag; tag to unpublished id → `MANUAL`; composition groups by idea.
- [ ] **Steps 2-4:** FAIL → implement → PASS. **Step 5: Commit** `feat(portfolio): attribute positions and trades
  to ideas`.

### Task 7: Public Ideas record

**Files:**
- Modify: `tradehub/api/main.py`, `market_sentiment_tool/src/App.tsx`
- Create: `market_sentiment_tool/src/pages/Ideas.tsx`, `IdeaRecord.tsx`, `Ideas.test.tsx`
- Test: `tests/test_ideas_public_api.py`

**Interfaces:**
- `GET /api/ideas` (no auth): published ideas, newest first: `id, title, claim label, latest_verdict, variations,
  status ("backtest"|"live"|"killed"), live: {since, return_pct, bench_return_pct, failing, as_of, state} | null`.
- `GET /api/ideas/{id}`: one published idea: every run's verdict summary (headline, verdict, p, bar, created_at),
  the shadow curve vs benchmark, kill date, tagged closed trades. Unpublished or missing → identical 404.
- Pages: `/ideas` list (fails and kills shown, not hidden), `/ideas/:id` record (numeric id check, as in
  `WorkshopIdea`). Menu: "Ideas" between Portfolio and Predictions.

- [ ] **Step 1: Tests** — API: unpublished vs missing 404 bodies equal; killed idea still listed; `state` is
  `stale` when the last shadow day is > 3 weekdays old. Page: list renders verdict and status; failing flag shown.
- [ ] **Steps 2-4:** FAIL → implement → PASS. **Step 5: Commit** `feat(ideas): public Ideas record`.

### Task 8: Workshop UI for publish, gate, go-live, kill and labels

**Files:**
- Modify: `market_sentiment_tool/src/pages/WorkshopIdea.tsx`, `Workshop.tsx`, `src/lib/workshop.ts`
- Test: `market_sentiment_tool/src/pages/Workshop.test.tsx` (add)

- [ ] **Step 1: Tests** — gate panel shows "waiting for data (40 of 63 …)" and a disabled button; `ready` +
  size → enabled; kill asks for confirmation; tag `idea-12-` shown with a copy button once live; labels list
  posts `{order_id, idea_id}`.
- [ ] **Steps 2-4:** FAIL → implement → PASS (browser check desktop + phone width against the local preview).
- [ ] **Step 5: Commit** `feat(workshop): go-live panel, kill, trade labels`.

### Server step (Kevin's terminal tab; prod change)

- [ ] Add `ideas-shadow)` to `/opt/stack/bin/tradehub-job`; `tradehub-ideas-shadow.service` + `.timer`
  (`OnCalendar=Mon..Fri *-*-* 22:30:00 UTC`, `Persistent=true`). Written as a script, run via `run_in_terminal`.
- [ ] After deploy: `curl` `/api/ideas` (200, `[]`), `/api/workshop/ideas/1/gate` (401), a manual systemd run of
  the shadow job (0 rows, no error).
