# Preregistration — the anchor replay test: daily natural gas and Brent on the latest Kalshi 15-minute strike

Frozen 2026-11-19 (action plan step 17, model item 2 in
`docs/review-backlog-2026-11-12.md`; the test proposed in
`docs/review-2026-11-10-models-deep-dive.md` section 3 and
`docs/handover-2026-11-10-claude-review.md` item 3). Frozen BEFORE the
replay is run. This file is not edited once the replay has run; the result
is recorded in the backlog row and the report file.

## The claim being tested

Kalshi's 15-minute strike IS the Pyth index price at each window's open,
and it is public — the hub can read the true settlement index every 15
minutes for free. The daily models that settle on Pyth do not use it:
daily natural gas centres on the NYMEX future (measured gap to the index:
93bp on average, about 3¢ where daily strikes sit 0.5¢ apart; the deep
dive's verdict was "says 99%, gets 94%: the level is off"), and daily
Brent centres on yesterday's settlement with a fitted change model riding
on BZ=F. The claim: re-centring each stored daily row on the latest
15-minute strike plus the perp's move since that strike's window opened
scores a better Brier than the row as frozen. A replay from stored rows
settles it; nothing here is a live shadow.

## The replay (frozen)

- **Population.** Every settled row of `natgas_daily` at `natgas-v1` and
  `oil_brent` at `brent-v1` in `journal_forecasts` joined to its
  `journal_settlements` outcome. (Both lines were retired 2026-11-10; the
  replay judges the anchor, not a resurrection.)
- **Sanity gate.** Each row's stored probability is first recomputed from
  its frozen payload (natgas: `live_price` + `sigma_eff`; Brent:
  `last_settlement`, `horizon_days`, `cl_change_5`, `alpha`, `beta`,
  `sigma`) over the row's YES interval — a "greater" strike read from the
  target ticker, at the engine's resolution (gas 0.001, oil 0.01). Rows
  whose recomputation differs from the stored probability by more than
  1e-6 are excluded and counted; if either series excludes more than 5%
  of its rows, the study reports the mismatch instead of a verdict.

  **Amendment, 2026-11-19 (before any verdict was read):** the first run
  tripped the flood rule on rounding, not on reconstruction error. The
  journal stores probabilities to five decimal places: measured over all
  620 rows, the recomputation's largest absolute difference from the
  stored value is 4.999e-6 and no row differs by more than 2e-5. The
  tolerance is amended to 2e-5 — still two orders of magnitude below the
  error a wrong interval or model reconstruction would produce, which is
  what the gate exists to catch. Nothing else changes.
- **The anchor.** For a row frozen at F: the strike of the latest
  15-minute window of the matching series (KXNATGAS15M / KXBRENT15M) with
  `window_open <= F` — the window from `fifteen_rule_decisions`, the
  strike itself read off that window's market on Kalshi's public record
  (the decisions table stores the ticker, not the strike; pre-run
  correction, noted before any row was scored); plus the perp's move
  since that window opened — Hyperliquid 1-minute candle closes of the
  series' coin (xyz:NATGAS / xyz:BRENTOIL): the close of the candle that
  ends at the window open, and the last close at or before F.

  **Amendment 2, 2026-11-19 (before any verdict was read):** Hyperliquid
  no longer serves the era's candles — a Nov 9 range returns zero rows
  while a Nov 18 range returns a full day — so the perp leg cannot be
  read live for rows frozen Nov 10 or earlier. The hub stored the same
  tape at the time: `fifteen_window_offsets.price` carries the perp read
  at every offset minute of every window from 2026-11-06 06:30Z. The
  perp leg is read from that stored tape instead (the offset-0 price for
  the window open; the last stored price at or before F, at most 2
  minutes stale, for the freeze). Rows frozen before the stored tape
  begins are excluded and counted. This is the deep dive's own framing —
  "a replay from stored rows" — applied to both legs.
  `anchor = strike + (perp(F) − perp(window_open))`. A row with no
  strike yet (frozen before the first recorded window) or no candle at
  either end is excluded and counted.
- **Variant probabilities.** Only the centre moves; every other stored
  input is reused exactly. Natgas: `prob_in_interval(anchor, sigma_eff,
  interval)`. Brent: `mu = anchor + horizon_days × (alpha + beta ×
  cl_change_5)`, `sigma × sqrt(horizon_days)`, same interval — the fitted
  change model riding on the anchored level exactly as it rode on the
  last settlement.
- **Scoring.** Per row: Brier of the original probability, of the variant,
  and of the stored `market_prob`, against the settled outcome. Paired
  differences (variant − original) are averaged per series with a
  **day-clustered** 95% lower bound (rows share days; days are the unit,
  per the deep dive's tracking rules). Report n rows, n days, the
  exclusions, and each series' three Brier means.

## Verdict rule (frozen)

The anchor earns a live shadow build only if, for at least one series,
the paired Brier improvement's day-clustered lower bound is above zero
AND the other series' lower bound is not below zero by more than the
first series' gain. Otherwise the answer is no: the daily lines stay
retired and the strike stays a 15-minute-family input. Either way the
report (`$TRADEHUB_RESEARCH_DIR/anchor_replay.json`) and this verdict are
the deliverable; a shadow, if earned, is a separate preregistered build.
