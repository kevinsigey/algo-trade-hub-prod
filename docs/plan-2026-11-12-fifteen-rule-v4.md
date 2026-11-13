# Better 15-minute rules: backfill, timing, context, and a demo lane (plan for Muse, Nov 12; revised)

Kevin's question was whether "five minutes in, buy the side the model beats by 10+ points after the fee" is the best gate.
His call (Nov 12): **backfill history to choose candidate rules now**, put the best of them on the Kalshi demo account
quickly, add the cheapest promising live features, and look at Kalshi's 15-minute crypto markets the same way.
Claude planned this and **Muse implements it**. Claude reviews every PR before it merges.

## What the data already says (production, Nov 6–12, all six series pooled, in-sample)
`fifteen_window_offsets` records each window's would-be trade at every entry minute. Settled trades at the 10-point bar:

| Entry minute | 1 | 3 | 5 (live rule) | 7 | 11 | 13 | 14 |
|---|---|---|---|---|---|---|---|
| Trades | 228 | 257 | 308 | 340 | 382 | 396 | 344 |
| ¢ per trade, 10-point bar | +7.1 | 0.0 | **+3.3** | +3.9 | +6.7 | +7.0 | +8.0 |
| ¢ per trade, 20-point bar | +9.3 | +10.7 | +5.1 | +10.4 | +9.0 | +10.7 | +12.9 |

Minute 5 looks like one of the weakest entry points, and a 20-point bar beats 10 points almost everywhere. But:
- six days of data is in-sample;
- the rows are correlated (one window appears at up to 15 entry minutes);
- late-minute fills are unproven.

The live rules are also fading: gas went from +17.4¢ per trade on Nov 6–9 to +2.5¢ on Nov 10–12.

## Step A0: the history backfill (one PR, read-only, no rule changes)
Goal: months of history instead of six days, so the question "which minute and which bar" can be answered now.

1. **Kalshi history.** Use the existing `tradehub/backtest/kalshi_history.py` client: series and market lists, then
   1-minute candlesticks (`/series/{series}/markets/{ticker}/candlesticks`, or `/historical/...` for older markets).
   Pull every settled market in the six 15-minute series (`KXNATGAS15M`, `KXWTI15M`, `KXBRENT15M`, `KXGOLD15M`,
   `KXSILVER15M`, `KXCOPPER15M`) as far back as Kalshi serves them. This is read-only public market data: no orders,
   no auth writes.
2. **Underlying tape.** Pull the 1-minute price history the forecaster uses (`SERIES_COINS` and
   `fifteen_tracking._candles_or_empty` show the source) for the same span.
3. **Replay the model.** At each entry minute 1–14 of each window, rebuild the model's probability exactly as the live
   forecaster would: the same engine (`engines/fifteen_min`), the same `sigma_1m` trailing tape, and the same strike
   and window open. Use the candle's yes bid and ask at that minute as the quote, then apply `rule.evaluate` (fee
   netting, halt exclusion) and `rule.pnl`.
   - **Golden check:** for the Nov 6–12 windows the replay must match `fifteen_window_offsets` (same probability within
     1e-6, same side and edge). If it doesn't, stop and report; the backfill isn't trustworthy until it does.
4. **Storage.**
   - A new table, `fifteen_replay_offsets`, shaped like `fifteen_window_offsets` plus `source='replay'`, candle volume,
     and spread. This **needs Kevin's go through Claude**: put the SQL in the PR and don't apply it.
   - Until the table exists, write the replay to a parquet or JSON file under `/cache/research/` so the study can
     run on it straight away.
