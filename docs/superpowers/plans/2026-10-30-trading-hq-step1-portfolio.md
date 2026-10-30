# Trading HQ Step 1: Login + Alpaca paper portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public Portfolio home page and Closed-trades page reading an Alpaca **paper** account, an
admin-only login, and the hub menu regrouped into Portfolio / Predictions / Admin.

**Architecture:** One small Python module talks to Alpaca's paper REST API with `requests` (already a
dependency; `alpaca-py` is not installed in the image). Pure functions turn Alpaca JSON plus stored
snapshots into the page payload. An hourly-in-market-hours job writes snapshots to a new Supabase
table. The React app adds two pages, a login page (supabase-js `signInWithPassword`) and a `RequireAdmin`
wrapper; the API verifies the Supabase JWT server-side for `/api/admin/*`.

**Tech Stack:** FastAPI, requests, Supabase (Postgres + Auth), React 18 + react-router + recharts +
Tailwind, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-trading-hq-design.md` (sections 3, 4.1, 4.2, 4.7 step 1, 5)

## Global Constraints

- Paper only: the only trading host is `https://paper-api.alpaca.markets`. A test fails if
  `api.alpaca.markets` appears anywhere in `tradehub/` without the `paper-` prefix.
- No orders: this step only reads (`GET`). No `POST/PATCH/DELETE` to Alpaca anywhere.
- Missing keys or a 401/403 → `state: "not_connected"`, HTTP 200, never a 500 and never zeros.
- Every number on the page carries `as_of` and a live/stale state (stale = snapshot older than 2h in
  market hours, or Alpaca read failed and we fell back to the last snapshot).
- "Since start" = first snapshot whose `account_number` equals env `PORTFOLIO_ACCOUNT_NUMBER`. Unset or
  different account → `state: "pre_start"` and the page labels it "Pre-start test account".
- Full sizes and dollars are public.
- Untagged positions are attributed to `"No idea yet (manual)"` (ideas arrive in Step 3).
- Admin = one Supabase user whose email equals env `TRADEHUB_ADMIN_EMAIL`; no sign-up route.
- Never print or log Alpaca keys; never read `/opt/stack/.env` values.
- Migrations recorded in `docs/superpowers/plans/migrations-applied.md`.
- Gate before merge: `.venv/bin/python -m pytest -q`, `ruff check --select F`, `npx tsc --noEmit -p
  tsconfig.app.json`, `npx vitest run`, `npx eslint .`.

## Review Focus

1. Empty paper account (no positions, no fills, one snapshot) → page renders "0 positions", returns
   shown as "—" (not 0.0%) until two snapshots exist. Test in Task 2.
2. Alpaca down/timeout with snapshots present → last snapshot shown with `state: "stale"`. Test in Task 3.
3. Partial fills / multiple buys before a sell → closed-trade FIFO matching keeps share counts exact. Test in Task 2.
4. Short positions (`side: "short"`, negative qty) → value and P&L sign correct, % of book uses abs value. Test in Task 2.
5. Expired admin session → gated page shows the login prompt, not a blank page; `/api/admin/me` 401. Tests in Tasks 4, 6.

---

## File map

| File | Responsibility |
|---|---|
| `tradehub/portfolio/__init__.py` | package marker |
| `tradehub/portfolio/alpaca_paper.py` | paper-only HTTP reads; `AccountNotConnected` |
| `tradehub/portfolio/book.py` | pure: scoreboard, curve, composition, positions, closed trades |
| `tradehub/scripts/portfolio_snapshot.py` | job: read account + SPY, insert snapshot |
| `tradehub/api/admin.py` | `require_admin` dependency, `/api/admin/me` |
| `tradehub/api/main.py` | `/api/portfolio`, `/api/portfolio/closed`, include admin router |
| `market_sentiment_tool/supabase/migrations/20261030000001_portfolio_snapshots.sql` | table |
| `market_sentiment_tool/src/lib/paperPortfolio.ts` | payload types + formatters |
| `market_sentiment_tool/src/pages/Portfolio.tsx`, `ClosedTrades.tsx`, `Login.tsx` | pages |
| `market_sentiment_tool/src/components/RequireAdmin.tsx` | session gate |
| `market_sentiment_tool/src/App.tsx` | routes + regrouped menu |

---

