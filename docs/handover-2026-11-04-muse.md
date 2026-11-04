# Handover — Muse, Wed Nov 4, 2026 (~12:25 UTC)

Supersedes `docs/handover-2026-11-04-next.md` where they differ. Kevin handed
the hub back to Muse on Nov 3 ~23:19 CT with his own work order (live price,
15-minute model, Hormuz adapters, tracker check-in). All three build items
are done and live. One assignment changed hands today: **the Oil page top
rebuild is Claude's task** (Kevin, Nov 4). Live code tag: `00fd7b4369e`.

Rules unchanged from the Nov 4 handover: paper only; never the Predictor
repos; never read/print secrets; ask Kevin before prod/credential/live-trading
changes and before PASS verdicts change (show before/after); failing test
first; check exit codes; verify on the live site, not just green tests; one
PR at a time pinned to its head; reports short with exact numbers and plain
statements of what was not verified.

## Shipped in this session (all merged, deployed, live-verified)

- **#369 — live price settled.** Pyth on the trial key is a dead end without
  Kevin's grant: PYTHOIL plus five more feeds answer 403, and the one open
  feed (WTIZ6) answers 200 with an empty price list under every variant
  probed in-container. Not a parser bug; the status text now says exactly
  that on the board. Hyperliquid is the live price (free, no key, age
  0.0 min; CL ~$96, Brent ~$104, natgas ~$2.89) and already feeds the board
  and the v4 shadow. Do not reopen the Pyth runaround.
- **#370 — 15-minute model v1.** `oil_wti_15m` / `oil_brent_15m` /
  `natgas_15m` journal shadows for KXWTI15M / KXBRENT15M / KXNATGAS15M
  (rules verified live: YES iff the settlement candle closes the window at
  or above its open; Pyth PYTHOIL / BRENT / NATGAS). Drift-scaled random
  walk on Hyperliquid 1-minute candles, preregistered in
  `engines/fifteen_min.py`; bar ~52% at 50c after the quadratic fee. The
  two code comments claiming these markets don't exist are corrected.
- **#371 — geo2 adapters.** `tradehub/geo/stress.py`: continuous stress in
  [0,1] from five Hormuz signal groups (weights 3/3/2/2/1), k = 1 +
  0.75·stress up to 1.75, quakes excluded, unknown-never-zero (a signal
  needs ≥24 history batches and a live value; under 6 of 11 speaking
  weight the read is insufficient and k stays 1.0). Three new shadows:
  `wti-hourly-v5-geo2-shadow`, `wti-v2-geo2-shadow` (daily),
  `natgas-v2-geo2-shadow`. Bases and the v2 geo shadow untouched. First
  live read Nov 4 ~06:10 UTC: stress 0.278 → k 1.209, military saturated;
  the hourly geo2 row had 300 freezes by 11:25 UTC. Known mute point:
  gate_flow cannot speak while its trailing median is 0 (can't collapse
  from a zero baseline, by preregistration).
- **#372 — the cadence fix (a real bug, found live).** #370 added `15min`
  to the code's CADENCES but not to `journal_calendars`' CHECK constraint,
  so the 15m family froze nothing for six hours while its code verified
  fine in-process — the runner's per-forecaster isolation hid it. Same trap
  as the hourly family in 2026-11-01. Migration
  `20261104000001_journal_calendars_cadence_15min.sql` is APPLIED and
  recorded (row 56, new watermark); `tests/test_cadence_parity.py` now
  pins the DB constraint to `contract.CADENCES` so the next cadence fails
  in CI instead of prod. Any future cadence change must widen the DB
  check in the same PR.
- **#373 — 15-minute model v2: every window.** Kevin's call: predict every
  15 minutes. Math unchanged; versions bumped to `*-15m-v2` (v1's rows are
  the pilot, a few market rows only). New runner
  `tradehub/scripts/fifteen_min_run.py` (the journal's own run_forecaster
  narrowed to this roster) on deploy's crontab every 5 minutes, freezing
  each window ~5 minutes in; the +10 pass and the hourly journal dedupe.
  Verified live: the 12:20 UTC pass froze all three v2 models plus market
  rows and settled the prior window. At full coverage the 200-settled
  gate is ~2 days of windows per series.

## Verified state at writing

- Circuit breakers: both books on, not tripped (4% daily / 15% drawdown;
  main daily loss 0.35%, big 0.006% at the 05:20 UTC check).
- Hormuz: all 6 feeds live (snapshot ~every 15 min since Nov 2); AIS
  consumer live; geo_events empty by design; PortWatch pulled Nov 3,
  source data lagging to ~Oct 23.