4b. **Golden check, re-specified (Claude's ruling, Nov 12, after Muse's first run).** The original "every probability
   within 1e-6" check couldn't pass by construction. 82% of stored rows were computed from the live tick price at the
   decision second, and the replay only has 1-minute candles. The first run showed the probability machinery is right:
   tape-sourced rows match 95–100% at every offset (median diff 1.7e-6), and 99.75% of all rows are within 0.01.
   **The new gate has three parts. All must pass before A0 ships:**
   - **(a) Tape rows:** at every entry minute, ≥ 95% within 1e-5. Copper at minutes 13–14 is reported separately, not
     waived.
   - **(b) Tick rows:** ≥ 99% within 0.01, with the share within 1e-5 reported.
   - **(c) Quotes and sides. This is the part that matters for choosing rules.**
     - Compare the replay's yes bid and ask at each entry minute with the stored row's. The median absolute difference
       must be ≤ 1¢, and ≥ 90% must be within 2¢.
     - Where both the replay and the stored row trade, they must pick the **same side ≥ 90%** of the time, with the
       edge within 3 points ≥ 90% of the time.
     - The first run's side agreement was **18.6%**. Two sides at random would agree about 50% of the time, so 18.6% is
       far below chance. That points to a systematic inversion, not candle noise. Check in this order:
       1. yes and no swapped (the no-side cost should be 1 − yes_bid);
       2. bid and ask swapped;
       3. cents versus dollars;
       4. **candle timing**: the minute-M candle covers [M, M+1), so its close comes *after* the decision. Use the
          previous candle's close, or the minute-M open.
       5. the strike direction for "above/below" markets.
     - Fix it, rerun, and report (a), (b) and (c).
   - A row that can't be compared (a missing quote on either side) is counted and reported, never dropped quietly.
   Entry-timing results mean nothing if the replay prices the wrong side, so **(c) is a hard gate.**
5. **Known limits**, to be stated on every output:
   - Candles have no order-book depth, so fills can't be proven. Treat the candle's ask as the price, and flag minutes
     where candle volume is 0 as **unfillable**.
   - The replay can't recover what the model would have seen if the tape had gaps.
   - The replay is for **choosing** candidates. It never counts toward a live record.

## Step A: the "where do the models work" study (one PR, read-only)
Build `tradehub/research/fifteen_where.py`, a script, and a table on the Strategies page's 15-minute section.
Run it on **replay + forward** together, with a column showing each source on its own.