### Task 1: Paper-only Alpaca client

**Files:**
- Create: `tradehub/portfolio/__init__.py`, `tradehub/portfolio/alpaca_paper.py`
- Test: `tests/test_portfolio_alpaca_paper.py`

**Interfaces:**
- Produces: `PAPER_BASE = "https://paper-api.alpaca.markets"`, `DATA_BASE = "https://data.alpaca.markets"`,
  `class AccountNotConnected(Exception)`, `paper_get(path: str, params: dict | None = None, *, session=requests) -> Any`,
  `latest_spy_price(*, session=requests) -> float`.

- [ ] **Step 1: Write failing tests**

```python
def test_missing_keys_raise_not_connected(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    with pytest.raises(AccountNotConnected):
        paper_get("/v2/account")

def test_401_raises_not_connected(monkeypatch):  # fake session returning status 401
    ...
    with pytest.raises(AccountNotConnected):
        paper_get("/v2/account", session=fake)
    assert fake.calls[0]["url"] == "https://paper-api.alpaca.markets/v2/account"
    assert fake.calls[0]["headers"]["APCA-API-KEY-ID"] == "k"

def test_no_live_trading_host_anywhere_in_tradehub():
    for path in Path("tradehub").rglob("*.py"):
        text = path.read_text()
        assert not re.search(r"(?<!paper-)api\.alpaca\.markets", text), path

def test_module_only_issues_gets():
    src = Path("tradehub/portfolio/alpaca_paper.py").read_text()
    assert not re.search(r"\.(post|patch|put|delete)\(", src)
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_portfolio_alpaca_paper.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement.** Headers `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` from env (strip quotes like
  `data_loader.fetch_alpaca`); `timeout=10`; 401/403 or missing keys → `AccountNotConnected`; other
  non-2xx → `raise_for_status()`. `latest_spy_price` reads `DATA_BASE + "/v2/stocks/SPY/trades/latest"` →
  `body["trade"]["p"]`. Exception messages never include key values.
- [ ] **Step 4: Run** the test file → PASS.
- [ ] **Step 5: Commit** `feat(portfolio): paper-only Alpaca reader`.

### Task 2: Book math (pure)

**Files:**
- Create: `tradehub/portfolio/book.py`
- Test: `tests/test_portfolio_book.py`

**Interfaces:**
- Consumes: nothing (pure; inputs are Alpaca JSON dicts and snapshot rows).
- Produces:
  - `MANUAL = "No idea yet (manual)"`
  - `positions_view(account: dict, positions: list[dict]) -> list[dict]` → rows
    `{symbol, qty, side, market_value, pct_of_book, unrealized_pl, idea}` plus one `{symbol: "Cash", ...}` row;
    `pct_of_book = abs(market_value) / equity`.
  - `composition(rows: list[dict]) -> list[dict]` → `[{idea, pct_of_book, unrealized_pl}]` grouped by `idea`.
  - `scoreboard(snapshots: list[dict]) -> dict` → `{start_at, equity, return_pct, spy_return_pct, ahead_pts,
    max_drawdown_pct, sharpe}`; all return fields `None` with fewer than 2 snapshots. Sharpe = mean/std of
    daily (last-snapshot-per-day) returns × √252, `None` with fewer than 5 days.
  - `curve(snapshots: list[dict]) -> list[dict]` → `[{t, portfolio_pct, spy_pct}]` rebased to 0 at the first snapshot.
  - `closed_trades(fills: list[dict]) -> list[dict]` → FIFO round trips
    `{symbol, qty, entry_price, exit_price, entered_at, exited_at, pnl, return_pct, held_days, idea}`.
  - `win_rate(trades: list[dict]) -> float | None` (share with `pnl > 0`; `None` if no trades).

Snapshot row shape (also the table in Task 3): `{taken_at: iso str, account_number: str, equity: float,
cash: float, spy_price: float}`.

- [ ] **Step 1: Write failing tests** (one per bullet; values exact):

```python
def test_scoreboard_vs_spy():
    snaps = [snap("2026-11-02T15:00Z", 100_000, 500), snap("2026-11-03T15:00Z", 104_820, 510.5)]
    s = scoreboard(snaps)
    assert s["return_pct"] == pytest.approx(4.82)
    assert s["spy_return_pct"] == pytest.approx(2.1)
    assert s["ahead_pts"] == pytest.approx(2.72)

