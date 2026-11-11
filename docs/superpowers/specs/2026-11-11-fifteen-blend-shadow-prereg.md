# Preregistration — the self-weighting blend as a 15-minute shadow (v2-blend-shadow)

Frozen 2026-11-11 (Kevin's commission, on Claude's check review
`docs/review-2026-11-11-muse-check-and-fifteen-loop.md`, Part 3 steps 1–2
only). Frozen BEFORE the first shadow row: only windows opening at or after
PREREG_AT count toward the promotion criterion, and no blend row is written
for an earlier window.

    PREREG_AT = 2026-11-12T00:00:00+00:00

## The claim being tested

The 15-minute models' information comes and goes by day (check review,
Part 2: natural gas's earned weight was 1.29 on Nov 9 and 0.05 on Nov 10;
the other five series sit at roughly zero). A fixed gate on the raw model
trades straight through the days when the model knows nothing. Blending the
model toward the market by how much it has earned — one weight per series,
learned slowly from past days only — should keep the good days' trades,
silence the empty days, and never do worse than the market it blends toward.

Replay on the forward record (Nov 7–11, halt excluded, weights from
earlier days only, from the review): raw rule 219 trades +$4.28 pooled;
blend 23 trades +$5.47, all of them natural gas, at +23.8¢/contract with
low95 +6.0¢ against the raw gas record's +14.9¢ / +2.6¢. The replay chose
this policy after seeing that week's data — which is exactly why it earns a
preregistered shadow record here, not a switch.

## The variant (frozen)

For every targeted window of all six 15-minute series (natural gas, WTI,
Brent, gold, silver, copper), at the same freeze the live rule acts on,
with the same quotes and the same fee-netted 0.10 bar and halt exclusion:

- Let `model` be the frozen probability and `market` the mid of the frozen
  payload's yes bid/ask.
- Let `w` be the series' earned weight for the window's UTC day: the slope
  of (outcome − market) on (model − market) over every settled window of
  that series from the forward record's start (2026-11-04) up to the day
  before, counting contested windows only (market between 0.10 and 0.90),
  clamped to [0, 1]. No contested history, or an undefined slope, gives
  w = 0. The weight is computed once per series per day, persisted, and
  stamped on every row it governs; the raw slope and the contested count
  are persisted beside it.
- Gate on `p = market + w × (model − market)` through the live rule's own
  evaluate (halt, fee netting, 0.10 bar unchanged).
- Rows are stamped gate_version 'v2-blend-shadow' in the blend's own
  decisions table. What stays fixed: the model formula, the fee math, the
  0.10 bar, the halt exclusion, and the live rule itself — its module and
  its decisions are never modified by this build.

## Promotion (frozen criterion, all required, fresh segment only)

    n >= 100 fresh shadow trades (buys, settled, pooled across all six
    series); shadow low95 > 0; policy-paired delta low95 > 0

where low95 is the record's standing convention (mean − 1.96 standard
errors) and the paired delta is per-window (blend PnL − live-rule PnL, a
skip scoring 0) against the live rule's persisted decisions for the same
window. On promotion the audit row lands in the blend's own promotions log
and the live decisions for all six series flip to the blend from that
timestamp, stamped 'v2-blend' by fifteen_tracking — the same dormant-until-
earned wiring the oil shadow uses, consulted independently of the oil
gate's state. One reversal row (`python -m tradehub.fifteen_blend revert`)
restores the raw-model gate for all six series. Evaluation is daily, on the
fifteen-minute runner's pass, in the blend's own evals table.

## Not in this build (the review's later steps, uncommissioned)

Step 3 (a series switching itself off at a 10-day weight under 0.1) and
step 4 (challengers) are NOT built. The blend's weight already silences a
dead series at the gate; nothing here adds a switch, a page callout, or a
second variant.