**Replay haircut rule (Claude's ruling on #517, Nov 13).** The A0 replay takes trades the live book never offered:
earliest trade per window, the replay shows −2.43¢ on 1,109 trades while the forward record shows +6.67¢ on 1,326.
So replay results are never used alone to rank or pick a rule:
1. A replay trade fills at the **candle ask + 1¢** and counts only if its edge clears the bar after that haircut
   (`fifteen_replay.REPLAY_HAIRCUT`, `replay_window(haircut=...)`).
2. Replay and forward are **always reported side by side**, for every cell.
3. A candidate is valid only if the replay and forward **agree in direction**, with **forward deciding the size**.

1. **Unit:** one row per (series, window, entry minute), settled only.
2. **Features**, all computed from data available at the entry minute (no look-ahead):
   - entry minute (1–14) and edge bucket (10–15, 15–20, 20+ points after the fee);
   - **trend**: the previous 1, 2 and 3 windows' settle moves for the same series, and whether the model's side agrees
     with the last window's direction;
   - the move so far inside this window;
   - **volatility regime**: `sigma_1m` against that series' trailing 10-day median;
   - market price near 50¢ versus at the extremes, and ET hour band;
   - **scheduled events (new)**: minutes to and from the next and last scheduled release that moves the series:
     - EIA petroleum status (Wed 10:30 ET, Thu when there's a holiday), API inventories (Tue 16:30 ET);
     - EIA natural gas storage (Thu 10:30 ET);
     - CPI, jobs, FOMC decision and minutes days for gold, silver and copper.

     Build a small hand-kept calendar module from published schedules (free). Flag windows that contain or follow a
     release within 15 minutes.
   - **Kalshi order book (new, forward only, since Nov 11)**: from `fifteen_min_ticks` at the entry minute, the
     spread, the ask size on each side, book imbalance (yes ask size against no ask size), and the change in ask size
     over the previous 2 minutes.
   - **Cross-market moves (new)**: the last 5-minute move in the dollar index (or a liquid proxy) for gold, silver and
     copper. The Brent–WTI spread change for the two oils. The 10-year TIPS yield change, daily, for gold. USDCNH for
     copper. Use free sources already in the codebase where possible (`workshop_fred` for daily series). Leave out
     anything that would need a paid feed.
   - **Gas weather (new)**: the latest change in the degree-days forecast (`tradehub/weather_demand.py` snapshot)
     before the window, for natural gas only.
   - **Fillability**: the ask size at entry ≥ 1 and ≥ the demo's 1% size (forward); candle volume > 0 (replay).
3. **Output**: net ¢ per trade after the fee, n, and a **day-clustered** low95 for:
   - each feature on its own;
   - entry minute × edge bucket;
   - two-way crossings only.

   Show it per series and pooled, for all rows and for fillable rows only. Leave any cell under 30 trades blank. Label it
   "in-sample, for choosing what to test".
4. **Paired comparison**: for windows where both minutes trade, the per-window difference between minute M and minute 5,
   with a day-clustered CI. This is the honest answer to "is minute M better than 5".
5. **A "data so far" line**: settled windows and days per series and source, and the date each series reaches the
   sample needed. For a 4¢ paired difference that's roughly 1,000–1,500 matched windows over 15–20 or more trading days.
6. **Tests**:
   - no look-ahead in the trend, event and cross-market features (fixtures where future data would change the answer);
   - the clustered CI is wider than the naive one on correlated rows;
   - fillable filtering works;
   - the paired difference uses matched windows only;
   - the replay matches the golden check from Step A0.

## Step B: candidates, preregistered, then on the demo account (after Kevin and Claude read Step A)
1. **Choose at most two candidate rules.** Use the replay plus the first 70% of forward days. Check them on the
   remaining 30% (day-clustered low95 > 0, fillable rows only) before going further. Example shapes, decided by the data:
   - "minute M, 20-point bar";
   - "minute M, 10-point bar, only when the model's side agrees with the last two windows";
   - "skip windows within 15 minutes of a scheduled release";
   - at most two entry checkpoints per window, fixed in advance.
2. **Preregister each one** in `docs/superpowers/specs/`, frozen before any row, with PREREG_AT at least a day after
   merge, and run it as its own shadow (for example `v4-ctx-shadow`) hooked fail-soft into `fifteen_min_run.py`.
   - The prereg fixes the rule, the series, the holdout result, the promotion bar (≥100 fresh trades, low95 > 0, and the
     paired delta's low95 > 0 against the gate in force), and a stopping rule (60 days or 300 fresh trades).
   - **Promotion is not automatic**: the shadow becomes *eligible*, and Kevin approves the switch.
3. **A demo candidate lane**, so the ideas trade on demo money now.
   - The Kalshi demo runner (`tradehub/kalshi_demo.py`) gets a second lane that also trades the **top preregistered
     candidate**, besides the live gate, on the same demo account.
   - It has its own daily caps (half the live lane's) and each order is tagged with the candidate's `gate_version`.
   - The demo tab shows each lane separately.
   - This needs `kalshi_demo_orders`' unique key to become (series, target, gate_version). That's a migration, so get
     Kevin's go through Claude first.
   - The lane decides at freeze time through the same `fifteen_tracking.open_decisions` path, with the candidate's rule
     applied, and the demo host guard is unchanged.
   - Demo fills still don't prove an edge; the shadow record is the measure.
4. Add every candidate as a column in the decline monitor (#513's per-day table).

## Step C: Kalshi's 15-minute crypto markets (after Step B's demo lane is up)
- **Why there may be an edge.** The commodity model wins when Kalshi's quote lags the underlying's move since the
  window opened. Crypto spot trades 24/7 on deep venues, so any Kalshi lag is visible to the minute. Competition there
  is also stronger, so the edge has to be shown, not assumed.
- **Confirm the series first.** List the series in Kalshi's market data and find the 15-minute BTC and ETH markets.
  The hourly `KXBTCD`/`KXETHD` ladders already feed `tradehub/crypto_board.py`, and `kalshi_feed.py` maps BTC and ETH
  to `KXBTC`/`KXETH`. If there's no 15-minute series, stop and report, and use the hourly ladder instead.
- **Then, in the same order as the commodities:**
  1. A record-only forecaster using the same engine.
  2. The minute tape.
  3. The Step A0 replay on history.
  4. The Step A study.
  5. A preregistered shadow.
- Add crypto-specific features: funding-rate change, the Coinbase–Binance gap, and liquidations (free endpoints only).
- No new tables without Kevin's go.

## Guardrails
- The grid stays small (the features above, at most two-way), every cell shows its n, and every CI is day-clustered.
  Searching dozens of filters and keeping the best one is how the live rule faded.
- Never change a live rule in place. The live v1 rule, the blend and the volatility challenger keep running unchanged.
- No migrations without Kevin's go through Claude. No live Kalshi orders; demo only.
- **Order:** A0 → A, then Kevin and Claude read it, then B, then C. Each is its own PR and stops for Claude's review.