def test_scoreboard_single_snapshot_is_unknown_not_zero():
    s = scoreboard([snap("2026-11-02T15:00Z", 100_000, 500)])
    assert s["return_pct"] is None and s["equity"] == 100_000

def test_max_drawdown():  # equity 100 -> 110 -> 99 -> 120
    assert scoreboard(series([100, 110, 99, 120]))["max_drawdown_pct"] == pytest.approx(-10.0)

def test_short_position_pct_uses_abs_value():
    rows = positions_view({"equity": "10000", "cash": "12000"},
                          [{"symbol": "XLE", "qty": "-20", "side": "short", "market_value": "-2000", "unrealized_pl": "50"}])
    xle = next(r for r in rows if r["symbol"] == "XLE")
    assert xle["pct_of_book"] == pytest.approx(20.0) and xle["idea"] == MANUAL

def test_fifo_closed_trades_with_partial_fills():
    fills = [fill("GLD", "buy", 10, 200, "2026-11-02"), fill("GLD", "buy", 10, 210, "2026-11-03"),
             fill("GLD", "sell", 15, 220, "2026-11-05")]
    t = closed_trades(fills)
    assert [(x["qty"], x["entry_price"]) for x in t] == [(10, 200), (5, 210)]
    assert sum(x["pnl"] for x in t) == pytest.approx(10 * 20 + 5 * 10)
    assert t[0]["held_days"] == 3

def test_empty_inputs():
    assert closed_trades([]) == [] and win_rate([]) is None
    assert positions_view({"equity": "100000", "cash": "100000"}, [])[-1]["symbol"] == "Cash"
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** in `book.py`. Alpaca returns numbers as strings; convert with `float()`. Fills come
  from `/v2/account/activities/FILL` (`symbol, side, qty, price, transaction_time`); sort by time, keep a
  per-symbol deque of open lots, sells (or buys to cover) consume lots oldest first. Every `idea` is `MANUAL`
  in this step.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(portfolio): scoreboard, composition and FIFO closed trades`.

### Task 3: Snapshots table, snapshot job, portfolio API

**Files:**
- Create: `market_sentiment_tool/supabase/migrations/20261030000001_portfolio_snapshots.sql`,
  `tradehub/scripts/portfolio_snapshot.py`
- Modify: `tradehub/api/main.py` (two routes next to `/api/pnl_summary`), `docs/superpowers/plans/migrations-applied.md`
- Test: `tests/test_portfolio_api.py`, `tests/test_portfolio_snapshot_job.py`

**Interfaces:**
- Consumes: Task 1 `paper_get`, `latest_spy_price`, `AccountNotConnected`; Task 2 functions.
- Produces:
  - `GET /api/portfolio` → `{state: "not_connected"|"pre_start"|"live"|"stale", as_of: str|None,
    account_number: str|None, scoreboard: {...Task 2..., win_rate}, curve: [...], composition: [...],
    positions: [...]}`
  - `GET /api/portfolio/closed` → `{state, as_of, trades: [...Task 2 closed_trades...]}`
  - `tradehub.scripts.portfolio_snapshot.main() -> int` (0 ok, 0 + logged skip when not connected, 1 on other errors)

Migration:

```sql
create table if not exists public.portfolio_snapshots (
  taken_at timestamptz not null default now(),
  account_number text not null,
  equity double precision not null,
  cash double precision not null,
  spy_price double precision not null,
  primary key (account_number, taken_at)
);
alter table public.portfolio_snapshots enable row level security;
```

- [ ] **Step 1: Write failing tests** with `get_supabase` overridden by a fake and `paper_get` monkeypatched:
  - `test_portfolio_not_connected_is_200`: `paper_get` raises `AccountNotConnected` and no snapshots → 200,
    `state == "not_connected"`, `positions == []`.
  - `test_portfolio_pre_start_when_account_number_unset`: env unset → `state == "pre_start"`.
  - `test_portfolio_live_uses_snapshots_of_this_account_only`: snapshots for accounts `PA1` and `PA2`, env `PA2`
    → `scoreboard.start_at` is the first `PA2` snapshot.
  - `test_portfolio_stale_when_alpaca_times_out`: `paper_get` raises `requests.Timeout`, snapshots exist →
    `state == "stale"`, `scoreboard.equity` equals last snapshot equity, `as_of` equals its `taken_at`.
  - `test_snapshot_job_inserts_one_row` and `test_snapshot_job_skips_when_not_connected` (returns 0, inserts nothing).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Route reads `/v2/account`, `/v2/positions`, and for `/closed`
  `/v2/account/activities/FILL` (`page_size=100`, follow `page_token` = last id until a short page). Snapshots
  read with the existing `_fetch_all(supabase, "portfolio_snapshots", ...)` filtered by `account_number`,
  ordered by `taken_at`. `win_rate` comes from closed trades. Missing table → existing `_table_fault`.
  The job skips outside 08:30–15:30 CT on weekdays plus one 15:05 CT close snapshot. This is a plain clock check,
  no holiday calendar (ponytail: a holiday snapshot just repeats the last equity; add a calendar if it shows on the curve).
- [ ] **Step 4: Run** the two files, then the full suite → PASS.
- [ ] **Step 5: Record the migration.** Add a row plus watermark to `migrations-applied.md`; `tests/test_migrations_recorded.py` passes.
- [ ] **Step 6: Commit** `feat(portfolio): snapshots table, snapshot job, /api/portfolio`.

### Task 4: Admin check on the server

**Files:**
- Create: `tradehub/api/admin.py`
- Modify: `tradehub/api/main.py` (`app.include_router(admin.router)`)
- Test: `tests/test_admin_auth.py`

**Interfaces:**
- Produces: `require_admin(authorization: str | None = Header(None), supabase=Depends(get_supabase)) -> dict`
  (returns `{"email": ...}`, else `HTTPException(401)`); `GET /api/admin/me` → `{"email": str}`. Step 2's
  Workshop routes use `Depends(require_admin)`.

- [ ] **Step 1: Write failing tests:** no header → 401; `supabase.auth.get_user` raising → 401; user email ≠
  `TRADEHUB_ADMIN_EMAIL` → 401; env unset → 401 (fail closed); matching email (case-insensitive) → 200.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Use `Bearer <jwt>` and `supabase.auth.get_user(jwt).user.email`.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(admin): server-side admin session check`.