- Gap tracker: running since Nov 4 02:19 UTC, still NOT ENOUGH EVIDENCE
  (0.125 of 28 days, 80 of 150 pairs at last check; early Brier delta
  +0.0134 against the model on a tiny sample).
- Activations unchanged: main Idea 42 @ 10% auto; big exactly
  [16 @ 8%, 47 @ 1%, 51 @ 1%, 54 @ 1%] auto. Ideas 50/56 killed.

## Watch items — status verified Nov 4

- **Book 2 IBIT (684 sh, market DAY):** Alpaca status `new`, submitted
  Nov 4 09:00:21 UTC, fills at today's regular open **14:30 UTC**. Not
  filled yet at writing — the earlier "fills at the Nov 4 open" note
  meant the US open. Confirm qty + average price after 14:30 UTC.
- **Idea 50 NVDA spread (Book 2):** BOTH legs verified open at ~11:56 UTC
  (long 200C +$1,510 mark, short 220C −$575; net +$935). The idea is
  killed, so today's 12:30 UTC orders run / 14:45 UTC protect run should
  close it via closing_activations — verify both legs are gone after.
- **Today 12:30 UTC paper-orders run:** first `day` orders; first orders
  for Ideas 47/51/54 at 1% on big; Idea 16's first big-book run at 8%
  (~106 SPY shares, then the covered call — #353 made covered calls wait
  for their shares). 14:45 UTC: first paper_order_checks rows expected.
  Report aggregates in chat when checked.
- **natgas_daily first freeze** expected ~20:15 UTC today.
- **Kozmino probe verdict: Mon Nov 9, 15:00 CT — flag Kevin** (he asked
  twice). Machine-order caps revisit ~Nov 8. Pyth trial ends ~Nov 18
  (paired-Brier comparison of v1 / v3-pyth / v4-hl shadows then).

## Decisions left for Kevin

1. **Programmatic rebalance — exact list and sizes.** Unchanged from the
   Nov 4 handover (grouped passing bets; main-book manual positions with
   no closing job listed there). Nothing moves until he says yes to the
   exact list. Show before/after.
2. **Oil page top rebuild — Claude's task now** (Kevin, Nov 4). The plan
   stands as written in the Nov 4 handover's Oil order, step 1: range
   first with Kalshi's beside it, direction "No call" by default,
   "Buy below" replacing "Best edge", "No trade" replacing the best-strike
   banner. Claude: the live ladder is `GET /api/oil/hourly-live`
   (Hyperliquid anchor; geo stress + geo2 now exist — the page predates
   both). Do not let the rebuild change any model or verdict.
3. **Pyth PYTHOIL grant.** His to request or drop; the hub no longer
   depends on it (Hyperliquid covers all three 15m anchors and the hourly
   board). The grant only buys settlement-exact anchoring for the hourly
   shadow comparison before the trial ends ~Nov 18.
4. **Gap tracker:** 3 paper positions on KXWTI-26NOV0414 predate the
   2-per-event cap (#361). Leave, or close early — his call.
5. **PR #172 disposition** and **reverting the stray merge** in the
   namesake repo `kevinsigey/algo-trade-hub` (ship.py slug lesson; the
   real repo is `kevinsigey/algo-trade-hub-prod`). Both still open.
6. **Archive pass** (DB 239 MB at the Nov 4 handover; biggest tables
   signal_events 97 MB, predictions 71 MB): design is in the Nov 4
   handover item 4. Approval needed before anything moves; never touch
   the frozen journal's graded rows without aggregating + verifying.
7. **Cleanup already approved, awaiting an execution slot:** unused
   tables, retiring `market_sentiment_tool/backend` (verify references
   first — Dockerfile, env.py, sniper_regrade, three tests, README).
8. **EIA storage shadow** for natgas (new version, not a natgas-v1
   change): `EIA_API_KEY` is set but no code reads it yet. Build order
   is his; the natural-gas page under Commodities is also unbuilt.

## Pointers

- Clones: `~/workspace/hub-finish/geo2-clone` is at current main and
  clean. `main-1104` and older worktrees are stale — never branch from
  them. Ship via `~/workspace/icons/ship.py`, repo slug copied from the
  clone's `git remote -v`, always `kevinsigey/algo-trade-hub-prod`.
- Full gates before any ship: full pytest (exit code, not the totals
  line) + full vitest + tsc on the exact tree after the final edit;
  ruff baseline is 9 pre-existing F-errors. A merged PR is not a
  deployed PR: workflow conclusion for the merge SHA + TRADEHUB_TAG +
  a live probe.
- The 15-minute runner's log is `/home/deploy/fifteen-min.log` on the
  VPS; its rows land in `journal_forecasts` under `*-15m-v2`.
