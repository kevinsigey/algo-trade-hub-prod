# Preregistration — the volatility-regime challenger to the 15-minute blend (v3-volregime-shadow)

Frozen 2026-11-12 (Kevin's commission, action plan step 5, on Claude's review
`docs/review-2026-11-11-muse-round2-and-regime-challenger.md`, Part 2 and
Part 3 item 4). Frozen BEFORE the first row: only windows opening at or after
PREREG_AT count toward anything, and no row is written for an earlier window.
This file is not edited once a row exists.

    PREREG_AT = 2026-11-14T00:00:00+00:00

## The claim being tested

The blend (`v2-blend-shadow`, preregistration
`2026-11-11-fifteen-blend-shadow-prereg.md`) gives each series one earned
weight per day. The in-sample split in the review says one weight is too
coarse: natural gas earns about 1.08 on fast-moving windows and about 0.26 on
quiet ones (Brent leans the same way, more weakly). The mechanism fits: Kalshi's
quote lags the move, and the lag matters more when the move is large. Two
weights per series, split by volatility and learned from earlier days only,
should trust the model more when it moves fast, less when it is quiet, and beat
the blend on the same windows. The in-sample split used look-ahead, which is why
this is a preregistered shadow, not a switch.

## The variant (frozen)

For every targeted window of the six 15-minute series (natural gas, WTI, Brent,
gold, silver, copper), at the same freeze the live rule acts on, with the same
quotes, the same fee-netted 0.10 bar and the same halt exclusion:

- **Volatility measure.** `sigma_1m` from the window's first frozen forecast
  payload: the standard deviation of consecutive 1-minute log returns over the
  unbroken trailing tape (up to 90 minutes) at the freeze, floored
  (`engines/fifteen_min.realized_sigma_1m`). It is the exact number the model
  divides the in-window move by, persisted at the freeze, so it carries no
  information from after the freeze.
- **The regime split.** For a window on UTC day D, the series' median is the
  median of `sigma_1m` over that series' first frozen forecasts for windows
  opening in [D − 10 days, D), earlier days only. A window is **high** when its
  `sigma_1m` is strictly above the median, **low** otherwise. No earlier
  `sigma_1m` (no median) means no regime and weight 0.
- **The weight.** For each (series, regime, D): the blend's earned-weight slope
  of (outcome − market) on (model − market), contested windows only (market
  between 0.10 and 0.90), over the series' settled windows from the forward
  record's start (2026-11-04) up to D, keeping only the windows whose frozen
  `sigma_1m` falls in that regime under day D's median. Clamped to [0, 1].
  Fewer than 30 contested windows, or an undefined slope, gives weight 0. The
  median, the two weights, their raw slopes and contested counts are computed
  once per series per day on the first pass, persisted, and read back on every
  later pass (late settlements never rewrite a day).
- **The gate.** `p = market + w × (model − market)`, with `w` the weight of the
  window's own regime, through the live rule's own evaluate (halt, fee netting,
  0.10 bar unchanged). `market` is the mid of the frozen payload's yes bid/ask.
- Rows are stamped gate_version `v3-volregime-shadow` in the challenger's own
  tables (`fifteen_volregime_decisions`, `_weights`, `_evals`). What stays fixed:
  the model formula, the fee math, the 0.10 bar, the halt exclusion, the live
  rule and its decisions, and the blend and its frozen rows and scoring. None of
  them is modified by this build.

## Scoring (fresh segment only)

Fresh = window open at or after PREREG_AT. Trades are buys with a settlement.
low95 is the record's standing convention (mean − 1.96 standard errors). The
paired delta is per window: challenger PnL − blend PnL on the same (series,
window), a skip scoring 0, counted only where both rows exist and are settled.
Evaluated once a day on the 15-minute runner's first pass, one row in
`fifteen_volregime_evals`.

Beside the frozen low95 and paired low95, the evals row and the page also carry
a **day-clustered low95** (windows clustered by series and ET day, the
cluster-robust standard error of the mean): it is informational only, was added
before any rows exist, and is not part of the promotion bar.

## Promotion bar (frozen, all required)

    n >= 100 fresh trades (pooled across all six series);
    challenger low95 > 0;
    paired delta (vs v2-blend-shadow) low95 > 0

The challenger may take the live gate only after the blend has been promoted
(the blend's promotions log reads `v2-blend`). Until then it is a record only.
**This build contains no promotion path:** the evals row records whether the
bar is met and whether the blend is promoted, and nothing writes to any
promotions log or touches the live gate. Wiring a promotion, if the bar is ever
met after the blend's promotion, is a separate commission.

## Stopping rule (frozen)

If the promotion bar is not met within 60 days of PREREG_AT (2027-01-13
00:00 UTC) or by 300 fresh trades, whichever comes first, the challenger is
retired as a record: it stops counting toward promotion and its rows stay as
they are.

## Not in this build

No series switch, no third regime, no tuning of the median window, the 30-window
minimum or the split. One challenger at a time, per the review's step 4.
