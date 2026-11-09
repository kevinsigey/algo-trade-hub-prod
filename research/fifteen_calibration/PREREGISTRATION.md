# Preregistration — Residual-quantile calibration of the 15-minute forecasters

Frozen: 2026-11-09 ~11:35 CT (17:35 UTC), BEFORE any calibration map is fit or any
score is computed. Commissioned by Kevin, 2026-11-09 11:26 CT: "lets run this experiment
in full and see if it improves the current models especially the oil ones since they
are a bit behind the gas model." This file does not change after the freeze; any
deviation is reported as a deviation in RESULTS.md, never edited in here.

## The question

The 15-minute models (`wti-15m-v2`, `brent-15m-v2`, `natgas-15m-v2`) state
P(up) = Φ( ln(price_now / price_at_open) / (σ_1m · √minutes_remaining) ), a drift-scaled
random walk on Hyperliquid 1-minute candles, frozen ~5 minutes into each 15-minute
Kalshi window. Does a recalibration layer — learned per series from the model's OWN
frozen forecast/settlement history, by bucketing past stated probabilities into
quantile bins and mapping stated probability → realized frequency — improve

(a) forecast quality (Brier / log score against Kalshi settlements), and
(b) the fee-net gated trading record (the fifteen-rule's gate, replayed identically),

per series? The per-series answer is the deliverable; nothing is pooled across series.

## Data (audited 2026-11-09 ~11:30 CT, before the freeze)

Source: `journal_forecasts` + `journal_settlements` (Supabase project
`wuhpbvgidnrrdndhkehl`), extracted to `data/{wti,brent,natgas}.json` in this folder.

- Population per series: the v2 model rows that have a Kalshi settlement. Each v2
  forecaster has exactly **one frozen row per target** (325 rows / 325 targets), so
  "the probability as frozen at decision time" is unambiguous — it is that row's
  `probability`, never recomputed with later tape. 324 of 325 are settled; the one
  unsettled row per series is the 2026-11-09 12:30 ET window, still open at extraction.
  **Frozen snapshot: 324 settled windows per series**, frozen 2026-11-04 12:20 UTC →
  2026-11-09 17:05 UTC. Base rates (outcome = window closes at/above open): WTI 158/324
  up (48.8%), Brent 159/324 (49.1%), NatGas 168/324 (51.9%).
- Coverage by UTC day is identical for the three series (one runner freezes all
  three): Wed Nov 4: 47 windows (v2 starts mid-day), Thu Nov 5: 88, Fri Nov 6: 96
  (full), **Sat Nov 7: 20, Sun Nov 8: 4** (the known weekend collapse — Kalshi-side
  availability, ~12% of the weekend's 192 possible windows), Mon Nov 9: 70 (partial
  day at extraction). No `market_prob`, `yes_bid`, or `yes_ask` is null on any row.
- Market probability: the model row's own frozen `market_prob` column — the mid of
  the exact Kalshi quote the gate faced at the same freeze instant (the same live
  market object also supplied the row's `yes_bid`/`yes_ask`). The journal's separate
  `kalshi_implied_*` rows freeze on a different lead (up to 15 min before close vs the
  model's ~10) and differ from this column by mean |Δ| 0.014, max 0.24 (WTI, measured
  in the audit), so they are NOT the decision-time price and are not used.
- Settlements: all 975 from `kalshi:market_result` (Kalshi's own result). Note the
  standing basis: markets settle on Pyth's 1-minute candle close vs open while the
  model reads Hyperliquid perp candles; that basis is part of what any score here
  grades, for raw and calibrated arms equally.
- **Brent provenance (the October gap, closed):** in October Kalshi had no Brent
  15-minute series; it does now. Brent targets are real Kalshi tickers
  (`kalshi:KXBRENT15M-…`) with live two-sided quotes frozen on every row (e.g.
  0.74/0.76), the market row is the KXBRENT15M mid from the same quote, settlements
  are Kalshi's, and the engine file records the series as "verified live 2026-11-04".
  The gate's Brent costs are therefore real KXBRENT15M asks/bids, not a proxy.

## Method (one primary, one variant, one control — the whole family is reported)

All maps are fit PER SERIES, on training windows only (see validation), and applied
to stated probabilities clipped to [0.005, 0.995].

- **PRIMARY — isotonic recalibration on quantile bins.** Sort the training windows'
  stated probabilities; cut 10 equal-count (decile) bins (fewer if duplicate edges
  collapse them; a bin needs ≥ 5 training windows, else merge with the neighbour).
  For each bin take (mean stated prob, realized frequency). Fit a monotone map
  through those points with the pool-adjacent-violators algorithm, weighted by bin
  count. A new probability is mapped by the bin whose training-decile edges contain
  it (below the first edge → first bin, above the last → last bin).
- **VARIANT — Platt scaling.** Logistic regression of outcome on logit(stated prob)
  (intercept + slope, fit by Newton/IRLS on the training windows); map(p) =
  sigmoid(a + b·logit(p)).
- **CONTROL — the primary method applied to the market probabilities** over the same
  windows and folds. If calibrating the market "improves" it as much as calibrating
  the model, the gain is a generic transform artifact, not the model's
  miscalibration being repaired.

Family = 3 series × {primary, variant} + 3 controls. Every cell is logged in
RESULTS.md including failures. **Verdicts are rendered on the PRIMARY only**; the
variant and control are evidence, never alternate verdicts (no method shopping).

## Validation — strict time-order walk-forward

Per series, windows in frozen_at order (ties by target). Expanding training window:

- Initial training set: the first **120** settled windows.
- Then score blocks of **24** windows; refit every map on ALL windows before the
  block before scoring it. A trailing remainder < 8 windows is merged into the last
  block. Expected: 204 scored (out-of-fold) windows per series over 9 blocks.
- A calibration map never sees a window it is scored on. All headline scores are
  computed ONLY on the pooled out-of-fold windows, identical set for every arm.

If a series had < 120 + 8 settled windows it would be reported NOT ENOUGH DATA
rather than shrinking the bar; all three series have 324, so all three run.

## Metrics

1. **Brier score** per series on the out-of-fold windows: raw model, primary-
   calibrated model, Platt-calibrated model, raw market, primary-calibrated market
   (control). Paired per window on identical windows. Headline uncertainty: the
   paired difference (calibrated − raw) gets a 95% CI from a **moving-block
   bootstrap over the out-of-fold window sequence, block length 16, 4,000 resamples,
   seed 20261109**, percentile method. Log score (same clipping) is secondary,
   reported without a verdict.
2. **Gated record replay.** Every out-of-fold window is replayed through the
   fifteen-rule's gate EXACTLY as production defines it (`oil_fifteen_rule.evaluate`
   / `pnl`, MIN_EDGE 0.10): halt windows (frozen 16:45–18:30 ET) skip; a side is
   bought iff its net edge (prob − side cost − Kalshi taker fee 0.07·cost·(1−cost),
   YES cost = yes_ask, NO cost = 1 − yes_bid, quote band 0.02 < yes_bid ≤ yes_ask
   < 0.98) clears 0.10; PnL settles at $1/$0 less the entry fee. Two arms on the
   identical window set: raw probabilities vs primary-calibrated probabilities.
   Report per series: trades, net/contract, win rate, low95 (the record's own
   convention: mean − 1.96·sd/√n).

## Frozen PASS definition (per series)

Calibration **improves** a series iff, on the out-of-fold windows:

(i) primary-calibrated Brier < raw-model Brier with the paired difference's
    bootstrap 95% CI entirely below 0, **and** primary-calibrated Brier ≤ raw
    market Brier (point estimates); **and**
(ii) the calibrated gated record's net/contract ≥ the raw gated record's
    net/contract on the same windows, **while keeping ≥ 60% of its trade count**.

Any other outcome = **does not improve**. Insufficient data = **NOT ENOUGH DATA**.
This definition is not edited after results are seen.

## Reproduction requirement

RESULTS.md hand-verifies one out-of-fold window end to end: its frozen probability
and quotes, the fold map in force (bin edges + fitted values), the bin the
probability lands in and the calibrated value that follows arithmetically, and the
gate's decision and PnL under both arms with the fee arithmetic shown.

## What this study is not

No production change. The live forecasters and the fifteen-rule keep running
uncalibrated whatever the outcome. If a series passes, the follow-on — a live
shadow forecaster version (e.g. `*-15m-v2-cal-shadow`) accruing forward settlements
beside v2 — is PROPOSED in RESULTS.md as Kevin's decision, not built here.
