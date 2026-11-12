# Better 15-minute rules: when to decide, and with what context (plan for Muse, Nov 12)

Kevin's question: is "five minutes in, buy the side the model beats by 10+ points after the fee" the best gate?
His idea: give the decision context (the last few 15-minute moves) and trade only where the models actually do
well, instead of an arbitrary minute 5. Claude planned this; **Muse implements it.** Claude reviews before any merge.

## What the data already says (production, Nov 6–12, all six series pooled, in-sample)
`fifteen_window_offsets` already records each window's would-be trade at every entry minute (`offset_min` 0–14,
with `edge_net`, `side_cost`, `outcome`, `pnl`, `move_to_settle_bps`). Settled trades at the 10-point bar:

| Entry minute | 1 | 3 | 5 (live rule) | 7 | 11 | 13 | 14 |
|---|---|---|---|---|---|---|---|
| Trades | 228 | 257 | 308 | 340 | 382 | 396 | 344 |
| ¢ per trade, 10-point bar | +7.1 | 0.0 | **+3.3** | +3.9 | +6.7 | +7.0 | +8.0 |
| ¢ per trade, 20-point bar | +9.3 | +10.7 | +5.1 | +10.4 | +9.0 | +10.7 | +12.9 |

Read with care:
- Minute 5 looks like one of the worst entry points, and a 20-point bar beats 10 points almost everywhere.
- These numbers are in-sample, pooled over six series, and the windows aren't independent (one window counts at up to 15
  entry minutes, and same-day windows move together).
- Late minutes may not be fillable at the recorded price, because the book is thin near the close. That has to be checked against `fifteen_min_ticks` ask
  sizes before any late-minute rule is believed.

The live rules are also fading. Gas went from +17.4¢ per trade (Nov 6–9) to +2.5¢ (Nov 10–12), and oil and metals are now negative.

## Step A: a "where do the models work" study (read-only, one PR)
Build `tradehub/research/fifteen_where.py` plus a script, and publish its output as a table on the Strategies page's 15-minute section.

1. **Unit of analysis.** One row per (series, window, entry minute) from `fifteen_window_offsets`, joined to
   `fifteen_min_ticks` for the ask size at that minute and to the journal forecast payload for `sigma_1m`. Settled
   rows only.
2. **Context features**, all computed from data available at the entry minute (no look-ahead):
   - entry minute (1–14);
   - edge after fee (bucket it: 10–15, 15–20, 20+ points);
   - trend: the previous 1, 2 and 3 windows' settle moves (`move_to_settle_bps` of earlier windows of the same
     series), and whether the model's side agrees with the last window's direction;
   - the move so far inside this window: price against the open at the entry minute;
   - volatility regime: `sigma_1m` against that series' trailing 10-day median;
   - market price level: near 50¢ versus at the extremes;
   - session and time of day (ET hour bands), and the ask size at entry.
3. **Output.** Net ¢ per trade after the fee, trade count, and a **day-clustered** low95 for:
   - each feature on its own;
   - entry minute × edge bucket;
   - a small set of two-way crossings (minute × trend agreement, minute × regime).

   Report per series and pooled.
4. **Fillability.** Mark each row fillable when the ask size at entry is ≥ 1 (and ≥ the demo's 1% size). Report every figure
   twice: all rows, and fillable rows only.
5. **Honesty.** Show the n behind every cell, and leave a cell blank below 30 trades. Label the table "in-sample, for
   choosing what to test". Nothing in this step changes a rule.

## Step B: preregister one or two candidate rules, as new shadows (separate PR, after Kevin and Claude read Step A)
- **Pick before you test.** From Step A, choose at most **two** candidates, using a train window (the first 70% of days). Example
  shapes, decided by the data and not by this plan:
  - "minute M, 20-point bar";
  - "minute M, 10-point bar, only when the model's side agrees with the last two windows' trend";
  - "skip high-volatility windows".
  - Optionally, at most two entry checkpoints per window, never "pick the best minute afterwards".
- **Write the preregistration** in `docs/superpowers/specs/`, frozen before any row, with PREREG_AT at least a day after merge. It
  fixes the rule, the series it covers, the holdout check (the last 30% of days, day-clustered low95 > 0, reported before
  going live as a shadow), and the same promotion bar as the blend: ≥100 fresh trades, low95 > 0, and the paired delta's low95 > 0 against the gate in force.
- **Run each candidate as its own shadow version** (for example `v4-ctx-shadow`), with its own decisions table, hooked fail-soft
  into `fifteen_min_run.py`, the same way `fifteen_blend.py` and `fifteen_volregime.py` are.
- **Never change a live rule in place.** The current v1 rule, the blend and the volatility challenger keep running unchanged.
- Add each candidate as a column in the decline monitor (#513's per-day table).

## Guardrails
- **Six days of data is not much.** The grid stays small (the features above, at most two-way), every cell shows its n, and every CI is
  day-clustered. Searching dozens of filter combinations and keeping the best one is how this rule faded in the first place.
- No migrations without Kevin's go through Claude. No live Kalshi orders. The demo runner keeps following the live gate only.
- Tests: no look-ahead in the trend features (a fixture where a future window's move would change the answer), the
  clustered CI is wider than the naive one on correlated rows, and fillable filtering works.

## Order
1. Step A (the study and its table).
2. Kevin and Claude read it.
3. Step B (preregister, then the shadows).

Claude reviews every PR before it merges.
