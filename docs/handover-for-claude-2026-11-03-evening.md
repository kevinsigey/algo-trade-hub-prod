# Handover for Claude — Algo Trade Hub, next phase (Tue Nov 3, 2026, ~17:00 CT)

From Muse (the prior operator) to Claude. Kevin's call: **Claude takes over
the next phase of hub work.** Muse is not implementing any of the below —
this file is the whole transfer. Where this file conflicts with the code,
trust the code and tell Kevin.

Repo: `kevinsigey/algo-trade-hub-prod` (GitHub user is **kevinsigey** —
the old `Kevocado` name is dead; never use it). Public hub:
https://algo.40-160-91-131.sslip.io

---

## 1. Where things stand right now

Live main chain (all deployed and verified): … #346 (handover doc) →
#347 per-book machine keys → #348–#351 the weekly critic (loop piece 1).
**Deployed tag: `4ddad300f6c`** (TRADEHUB_TAG in /opt/stack/.env; deploy
workflow "Build and deploy Trade Hub" concluded success for that SHA).
That is the last CODE deploy — this handover's own docs-only merge may sit
on top of it; the code is identical either way.

Working tree: `~/workspace/hub-finish/keys-wt` on Muse's VM holds the
current code. **Its git HEAD is stale (#346)** — shipping here is done by
pushing file contents through the GitHub API (see §6), so the working-tree
FILES equal live main plus the unshipped piece-2 delta below, while
`git status` shows all of #347–#351 as uncommitted noise. Trust file
contents, not the local HEAD. Diff against fetched origin/main if unsure.

### Loop piece 2 — WRITTEN, targeted-tested, NOT shipped (your first job)

The self-improving loop package (Kevin-approved, from the Trading Thesis
Testing chat; adapted from Ray Fu's self-improving-loop guide) has four
pieces in order. Piece 1 (weekly critic) is live. Piece 2 is written and
sitting unshipped in the keys-wt tree:

New files:
- `tradehub/agent/preflight.py` — the ledger pre-flight (design in §3)
- `tests/test_agent_preflight.py` — 6 tests, all passing

Edited files (piece-2 hunks only):
- `tradehub/api/main.py` — `POST /api/agent/interpret` gains a
  `supabase=Depends(get_supabase)` parameter, calls `preflight()` fail-soft
  (an exception returns `{"error": ...}` in the payload, never a 500), and
  enforces the one hard rule: exact duplicate of a killed spec → response
  `spec: None` with the duplicate question first.
- `market_sentiment_tool/src/lib/agent.ts` — `InterpretResult.spec` is now
  `StrategySpec | null`; `Preflight` / `PreflightMatch` types added.
- `market_sentiment_tool/src/pages/Agent.tsx` — draft state is
  `InterpretResult`; a null spec renders "No draft — the ledger answered
  first" with the questions + a `PreflightPanel`; spec editor and Confirm
  button render only when a spec exists.

Gates status at handover: targeted tests 6/6 pass; **full pytest exit 0 —
2569 passed, 12 skipped** on this exact tree (log:
`~/workspace/pf-pytest.log`); **ruff `--select F` = exactly 9**, the
pre-existing baseline. **Frontend gates have NOT been run for piece 2**
(full vitest single-invocation + `tsc --noEmit` still owed — remember the
node_modules symlink and the TMPDIR rule in §6). Do not ship until those
two are also green on this exact tree.

Ship piece 2 as ONE PR containing exactly those five files (see §6 for the
ship mechanics). Then deploy-verify (§6) and live-check: an admin
interpret call whose text resolves to a manual-entry spec (the route is
admin-gated; verification via the test suite plus a Kevin-session call —
say plainly if the live call wasn't made).

---

## 2. Loop piece 1 — the weekly critic (LIVE; know how it behaves)

- `tradehub/workshop/critic.py` + `tradehub/scripts/ideas_critic.py` +
  table `idea_critiques` (migration `20261103000008`, prod watermark row 52,
  RLS on) + critic block on `/api/ideas` + `GET /api/ideas/critic-summary`
  + Ideas-page strip/chips. Cron (deploy's crontab, verified):
  Sundays 23:00 UTC `docker exec stack-tradehub-1 python -m tradehub.scripts.ideas_critic`.
- It RECOMMENDS only (PAUSE/HOLD/WATCH) — never pauses or kills anything.
- Judgment design: the live value is the claim's OWN statistic recomputed
  on the live shadow record via `engine._claim` (same code as the backtest
  judge) — degradation = live − backtest, in the claim's own units. Bands:
  <10 live days → WATCH; NaN live value (claim untestable on the span) →
  WATCH; backtest >0 and (live ≤0 or ratio <0.5) → PAUSE **only with ≥60
  live days** (`JUDGE_DAYS`), else capped at WATCH; ratio <0.75 → WATCH;
  else HOLD. Payloads are sanitized (`_num`) — **Supabase jsonb refuses raw
  NaN/inf**; keep that at every storage boundary.
- First live run (Nov 3): 27 units, 0 failed, **all WATCH** — the entire
  standing book has exactly **1** live shadow day (everything went
  tracked/live Nov 2–3). The worst-degraders ranking requires ≥10 live days
  (`MIN_DAYS`) in both the script and the summary endpoint, so it is
  honestly empty this week. Expect the first meaningful verdicts in a few
  weeks; do not "fix" the all-WATCH state — it is the correct read.
- Store gotcha that cost a crash: `store.get_idea()` returns
  `{"idea": row, "runs": [...]}` — unwrap `["idea"]`.

---

## 3. Loop piece 2 design (already implemented — for your review pass)

`preflight(supa, draft)` in `tradehub/agent/preflight.py`:
- Converts the draft via `gate.to_idea_spec` (manual entries only). If not
  expressible, it compares on the draft's raw `universe` and does not claim
  exactness (`expressible: false`).
- Spec identity (`_canon`): frozenset(hold), frozenset(short), claim,
  JSON of `when`, JSON of `exits`. Sizing/titles/dates are staging, not
  identity.
- Family: `registry.families()` (union-find over shared tickers, PR #340)
  computed over every idea's latest SAVED run plus the draft as pseudo-id
  −1. Payload: family {key, size, tickers}, `prior_attempts` (saved runs
  across family members), `best_prior` (max unseen claim value among exact
  + near matches, with verdict then and `verdict_now` under the current
  standard), and `bar` (ideas tested + the standard's text: claim holds on
  unseen years, clears the hub-wide FDR bar q=0.05, holds in ≥half the
  walk-forward folds).
- Killed matches carry a composed reason, in priority order: (1) demotion
  under the current standard — `registry.adjusted()` verdict_now differs
  from the stored verdict, naming the FDR bar and/or walk-forward; (2) the
  `by` text of the idea's latest `order_switches` row; (3) "killed on
  <date>".
- It informs and never blocks — except the route-level rule above for an
  exact duplicate of a killed spec.

Pieces 3 and 4 are specced in §4 and §5 — not started.

---

## 4. Loop piece 3 — run autopsy (spec, not started)

On every judged Workshop run, attach a failure-pattern diagnosis to the
run record (the run's `result` is the natural home, or an adjacent store
field — your call, with a test): cluster the run's losing trades/entries
by entry condition — market regime at entry (the critic's `regime_tags`
in `tradehub/workshop/critic.py` is reusable), day-of-move size, sector —
name the top recurring pattern in plain language, and say which spec
element it implicates (entry / exit / sizing / gate). When a spec is
revised, the revision flow must surface the prior run's autopsy.
Revisions stay charged through the existing attempt counting
(variations = attempts, seed = id×1000 + attempts, PR #340); **cap
auto-suggested revisions at 5 per idea**. One PR, full gates, deploy
verification — same as every piece.

## 5. Loop piece 4 — book-level circuit breakers (spec, not started)

Per book, in the order path — BOTH the engine's planner path and the
machine-order path (`tradehub/api/machine_api.py`): a max daily loss (% of
equity) and a max drawdown (% from high-water mark). When tripped, new
OPENING orders are refused; closing/protective orders still pass; a
manual-action notice is raised (`manual_actions` table + the existing
notice flow). **Ship the mechanism and tests with thresholds DEFAULTED
OFF — Kevin sets the numbers; do not invent them.** Show breaker state on
each book's portfolio view. One PR, full gates, deploy verification.

---

## 6. Shipping, gates, deploy verification (how work actually lands here)

- Shipping is API-based: `~/workspace/icons/ship.py`,
  `ship(repo, branch, files_dict, message, title, body)` — contents are
  bytes, deletions are None; it opens and merges the PR pinned to the head
  it created and returns (number, merge_sha). **Repo slug:
  `kevinsigey/algo-trade-hub-prod`** — always copy it from the shipping
  clone's `git remote -v`, never from memory (a from-memory slug once
  merged a stray PR into the namesake repo `kevinsigey/algo-trade-hub`).
  Credentials: `dynamic_credentials.add_surrogate_to_request(req,
  'custom.github', entry_name='access_token',
  allowed_hosts=['api.github.com'])` with
  `PYTHONPATH=/opt/muse/skills/custom-connector-setup/bin`.
- **Merge one PR at a time, pinned to its head commit.** A PUT merge can
  405 while `mergeable_state` is "unstable" — read the PR state and retry
  once CI settles.
- **Same-file overlap trap (bit us three times):** back-to-back PRs
  touching the SAME files from the same base can silently DROP the earlier
  PR's hunks. After any such sequence, grep merged origin/main for BOTH
  PRs' markers in EVERY shared file, and run the combined test files on
  merged main.
- **Gate rule:** follow-up edits after a full-suite gate invalidate it.
  Before shipping: full `.venv/bin/python -m pytest -q` (capture output
  under ~/workspace, never /tmp) + full vitest **single invocation** +
  `tsc --noEmit -p tsconfig.app.json` on the EXACT tree, after the FINAL
  edit. **Check exit codes, not just totals lines.** Ruff:
  `ruff check --select F tradehub tests` — true baseline is exactly **9**
  pre-existing errors; add zero.
- Frontend in fresh worktrees: `market_sentiment_tool/node_modules` is a
  symlink to the main clone's — recreate with `ln -s` for test runs and
  **remove the symlink before shipping**. Use `./node_modules/.bin/tsc`
  and `vitest` directly (npx resolves a placeholder). **Full vitest
  ENOSPCs on /tmp (512MB tmpfs): set `TMPDIR=/home/hatch/workspace/.tmp`.**
  Run full suites SOLO — the VM is shared and suites slow/flake under
  concurrency (known flaky-under-load list exists; a solo re-run is the
  arbiter).
- Repo AGENTS.md rule: rebuild graphify before shipping
  (`python -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"`,
  main venv, from the worktree; gitignored, ~1 min).
- **A merged PR is NOT a deployed PR.** Deploy verification = all three:
  (1) the GitHub Actions run of the workflow named exactly
  **"Build and deploy Trade Hub"** for the merge SHA concludes success
  (helper `~/workspace/hub-finish/ghapi.py`: `call(method, FULL_URL)`
  returns a TUPLE `(status, json, headers)`; the actions-runs list must be
  filtered by workflow NAME + head SHA — conclusion filtering misleads);
  (2) `TRADEHUB_TAG` in `/opt/stack/.env` equals the merge SHA prefix;
  (3) a live probe of the changed surface on
  https://algo.40-160-91-131.sslip.io.
- CodeRabbit is rate-limited — Kevin's standing allowance: merge on
  self-review and state that in the PR body.
- Migrations: files in `market_sentiment_tool/supabase/migrations/`,
  applied via `~/workspace/custom-connectors/custom.legacy-supabase/bin/supabase-sql
  --project-ref wuhpbvgidnrrdndhkehl` (same PYTHONPATH as above;
  `NO_PROXY=no_proxy=localhost,127.0.0.1`; SQL on stdin; returns only the
  LAST statement's result set). Every applied migration must be recorded
  in `docs/superpowers/plans/migrations-applied.md` (enforced by
  tests/test_migrations_recorded.py). **Prod watermark: row 52 =
  `20261103000008_idea_critiques.sql`.**
- VPS: `deploy@40.160.91.131`, stack at `/opt/stack`, container
  `stack-tradehub-1`. Muse's route was
  `~/workspace/hub-finish/vps-ssh.sh '<command>'` (takes ONLY the command).
  In-container work: base64-encode scripts and
  `docker exec stack-tradehub-1 sh -c 'echo <b64> | base64 -d > /tmp/x.py && python /tmp/x.py'`;
  `docker cp` FAILS against this container; plain `docker exec`, never
  `docker compose exec`. Files move via `/opt/stack/volumes/tradehub-cache/`
  (= container `/cache`). `/opt/stack/compose.yml` was hand-patched —
  never wholesale-sync it. deploy has NO sudo; systemd units and
  `/opt/stack/bin/tradehub-job` are root-owned (deploy cannot edit them);
  scheduled jobs live in deploy's crontab + root systemd timers
  (paper-orders 12:30 UTC Mon–Fri, paper-protect 14:45 UTC Mon–Fri,
  ideas-shadow 22:30 UTC, ideas_critic Sun 23:00 UTC).

---

## 7. Standing state you are inheriting

- Books: main (Alpaca PA3JI2ZAHBII, "Main book") / big (PA3IJ7MEF, "$1M
  book"). Books module is context-based: `books.use_book(name)` returns a
  contextvars **Token** (not a context manager); restore with
  `books.reset_book(token)`.
- **PASS standard (PR #340):** claim holds on unseen years AND p clears
  the hub-wide Benjamini-Hochberg FDR bar (q=0.05) over every idea's
  latest saved run AND claim held in ≥half the walk-forward folds. Census:
  53 tested · 31 passed · 20 failed · 2 not-enough-data. The chip family
  (8 ideas sharing INTC/MU/TSM/TXN) shows under one "One bet" header.
- **Activations now:** main — Idea 42 @ 10% (auto). Big — exactly
  **[16 @ 8%, 47 @ 1%, 51 @ 1%, 54 @ 1%]**, all auto. Ideas 50 and 56 are
  killed (56 was briefly activated at 1% before the trim — it will not
  order). Idea 16: off on main (switch id 15), on on big (id 16).
- Machine API: keys are per-book since #347 (`api_keys.book`; key 1 "mac
  scripts" = main; a "muse big book" key = big, minted by the Trading
  Thesis Testing chat via direct DB insert — caps mirror key 1: max_qty
  100, max_notional $25k, daily cap 50). Placement submits on the KEY's
  book; `?book=` on reads is a consistency check (mismatch = audited 403).
  Kill switch `TRADEHUB_MACHINE_ORDERS` = "on" (Kevin flipped it). The
  one-`.post(` invariant in alpaca_paper is guarded by tests — preserve
  it. Caps are due a revisit ~Nov 8.
- Book 2 manual position (Nov 3, Kevin-approved, admin route):
  **BUY 684 IBIT, market, DAY, book=big** — Alpaca id
  `7c4e19d6-8716-4b69-929f-81840882f25f`, client id `manual-a40c1ebb8778`,
  submitted after the Nov 3 close → **fills at the Wed Nov 4 open**;
  expected ≈$30k ≈ 3.0% of Book 2 at the $43.86 reference. Confirm the
  exact fill in the Nov 4 report (see §8).
- **Open item on Book 2:** the killed Idea 50's NVDA spread survives there
  — long 1× NVDA261204C00200000, short 1× NVDA261204C00220000 (net ≈ +$935
  at Nov 3 marks, Dec 4 expiry). `kill_book` stops future planning but
  does not close positions. **Kevin's call is pending: leave to expiry or
  close on his word. Do not touch it unasked.**
- Options automation: defined-risk verticals go as ONE mleg order;
  min-1-contract rule for exact 1-buy+1-sell verticals only (one
  contract's max loss must fit the size budget, else a manual-action
  notice — never silent); covered calls get NO min-1. Options calibration
  (#342): skew was REJECTED by the data — zero coefficients shipped,
  machinery retained in `tradehub/workshop/calibration.json`; spreads are
  charged; every options verdict quotes its calibration error.
- OpenRouter hard rule: a `models` array with **more than 3 items is
  rejected (400)** — every caller caps at `[:3]`. Gemini: stay on the
  FREE tier (20 requests/day/model; hub debate cap 10/day) — do not
  retry against the daily cap.

---

## 8. Watch items (dated — report aggregates, Kevin wants these)

- **Wed Nov 4, 12:30 UTC** — first paper-orders run with `day` (not `opg`)
  orders; first orders for Ideas 47/51/54 at 1% on big; **Idea 16's
  big-book first run at 8%** (~106 SPY shares, then the covered call —
  Kevin's watch rule: if the call is refused because shares hadn't
  filled, the next morning's run must place it; if it doesn't, that's a
  bug — failing test first). 56 and 50 are killed and will NOT order.
- **Wed Nov 4, 14:45 UTC** — first paper-protect/fill-check run under the
  both-books version: first `paper_order_checks` rows expected (the table
  was at 0 rows Nov 3 by design).
- **Wed Nov 4 open** — the Book 2 IBIT fill (above): report exact fill
  qty + average price, position value + % of Book 2, cash after.
- **Wed Nov 4 journal runs** — first `natgas_daily` freeze expected
  ~20:15 UTC; first news-tone freezes expected ~11:15/12:15 UTC (the
  sector `*_news_tone` families never froze before the #345 GDELT pacing
  fix). Verify from `journal_forecasts`; if tone is still zero, next
  suspect is GDELT refusing the VPS's shared egress IP.
- **Mon Nov 9, 15:00 CT** — Kozmino probe verdict. **Flag Kevin** (he
  asked twice). Do NOT start any chokepoints v1.5 build.
- Geo shadow (oil_wti_hourly v2-geo-shadow) grades toward its gate:
  ≥200 settled + paired Brier vs v1 AND Kalshi; promotion is Kevin's
  decision, nothing auto-promotes (68 settled at Nov 3 ~01:00 CT).

---

## 9. Kevin's hard rules (non-negotiable)

- **Paper only, never real money. Don't touch the Predictor repos.**
- **Never read or print secrets or /opt/stack/.env values.** Kevin sets
  VPS secrets himself.
- **Ask Kevin before any prod, credential or live-trading change —
  including switching ideas on or off or resizing them.** Show before/
  after before PASS verdicts change. (Exception already granted: the
  "mac scripts" machine key stays active on purpose for auto idea
  trading; the four BLOCKER keys were already rotated by Kevin.)
- **Write a failing test first; check exit codes, not just totals.**
- **Before saying something works, check it on the live site.** Green
  tests have hidden real bugs here (today alone: the critic's first live
  run caught three).
- **paper_orders and order_switches are append-only; every new table
  needs RLS.**
- **Reports: short, exact numbers, aggregate first** — totals, rates and
  a verdict up front; per-item detail only when an item needs his action
  or he asks. Say plainly what you didn't verify.
- **If anything in a handover conflicts with the code, trust the code
  and tell Kevin.**
- Ideas lifecycle: the `ideas_lifecycle_once` trigger sets lifecycle
  fields once; since migration 20261103000004 any idea may be killed;
  the kill endpoint 409s only on already-killed.

## 10. Open decisions parked with Kevin (do not act unasked)

Reverting a stray merge in the namesake repo `kevinsigey/algo-trade-hub`;
retiring `market_sentiment_tool/backend` (needs his explicit go as its
own proposal); PR #172; the Idea 50 NVDA spread on Book 2 (§7); Pyth API
key (Kevin chose "get a key" Nov 3 — he creates it himself; the same key
would serve the natgas forecaster; the journal's frozen CL=F anchor stays
untouched regardless); a free EIA API key (Kevin registers it himself —
unlocks EIA storage in natgas v2); journal DB growth (238MB, ~4MB/day —
rollups are his design call); sector-limit enforcement; circuit-breaker
thresholds for loop piece 4 (§5 — defaults OFF by design); machine-order
caps revisit ~Nov 8.

---

## 11. THE NEXT PHASE — Kalshi Gap Tracker (Kevin-approved Nov 3, via the Trading Thesis Testing chat)

This is the build Kevin is handing you. Verbatim spec first, then hub
context. **Sequencing:** it queues behind the loop package (piece 2
shipped first per §1, then pieces 3–4, then this) unless Kevin reorders.

> **KALSHI GAP TRACKER** — a research/tracking layer over the existing
> Kalshi forecasters, adapted from the prediction-market loop Kevin
> reviewed Nov 3. **TRACKING AND PAPER LEDGER ONLY: no live orders, no
> order placement, no prompts telling Kevin to trade.**
>
> **Purpose:** test whether our model fair values identify real Kalshi
> mispricings after executable prices and liquidity, before anyone
> considers using the signal. Initial markets: the hourly Kalshi crypto
> markets already covered by the crypto forecasters and KXWTI oil markets
> already covered by the oil forecaster. Do not invent coverage where no
> forecaster fair value exists.
>
> **1. SNAPSHOT LOG.** On every forecaster run, store one immutable row
> per contract: timestamp, market/event/contract identifiers, category,
> settlement/resolution time, the official resolution source/rule summary
> (or a null explicitly marked unknown), model fair-value probability +
> model/version identifier, Kalshi bid/ask/mid/last where available,
> spread, volume/open interest where available, and data age. Stale or
> missing market/model data must read UNKNOWN, never zero.
>
> **2. GAP FLAGS.** Flag a contract only when ALL gates pass: absolute
> model-minus-market gap ≥ 8 percentage points using the executable side
> (ask for a hypothetical long YES/NO as applicable, not an unattainable
> mid); >2 hours to settlement; official resolution source is named; and
> liquidity passes — available order-book depth shows the hypothetical
> full position could exit within ≤3% slippage. If depth is unavailable,
> mark liquidity UNKNOWN and do not flag it as tradeable. Store why every
> near-miss failed the gate so the funnel can be audited.
>
> **3. PAPER LEDGER.** For each flagged contract, create at most one
> hypothetical position on a normalized $10,000 tracker bankroll. Size
> with binary half-Kelly using the executable entry price, hard cap 6% of
> current tracker bankroll per position and max 5 concurrent positions.
> Entries use the ask, exits use the bid, and include Kalshi fees where
> the API/fee schedule makes them knowable; if fees are not knowable,
> label P&L gross and do not present it as net. Every entry logs model
> value, market price, gap, size, and its exit condition before the
> position is opened.
>
> **4. MECHANICAL EXITS ONLY:** absolute remaining gap ≤2 points or sign
> flip; model fair value moves >5 points from entry value; <1 hour to
> settlement (exit at the then-current bid if available); or settlement.
> No discretionary overrides in v1. A missing exit quote is UNKNOWN and
> stays open in the ledger with that state shown, not silently marked at
> mid.
>
> **5. GRADING.** Maintain paired forecast-vs-market observations and
> resolved-contract outcomes. Report Brier score and log loss for our
> model vs Kalshi's market price, calibration by probability bucket,
> flag count/funnel conversion, resolved paper-trade count, win rate,
> average entry gap, paper P&L/return, max drawdown, and results split
> crypto vs oil. Compare against simply taking the market price as the
> forecast. The tracker must say NOT ENOUGH EVIDENCE until BOTH minimums
> are met: ≥4 weeks of observations AND ≥150 paired forecast/market
> observations; also show resolved flagged trades separately because pair
> count alone does not validate the trading rule.
>
> **6. PRESENTATION.** Aggregate first, per Kevin's standing rule: a
> compact desk view with current evidence status, model-vs-market Brier
> delta, paper return/drawdown, open paper positions, and the largest
> current PASSING gaps. Contract-by-contract history, gate failures, and
> the full ledger sit behind detail views/dropdowns. This belongs with
> the existing Kalshi/oil/crypto desk surfaces rather than as a new wall
  of tables; keep labels explicit about delayed vs live data and the
  as-of time.
>
> **7. DISCIPLINE AND TESTS.** Unit-test the binary Kelly sizing/caps,
> executable-side gap calculation, liquidity/resolution/time gates,
> mechanical exits, fee/gross labelling, and Brier/log-loss calculations.
> Integration-test from stored fixture snapshots. Do not touch order
> routes or either Alpaca book. Full-suite gate on the exact shipped
> tree (full pytest + full vitest single invocation with TMPDIR off
> tmpfs + tsc) and live deploy verification with real snapshot rows
> before reporting it live.
>
> **Report back aggregate-first when live:** observation window started,
> markets covered, snapshot cadence, any source fields Kalshi does not
> actually provide, and the exact evidence counters that start at zero.

### Hub context for the gap tracker (so you don't rebuild what exists)

- The forecasters already run on the journal's systemd timers (~hourly
  at :15 plus settle/orderbook passes): `btc-hourly-v1` and
  `eth-hourly-v1` (hourly Kalshi crypto; variant 2 was preregistered;
  live record at Nov 3: dead even with the market, inside noise) and the
  oil WTI hourly forecasters behind the journal's scoreboard. Forecasts
  land in `journal_forecasts` (the forecaster column is literally named
  `forecaster`), settlements in `journal_settlements`, scores in
  `journal_scores`. The snapshot log should hook the same run cadence —
  read the journal code before designing the hook.
- Kalshi settles KXWTI hourly on the **Pyth WTI 1-minute candle**; the
  journal forecaster's anchor is Yahoo CL=F, which runs ~10–15 min behind
  (CME redistribution delay). The frozen record's 15-min freshness gate
  is correct and must stay untouched — the gap tracker is a separate
  layer and must not contaminate the frozen journal.
- The existing `gas` forecaster family is KXAAAGASD retail gasoline, and
  `natgas_daily` (KXNATGASD, registered Nov 3 in PR #344, first freeze
  expected Nov 4 ~20:15 UTC) is a different contract family — neither is
  in the gap tracker's initial scope (crypto hourly + KXWTI only).
- New tables need migrations + RLS + a `migrations-applied.md` record
  (§6). Reporting to Kevin is aggregate-first (§9). "Kalshi does not
  actually provide field X" is a finding to report, not a gap to fill
  with a plausible value — UNKNOWN stays UNKNOWN everywhere in this
  build.

---

## 12. What Muse kept

Muse retains the dated watch items in §8 unless Kevin says otherwise,
and the job-search track (nothing in this file). Everything in §§3–5 and
§11 is yours now. Good luck — the live site will tell you the truth
faster than the test suite will; run things live early.
