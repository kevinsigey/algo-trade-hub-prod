# Preregistration — oil-big-gap-v1 (shadow)

Frozen 2026-11-24 as a preregistered SHADOW. Paper only: nothing here places
an order or touches the live lane's trading path.

**PREREG_AT = 2026-11-24 21:00 UTC** (fixed in review, before merge), set in
`BIG_GAP` in `tradehub/fifteen_candidates.py`.

## Frozen rule

- PREREG_AT = 2026-11-24 21:00 UTC (fixed in review, before merge). Only windows opening at or after it count.
- Series: KXWTI15M and KXBRENT15M only.
- Base decision: the RAW oil rule (oil_fifteen_rule.pick at the first frozen read, the gross 10-point bar, the halt excluded), exactly as oil-trend-agree-v1 builds it.
- Filter: keep the decision only if the gap on the chosen side is at least 15 points: (model probability of that side) − (that side's frozen ask) ≥ 0.15. For YES, side prob = p and the ask is yes_ask. For NO, side prob = 1 − p and the ask is the NO cost the rule pays. Otherwise skip with reason `gap_below_15`.
- Entry: one contract at the frozen ask, held to settlement, Kalshi taker fee ceil(0.07*P*(1-P)*100)/100.
- Grade: against the UNFILTERED raw rule on the same windows. Pass needs ≥150 settled trades, a day-clustered low95 of net cents/contract above 0, and a paired gain over the unfiltered rule with low95 above 0. No stopping rule; it stays shadow until it passes; no parameter changes after PREREG_AT. Promotion needs Kevin's word.

## Implementation notes

- Shares the raw-rule shadow machinery with oil-trend-agree-v1
  (`RawShadow`, `raw_decisions`, `raw_evaluate`, `raw_read`): same first
  freezes, same NO cost (1 − yes_bid), same fee and grade. Recomputed
  read-only from the journal; no new table.
- The gap is rounded to 6 decimals before the ≥ 0.15 test, so a gap of
  exactly 15 points is never dropped by float noise.
- Shown on the Strategies board under WTI and Brent, paired against the
  raw rule, with progress toward 150 per series (the grade pools both).

## Evidence (post-hoc)

On 248 settled WTI+Brent raw trades from Nov 7-24, gaps of 15+ points made
+19.4c/contract (n=69) vs +1.5c for 10-15 points (n=179). The cut was chosen
after seeing the data, so this shadow is the real test.
