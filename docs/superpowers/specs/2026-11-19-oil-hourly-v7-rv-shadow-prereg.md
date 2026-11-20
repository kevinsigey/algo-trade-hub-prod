# Preregistration — hourly oil v7: v4 with the spread from 1-minute realised volatility (wti-hourly-v7-rv-shadow)

Frozen 2026-11-19 (action plan step 16, model item 1 in
`docs/review-backlog-2026-11-12.md`). Frozen BEFORE the first row: only rows
frozen at or after PREREG_AT count toward anything. This file is not edited
once a row exists.

    PREREG_AT = 2026-11-19T12:00:00+00:00

## The claim being tested

The live-feed hourly line (`oil_wti_hourly` at `wti-hourly-v4-hl-shadow`)
prices each strike as a Normal centred on the Hyperliquid perp with a sigma
fitted from Kalshi's own settled hourly changes — the trailing 72 changes,
three trading days of settlements. That sigma is stale by construction: it
mixes regimes up to three days old, and it shows in the calibration. Read
off v4's frozen payloads, its central intervals over-cover: the bands it
states as 65 / 75 / 85% contain the settlement about 73 / 83 / 93% of the
time. The spread is too wide on average, which flattens every probability
toward the middle and gives away Brier score on the strikes that matter.

A sigma read from the perp's own 1-minute tape over the last day tracks the
regime the market is actually in. The claim: the same anchor and the same
interval math with the spread set by 1-minute realised volatility calibrate
closer to nominal and score a better paired Brier than v4 on the same
targets. This is a preregistered shadow, not a switch: v4 and its record
are untouched.

## The variant (frozen)

For every KXWTIH target v4 prices (same freeze lead, same targets), at the
same freeze:

- **Anchor.** The Hyperliquid `xyz:CL` oracle price, read exactly as v4
  reads it (`oil_hl._hl_price_or_none`, tape-vouched). A dead feed is a
  gap, never a stale price; the 15-minute maximum anchor age is v4's.
- **Sigma.** From the same feed's 1-minute candles over the trailing 24
  hours ending at the forecast instant: take the differences of
  consecutive candle closes exactly one minute apart (a missing minute
  breaks the pair, the hourly engine's own adjacency rule), then
  `sigma_h = stdev(differences) * sqrt(60)`, floored at the engine's
  `MIN_HOURLY_SIGMA` (0.05). Fewer than 120 usable differences is no
  forecast — a gap, never a fallback to the settled-changes sigma.
- **Everything else is v4's.** No drift; the settlement is a Normal centred
  on the anchor; the horizon scaling is the engine's `sigma_for`
  (sqrt of minutes-to-close over 60, five-minute floor); the probability
  is `hourly_prob` over the strike's YES interval.
- **Payload.** v4's fields, with `changes_used` replaced by
  `rv_diffs_used`, plus `sigma_source: "rv_1m_24h"` and `rv_sigma_1m`, so
  the record can be audited and the coverage check below can be
  recomputed from frozen payloads alone.

## Grading (frozen)

Paired against v4 (`wti-hourly-v4-hl-shadow`) on identical targets, rows
frozen at or after PREREG_AT only:

1. **Paired Brier.** Mean per-target Brier difference (v7 − v4) with a
   day-clustered 95% lower bound. Negative favours v7.
2. **Coverage.** From each row's frozen payload (`live_price`,
   `sigma_eff`): the settlement's PIT value
   `u = Phi((settlement − live_price) / sigma_eff)`; the central
   65 / 75 / 85% bands are the u-ranges (0.175–0.825, 0.125–0.875,
   0.075–0.925). v7's realised coverage should sit closer to nominal than
   v4's recorded 73 / 83 / 93.

**Verdict** at 300 settled pairs or 2027-01-15, whichever comes first.
Promotion needs Kevin's word — nothing auto-promotes. If the paired Brier
lower bound is against v7 at the verdict point, the shadow is retired and
the record stands as the answer.

## Amendment (2026-11-19, Claude's review of the build PR, before the first freeze)

Two method points tightened before any row froze, so the frozen rule above
reads with them:

1. **One anchor per pair.** v7 scores off the same frozen anchor observation
   v4 used for the target (v4's payload `live_price` / `price_at`, read back
   from its journal row), not a second live read taken seconds later. The
   paired Brier then compares two sigmas, not two anchors. No v4 row for a
   target, no v7 row for it.
2. **Completed minutes only.** The 24h candle read drops the in-progress
   minute, the way `read_window` does: a candle counts only once its minute
   has fully elapsed.