### Task 5: Portfolio and Closed-trades pages

**Files:**
- Create: `market_sentiment_tool/src/lib/paperPortfolio.ts` (+ `.test.ts`),
  `src/pages/Portfolio.tsx` (+ `.test.tsx`), `src/pages/ClosedTrades.tsx` (+ `.test.tsx`)
- Test: the three test files above.

**Interfaces:**
- Consumes: Task 3 payloads via the existing `getJson<T>(path)`.
- Produces: `type PortfolioPayload`, `type ClosedPayload`, `fmtPct(v: number | null): string` (`null` → "—",
  sign always shown, 1 dp), `fmtUsd(v: number | null): string`, `stateLabel(state, as_of): string`
  ("Live · as of 2:41 PM CT, Tue Nov 10" / "Stale · last read …" / "Pre-start test account · …" /
  "Account not connected").

Layout (spec 4.2, mockup `portfolio-layout-v2.html`): (1) four big numbers: Account, Since start, SPY same
period, Ahead of SPY. Then the state line, then a recharts `LineChart` of `curve` with portfolio solid and SPY
dashed, then three tiles: Max drawdown, Sharpe, Win rate. (2) Composition: a treemap (`recharts` `Treemap`)
of `positions` by `pct_of_book`, plus an idea list from `composition`. (3) Every position: a table with
Holding, Shares, Value, % of book, P&L, From idea. A link to `/portfolio/closed`. Closed page: a table with
Holding, Shares, Entry, Exit, Result ($ and %), Held, Idea, newest first. Follow the existing dark slate /
emerald language, numbers-first, and read impeccable `reference/craft-floor.md` before UI edits.

- [ ] **Step 1: Write failing tests:** `fmtPct(null) === "—"`, `fmtPct(2.72) === "+2.7%"`; Portfolio renders
  "Account not connected" for `state: "not_connected"` and shows no `$0`; renders "Pre-start test account" for
  `pre_start`; renders the "No idea yet (manual)" row; renders "—" for a null return. ClosedTrades renders an
  empty state "No closed trades yet" and a row's `+$250.00`.
