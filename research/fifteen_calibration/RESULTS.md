# Results — Residual-quantile calibration of the 15-minute forecasters

Study frozen in `PREREGISTRATION.md` (sha256
`1a2ecf81fd81466ccee2e72f3e83b16fe533ac8782a8abe341f323b7e8c1367c`, frozen
2026-11-09 ~11:35 CT, before any map was fit). Run the same day from the audited
snapshot in `data/` (324 settled v2 windows per series, frozen 2026-11-04 12:20 UTC →
2026-11-09 17:05 UTC). Code: `run.py`; full numbers: `results.json`; per-window
out-of-fold probabilities: `oof_*.json`. **No production change was made or is
implied: the live forecasters and the fifteen-rule still run uncalibrated.**

## Verdict up front

**Calibration does not improve any of the three series under the frozen definition —
0 of 3.** WTI's calibrated Brier is better on point estimate but the paired
confidence interval includes zero and it stays worse than the market's Brier. Brent
gains nothing measurable. Natural gas — the series that was already working — is
made **significantly worse** (paired Brier +0.0099, 95% CI [+0.0006, +0.0195]) and
its gated record collapses (+14.4¢ → +3.9¢ per contract). The one genuinely
interesting result is a trading-side observation on WTI (below), which the frozen
definition correctly refuses to call an improvement.

Per series, out-of-fold (204 windows each; walk-forward, initial train 120, blocks
of 24, 9 folds, maps refit per fold on past windows only):

| | Brier raw model | Brier isotonic | Brier Platt | Brier market | Brier isotonic-on-market (control) |
|---|---|---|---|---|---|
| WTI | 0.17936 | 0.17548 | 0.17940 | **0.17111** | 0.17381 |
| Brent | 0.17632 | 0.17579 | 0.17992 | **0.17333** | 0.18563 |
| Natural gas | 0.19013 | 0.20006 | 0.19402 | **0.18733** | 0.18646 |

Paired Brier differences vs the same series' raw probabilities (moving-block
bootstrap, block 16, 4,000 reps; negative = calibration better):

| | isotonic − raw | Platt − raw | control (isotonic − raw market) |
|---|---|---|---|
| WTI | −0.00388 [−0.01271, +0.00298] | +0.00004 [−0.00189, +0.00180] | +0.00271 [−0.00736, +0.01184] |
| Brent | −0.00053 [−0.00926, +0.00762] | +0.00359 [−0.00059, +0.00789] | **+0.01230 [+0.00310, +0.02301]** |
| Natural gas | **+0.00993 [+0.00064, +0.01952]** | +0.00389 [−0.00025, +0.00838] | −0.00087 [−0.01485, +0.00908] |

Gated record replayed on the identical out-of-fold windows (production's own
`evaluate`/`pnl`, fee-net gate at 0.10):

| | raw: trades @ net/contract (win, low95) | calibrated: trades @ net/contract (win, low95) |
|---|---|---|
| WTI | 10 @ +3.5¢ (60.0%, −18.0¢) | 42 @ +7.7¢ (64.3%, −5.9¢) |
| Brent | 14 @ +6.7¢ (50.0%, −12.8¢) | 53 @ +5.3¢ (45.3%, −4.5¢) |
| Natural gas | 37 @ +14.4¢ (59.5%, **+0.7¢**) | 65 @ +3.9¢ (56.9%, −7.4¢) |

Verdicts against the frozen PASS definition, leg by leg:

- **WTI — does not improve.** Leg (i) fails twice: the isotonic Brier gain's CI
  includes 0, and calibrated Brier (0.17548) is not ≤ the market's (0.17111).
  Leg (ii) *passes* in isolation: calibrated net/contract +7.7¢ ≥ raw +3.5¢ with
  42 trades ≥ 60% of 10. The definition requires both legs; it is not met.
- **Brent — does not improve.** Leg (i) fails (diff −0.00053, CI spans 0 widely;
  calibrated still above the market). Leg (ii) also fails: +5.3¢ < +6.7¢.
