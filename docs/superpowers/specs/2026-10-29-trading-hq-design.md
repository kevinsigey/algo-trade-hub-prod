# Trading HQ: ideas → backtest → paper portfolio (design)

Date: 2026-10-29 · Owner: Kevin Sigey · Repo: `kevinsigey/algo-trade-hub-prod`
(`tradehub/` FastAPI engine, `market_sentiment_tool/` React front end, Supabase, VPS deploy on push to main)

## 1. Intent

The Algo Trade Hub becomes what its name says: a place where Kevin writes a trading idea in plain
words, tests it honestly against history, and — if it earns it — runs it on a paper account whose
results are public. The prediction work that exists today (journal, CPI, jobs, sports, weather,
ERCOT, on-chain) stays, as inputs and as a public record, and keeps getting refined.

Why now: Kevin's IBKR competition (ends Nov 6, handled in Muse, **not** part of this build) showed the
process works — write a thesis, test it on its own data, kill what fails, size with capped loss. He
wants that process permanent, his own, and visible. He is opening new paper positions next week and
wants the portfolio record to start from day one.

Success: (1) Kevin can type an idea and get a trustworthy PASS/FAIL against the idea's own claim;
(2) a stranger with the public link sees the paper portfolio, its results vs SPY, every position at
full size, every published idea with its verdict (fails included), and the predictions — mostly
visual; (3) the record accumulates over time, including kills.

## 2. Goals, non-goals, anti-goals

Goals
- Public portfolio page reading a live Alpaca **paper** account.
- Private Workshop: plain-words idea → Claude draft → Kevin confirms → backtest → verdict, all saved.
- Ideas record: published ideas with claim, verdict, and live paper record.
- Two gates: backtest gate (did it do what it claims) and live-paper gate.
- Later: automated **paper** orders per idea, off by default.

Non-goals
- Real-money trading, ever. No live-broker order path exists anywhere in the code.
- Importing the IBKR competition book or Strategy HQ state. The IB notebooks
  (`/Users/sigey/Documents/IB Python Models`) are guidance for future test types, not data to ingest.
- Accounts for anyone other than Kevin. No sign-up.
- New prediction engines as part of this work.

Anti-goals (would be failure even if it works)
- A verdict that looks confident but was fitted on the same years it reports. Every headline number
  must come from years the idea did not see.
- Hiding fails. Failed and killed ideas stay in the record.
- Any public number without its as-of time and live/stale state.
- Claude silently choosing what an idea means. Every assumption in a draft is shown and confirmed.

## 3. Constraints

- **Paper only.** All Alpaca calls go to the paper endpoint (`paper-api.alpaca.markets` /
  `TradingClient(paper=True)`). A test must fail if any code path builds a non-paper trading client.
- **Credentials.** Kevin is waiting on Alpaca support for new paper keys. Build against the
  `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` already configured (used today for market data in
  `tradehub/core/data_loader.py`). Whether those keys also belong to a paper trading account is
  unknown; the portfolio endpoint must degrade to an honest "account not connected" state rather than
  fail. The VPS `vps-stack/compose.yml` does not pass `ALPACA_*` to the tradehub service today; adding
  them is a prod change Kevin does himself (never read or print `/opt/stack/.env`).
- **Existing honesty rules carry over**: every forecast counts once, nothing overwritten, previews
  never scored; every number labelled with as-of and state.
- Existing deploy, test gates and migration recording (`docs/superpowers/plans/migrations-applied.md`,
  enforced by `tests/test_migrations_recorded.py`) apply.
- The hub's current "suggest-only, no orders placed" stance changes to: **no real orders; paper orders
  only, only for ideas that passed both gates, only when switched on per idea.** Until step 4 ships,
  the hub still places no orders at all.

## 4. What Kevin decided

### 4.1 Site structure

| Section | Audience | Contents |
|---|---|---|
| Portfolio (home page `/`) | Public | Scoreboard, composition, every position |
| Closed trades | Public | Separate page (or expandable section) linked from Portfolio |
| Predictions | Public | Everything that exists today, grouped here, kept visual and plain |
| Ideas record | Public | Published ideas: claim, verdict, live paper record; fails included |
| Workshop | Kevin only (login) | Idea entry, drafts, runs, verdicts, live-paper gate |

### 4.2 Portfolio page (Kevin chose layout "A + composition")

Top to bottom:
1. **Scoreboard**: account value; return since start; SPY return over the same period; points ahead
   of/behind SPY. Equity curve vs SPY. Max drawdown, Sharpe, win rate.
2. **Composition**: a treemap/block chart of holdings by % of account, plus each idea's share of the
   book and its return. Positions not opened by a tested idea are grouped as "No idea yet (manual)".