- [ ] **Step 2: Run** `npx vitest run src/lib/paperPortfolio.test.ts src/pages/Portfolio.test.tsx src/pages/ClosedTrades.test.tsx` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; `npx tsc --noEmit -p tsconfig.app.json` clean.
- [ ] **Step 5: Commit** `feat(web): public Portfolio and Closed trades pages`.

### Task 6: Login, admin gate, regrouped menu

**Files:**
- Create: `src/pages/Login.tsx`, `src/components/RequireAdmin.tsx` (+ `.test.tsx`)
- Modify: `src/App.tsx`, `src/App.routes.test.tsx`, `src/App.shell.test.tsx`
- Test: as listed.

**Interfaces:**
- Consumes: `supabase` from `src/lib/supabase.ts`; Task 4 `/api/admin/me`.
- Produces: `<RequireAdmin>{children}</RequireAdmin>`: no session or `/api/admin/me` not 200 → renders
  "Admin only" + a link to `/login?next=<path>`. Step 2 wraps `/workshop` with it.

Routes after this task:
- `/` → `Portfolio` (public)
- `/portfolio/closed` → `ClosedTrades` (public)
- `/predictions` → the current `Home` (public)
- `/journal`, `/sports`, `/jobs`, `/cpi`, `/weather`, `/shadow` → unchanged (public)
- `/scoreboard`, `/models`, `/health` → wrapped in `RequireAdmin` (URLs unchanged)
- `/login` → `Login`

Menu groups: **Portfolio** (Portfolio, Closed trades) · **Predictions** (Overview, Journal, Sports, Jobs
nowcast, CPI Display, Weather, Crypto Shadow) · **Admin 🔒** (Engine Scoreboard, Models, Health, then
Sign in or Sign out). The sidebar money card shows the `/api/portfolio` account value and state label instead
of the suggest-only headline. Keep the `NoOrdersBanner`: it stays true until Step 4. Keep the existing NavLink
comments that still apply.

Gate scope (ponytail): this step gates the operator **pages** only; their APIs stay public as today (the
data is already public and other sites link to them). Gate the APIs when something private sits behind them.

- [ ] **Step 1: Write failing tests:** `/` renders Portfolio's heading; `/predictions` renders Home;
  `/scoreboard` with no session renders "Admin only" and a `/login?next=/scoreboard` link; with a session and
  `/api/admin/me` 200 it renders Scoreboard; with `/api/admin/me` 401 (expired session) it renders "Admin only";
  the menu shows the three group labels; `/login` has no sign-up control.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Login is a form: email, password, `signInWithPassword`, then `navigate(next)`.
  Errors are shown inline. Sign-out is `supabase.auth.signOut()`.
- [ ] **Step 4: Run the full frontend gate:** `npx vitest run`, `npx tsc --noEmit -p tsconfig.app.json`,
  `npx eslint .` → all clean. Then the full Python gate.
- [ ] **Step 5: Commit** `feat(web): admin login, gated operator pages, regrouped menu`.

### Task 7: Ship (orchestrator + Kevin)

- [ ] Apply the migration to Supabase `wuhpbvgidnrrdndhkehl` (orchestrator, via MCP), then check the
  `migrations-applied.md` row.
- [ ] Kevin, in his own terminal: put `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `TRADEHUB_ADMIN_EMAIL`, and later
  `PORTFOLIO_ACCOUNT_NUMBER` in `/opt/stack/.env`. Compose already forwards `ALPACA_*`; the two new names are
  added to the tradehub `environment:` block in `/opt/stack/compose.yml`.
- [ ] Kevin, in the Supabase dashboard: Auth → turn off "Allow new users to sign up"; create his user.
- [ ] Add `portfolio)` to the `/opt/stack/bin/tradehub-job` case statement. Add `tradehub-portfolio.service`
  and `.timer` (`OnCalendar=Mon..Fri *-*-* 13..21:05:00 UTC`, `Persistent=true`). This is a prod change, and
  Kevin approved Step 1.
- [ ] PR → local gate → merge pinned to the full head sha → deploy green.
- [ ] Live checks: `curl /api/portfolio` returns `state` (not 500); `/` renders; `/scoreboard` shows the login
  prompt; a signed-in Kevin sees Scoreboard; the first timer run inserts one snapshot row.