- **Natural gas — does not improve, decisively.** Leg (i) fails with harm:
  calibration significantly *worsens* Brier. Leg (ii) fails: +3.9¢ < +14.4¢.

Family accounting: 9 scored cells (3 series × {isotonic, Platt} on the model, plus
3 market controls). Two confidence intervals in the whole family exclude zero —
both in the harmful direction (NatGas isotonic; Brent control). No favourable
interval excludes zero anywhere. Log scores (secondary, no verdict) tell the same
story: WTI 0.5371 raw → 0.5321 iso; Brent 0.5281 → 0.5320; NatGas 0.5703 → 0.6011;
market best in every series (0.5162 / 0.5193 / 0.5556).

## Why: the calibration curves, and why oil "lags" gas

Full-sample decile curves (descriptive, in-sample; stated → realized) show all
three models share one distortion: probabilities are too compressed toward the
middle in the 0.30–0.55 band. WTI states 0.30 and realizes 0.18; states 0.44,
realizes 0.36; states 0.51, realizes 0.72. Brent and NatGas rhyme (Brent states
0.43 → 0.45 is its honest bin; its 0.19 bin realizes 0.06). Within a window, a move
that has started persists more than the Gaussian walk's Φ allows — so the model
understates whichever side the drift already favours. That is a real, nameable
bias, and it is exactly the shape isotonic/Platt exist to correct (the fold-9 Platt
fit for WTI indeed learns slope 1.12 > 1).

It still doesn't pay, for one arithmetic reason: **the map's noise is bigger than
the bias.** A decile bin of a 120–312-window training set holds ~12–32 windows, so
each bin's realized frequency carries a standard error of roughly ±9 points. The
bias being corrected is worth ~0.004 of Brier overall. Walk-forward, the fitted
steps are mostly last-fold wiggles — several are non-monotone in-sample (NatGas
states 0.26 and realizes 0.03; Brent states 0.19 and realizes 0.06) and they do not
repeat. The control arm proves the machinery's cost independent of the model:
running the identical isotonic layer over Brent's market probabilities — the
best-calibrated series on the board — made them significantly *worse* (+0.0123,
CI excludes 0). At these training sizes the transform itself is a Brier tax of
roughly +0.003 to +0.012, and no series' miscalibration is large enough to pay it.

And the oil-vs-gas framing, corrected by the data: **on all-window forecast
quality, the market beats every model** (OOF Brier model − market: WTI +0.0083,
Brent +0.0030, NatGas +0.0028) — oil is not uniquely broken; WTI is simply the
furthest behind its own market. Gas's trading lead is a *selection* effect, not
average superiority: the gate only fires on ≥10-point net disagreements, and gas
produces far more of them (37 raw gated trades out-of-fold vs Brent 14, WTI 10),
because gas's 15-minute moves are large relative to the model's σ, so by minute 5
its stated probabilities land far from price more often — and in that selected
tail it has converted at ~60–68% wins near 50¢ costs. Calibration is precisely
the wrong tool for that kind of value: it pulls extreme stated probabilities back
toward bin averages, i.e. it taxes exactly the disagreement tail the gate
monetizes. On NatGas the tax is visible in both legs at once.

The WTI trading-leg result deserves one plain sentence of its own: on out-of-fold
windows, WTI's calibrated probabilities took 42 gated trades at +7.7¢ where the
raw model took 10 at +3.5¢ — the mid-band compression means the calibrated map
pushes many WTI windows *away* from the market price and through the gate. With
10 raw trades the comparison is thin, the forecast leg failed, and the frozen
definition says "does not improve". It is a hypothesis for a future re-test at
larger n, not a result.

## One-row reproduction (hand-verified)