3. **Every position**: ticker, shares, value, % of book, P&L, the idea that opened it.
- Full sizes and dollar amounts are public (it is a paper account; Kevin's choice).
- Closed trades: entry, exit, result, holding time, idea — on a separate page or a dropdown.

### 4.3 Workshop flow

1. Kevin types an idea in plain words.
2. Claude drafts the test and **Kevin always confirms or edits before it runs.** The draft shows:
   kind of idea, the rules/conditions, instruments, the **claim** (what success means), benchmarks,
   costs, data range and the built-on / unseen split, and every assumption Claude made.
   (Later possibility, not now: show the idea in prose and let Kevin ask for changes conversationally.)
3. The run produces a verdict that is saved forever, pass or fail, grouped with its variations.

### 4.4 What PASS means

PASS means **the idea did what it claims**, not "beat the market". Each idea carries a claim chosen at
draft time. Examples:
- Beat the market: returns more than SPY after costs.
- **Ballast** (Kevin's definition): on SPY's down days it loses less than SPY **and** its overall return is
  positive — **or** it goes up on SPY's down days.
- Relationship: "gold beats stocks when rates rise" — tested on the condition periods.
- Smoother ride: similar return with a smaller worst drawdown.

To PASS, the claim must hold **on years the idea was not built on**, and the result must beat random
timing (shuffle/permutation test). SPY/QQQ/IWM comparison is shown on every verdict as context, and is
the bar only when the claim is to beat them. Supporting statistics shown on the verdict: t-test of the
claimed relationship, consistency across market periods, number of variations tried (which raises the
bar). Kevin and Claude will keep adding test types over time; the verdict must make room for more checks.

### 4.5 Two gates

1. Backtest gate: the PASS above.
2. Live-paper gate: a passed idea starts its paper record only when it also clears a second check and
   Kevin presses the button. After that, its paper record is measured against its own claim and it can
   be killed on record.

### 4.6 Live paper record and attribution (Kevin's answers to the builder check)

- **An idea's live paper record is a shadow track**: from the day it clears the live-paper gate, the hub
  applies the idea's confirmed rules every trading day and records what the idea would have done,
  whether or not Kevin traded it. Kevin's real Alpaca trades tagged to the idea are shown beside it.
  The claim check and the "claim failing on paper" flag run on the shadow track. When an idea fails,
  Kevin stops tracking it (kill button); its record up to that day stays.
- **Positions get their idea by tagging the order when Kevin places it** (Alpaca `client_order_id`
  prefix; the Workshop shows the exact tag to paste for each live idea). Untagged positions show as
  "No idea yet (manual)".
- **Positions can be relabelled later.** Every relabel is appended to a visible history (who, when,
  from, to); the original tag is never erased.

### 4.7 Build order

1. Login + Alpaca portfolio pages (Portfolio, Closed trades) + nav restructure. Target: live before Kevin
   opens new positions next week (Nov 2 or later; not a hard deadline).
2. Workshop with the first test type: **relationship / ballast / conditional** ideas on daily prices
   and FRED macro series. Then rule-based "buy when X, sell when Y" ideas (Verdict-style:
   losingloonies.ca/verdict is the inspiration). Then new test types built together (e.g. earnings
   reaction/drift, implied vs realized, as in the IB notebooks).
3. Ideas record + live-paper gate.
4. Automated paper orders per idea, off by default.

## 5. Claude's calls (Kevin can overturn)

- Login: a single admin user via Supabase Auth (already in the stack); no sign-up route; Workshop API
  routes require Kevin's session (server-side check, not just a hidden link).
- Today's Scoreboard, Models and Health pages are operator views and move behind the login; everything
  else that exists moves under Predictions.
- The portfolio job snapshots the Alpaca account daily and during market hours into Supabase, so the
  equity curve has history independent of Alpaca's own history API.
- Data sources for backtests: daily prices from Alpaca/Tiingo (both already wired), macro from FRED
  (already wired); free sources first.
- Default built-on / unseen split: the most recent ~30% of the data range is unseen, shown as a line on
  the chart. Shuffle test default: 1,000 permutations, 95% bar.
- Live-paper gate default contents: the claim still holds on the most recent 12 months; position size
  within a book limit (default max 25% of account per position); Kevin's button.
- Idea drafting uses the Claude API with the latest model; drafts are stored with the exact rules that ran.
- Ideas are private until Kevin publishes them to the Ideas record.
- "Since start" begins at the first snapshot of the **new** paper account Kevin is setting up; no
  backfill from older account history. Until then the page shows "account not connected" or, if the
  current keys reach a paper account, labels its numbers as a pre-start test account.
- The live-paper gate's recheck uses only data that arrived **after** the backtest's data end, so it is
  genuinely new evidence; if too little new data exists yet, the gate says "waiting for data".
- A variation is any run under the same idea with changed rules or parameters. The permutation-test
  bar is Bonferroni-adjusted by the number of variations (0.05 / n); the count is shown on the verdict.
- Killing a live idea is Kevin's button. The system flags "claim failing on paper" (claim check over
  the idea's live record, rolling 3 months) but never kills on its own.
- The nav restructure changes the hub's own menu only; the shared global nav on the other sites keeps
  its links (pages that move behind login keep their URLs and show the login prompt).
- The 25% per-position limit is checked at the live-paper gate, and enforced on every order once
  automated paper orders exist (step 4).
- Kevin adds any new server secrets (Alpaca paper keys, Claude API key, Supabase auth settings) to
  the VPS himself. The existing `tradehub/backtest` is Kalshi-specific; the price/FRED test engine is new.

## 6. Left to the builder

Schema details, API shapes, chart components (reuse what the journal/league work already uses), job
scheduling mechanism on the VPS (follow the existing systemd timer pattern), how test types are
registered so new ones can be added, and visual design within the existing site language
(numbers-first, plain, mostly visual).