Window: WTI, target `kalshi:KXWTI15M-26NOV090930-30`, frozen 2026-11-09 14:20:05
UTC, first window of fold 9; the map in force was fit on the first 312 settled WTI
windows (2026-11-04 12:20:04 → 2026-11-09 14:05:06 UTC). Frozen row: model
p = 0.45805, market mid 0.535, yes_bid 0.53, yes_ask 0.54, outcome 1 (closed up).

- The fold-9 isotonic map's bins (training stated-prob ranges → fitted values):
  [≤0.154]→0.0968, [0.156–0.245]→0.1935, [0.250–0.342]→0.2258, [0.343–0.408]→0.2581,
  **[0.409–0.479]→0.3438**, [0.481–0.529]→0.6613 (PAVA-pooled with the next bin),
  [0.531–0.590]→0.6613, [0.592–0.658]→0.7097, [0.659–0.758]→0.8387, [0.761–0.962]→0.8438.
  p = 0.45805 lands in the fifth bin: 32 training windows, 11 up → 11/32 = 0.34375;
  the bin needed no pooling (neighbours 0.2581 ≤ 0.3438 ≤ 0.6613), so the calibrated
  probability is **0.34375**. (The run's stored value: 0.34375. ✓)
- Gate under the raw p (fees: 0.07·cost·(1−cost); fee(0.54) = 0.017388,
  fee(0.47) = 0.017437): YES net edge = 0.45805 − 0.54 − 0.017388 = −0.0993;
  NO net edge = 0.53 − 0.45805 − 0.017437 = **+0.0545** < 0.10 → **skip (no_edge)**.
  Production's `evaluate` returns exactly this (best_edge_net 0.054513). ✓
- Gate under the calibrated p: YES net edge = 0.34375 − 0.54 − 0.017388 = −0.2136;
  NO net edge = 0.53 − 0.34375 − 0.017437 = **+0.1688** ≥ 0.10 → **buy NO @ 0.47**.
  Outcome 1 → NO loses: PnL = 0 − 0.47 − 0.017437 = **−0.4874**, matching
  production's `pnl` to the digit. ✓
- This row is the WTI story in miniature: calibration manufactured a 16.9-point
  edge where the raw model saw none — and this instance lost 48.7¢.

Extraction cross-check: replaying the snapshot through production's own gate
functions over the forward window set (frozen ≥ 2026-11-07) reproduces this
morning's live gated record — WTI 6 @ +10.9¢, Brent 10 @ +5.5¢ exactly; NatGas 22
@ +23.9¢ vs the live 21 @ +22.9¢, the difference being the one trade that was
still pending at the live read and settled as a win before extraction.

## Follow-on

No series passed, so the preregistration's shadow-forecaster follow-on
(`*-15m-v2-cal-shadow`) is **not earned and not proposed**. Nothing about the live
models or the rule should change on this evidence. The honest next step is a
re-run of this identical preregistered study when the settled record is larger —
at ~800–1,000 settled windows per series (roughly two to three more weeks at
weekday rates), bin frequency noise falls by about half and a real S-curve bias
of the size seen here would become correctable if it persists. WTI's trading leg
is the cell to watch in that re-run. If Kevin wants the WTI calibrated shadow
anyway, that is his explicit call to make against this verdict, not a
recommendation of this study.

## Deviations and notes

- No deviations from the frozen design. Verdicts are rendered on the primary
  (isotonic) arm only, as frozen; Platt and the market control are reported as
  evidence.
- The market probability is the model row's frozen `market_prob` (the mid of the
  quote the gate faced), per the preregistration's provenance decision; the
  journal's separate `kalshi_implied_*` rows freeze on a different lead and were
  not used.
- Brent's market row is real: KXBRENT15M trades on Kalshi (verified live
  2026-11-04; it did not exist at the October check), with two-sided quotes and
  Kalshi settlements on every row. The gate's Brent costs are genuine asks/bids.
- All three models remain worse than their own market on all-window Brier over
  this week. The fifteen-rule's positive gated record and this fact coexist
  because the gate trades only the disagreement tail; nothing here contradicts
  the rule's record, and nothing here improves it.
