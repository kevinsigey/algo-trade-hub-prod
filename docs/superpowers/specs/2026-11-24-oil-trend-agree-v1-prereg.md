# Preregistration — oil-trend-agree-v1 (shadow)

Frozen 2026-11-24, approved by Kevin as a preregistered SHADOW. Paper only:
nothing here places an order or touches the live lane's trading path.

**PREREG_AT = 2026-11-24 18:00 UTC** (fixed in review before merge: the first
window boundary after this PR deploys), set in `TREND_PREREG_AT` in
`tradehub/fifteen_candidates.py`.
Until it is set, nothing is recorded or graded.

## Frozen rule

- Series: KXWTI15M and KXBRENT15M only.
- Base decision: the RAW oil rule (oil_fifteen_rule.pick at the first frozen read, the gross 10-point bar, the 4:45-6:30 PM ET halt excluded), the same decisions the live lane trades (see tradehub/kalshi_live_lane.raw_open_decisions).
- Filter: m15 = ln(P_now / P_prev), where P_now is the underlying price at this window's first freeze and P_prev is the price at the previous window's first freeze, both from the same Hyperliquid tape the model reads (fifteen_min_ticks / the forecast payload; use whatever the analysis scripts used and say which). Keep the decision only if (side == yes and m15 > 0) or (side == no and m15 < 0). Skip when m15 is 0 or either price is missing (record the skip reason).
- Entry: one contract at the frozen ask, held to settlement. Kalshi taker fee rounded up per order: ceil(0.07*C*P*(1-P)*100)/100 with C=1.
- Grading: against the UNFILTERED raw rule on the same series and windows. Pass needs at least 150 settled trades, a day-clustered low95 of net cents/contract above 0, and a paired gain over the unfiltered rule with low95 above 0. Otherwise it stays shadow. No early promotion, and no parameter changes after PREREG_AT.

## Implementation notes (how the rule above is read)

- **Price source:** the forecast payload's `price` field on the journal's
  first frozen row (`journal_forecasts`, forecasters `oil_wti_15m` /
  `wti-15m-v2` and `oil_brent_15m` / `brent-15m-v2`) — the Hyperliquid
  perp price the model read at that freeze. This is what the analysis
  scripts used (`forecasts.csv` → `price`, `px_m15` = the previous
  window's first-freeze `price`). A window is the 15-minute slot its first
  freeze falls in; the previous window is the slot 15 minutes earlier.
- **Recording:** decisions are recomputed read-only from the frozen
  journal rows (first freeze + settlement), the way the live record is —
  no new table, no migration. Only windows opening at or after PREREG_AT
  count. Skip reasons: `disagrees`, `flat_m15`, `no_m15`.
- **Grade:** `trend_evaluate` — kept trades' day-clustered (ET day)
  low95 of net per contract; paired per-window delta vs the unfiltered
  raw rule (kept window: 0, dropped window: minus the raw trade's pnl),
  day-clustered low95. `clustered_low95` is the family's estimator.
  Eligibility raises the `gate_switch` alert from the daily
  `fifteen_candidates_score` run; promotion stays Kevin's word. No
  stopping rule: it stays shadow until it passes.
- **Board:** the Strategies board shows it under WTI and Brent, paired
  against the raw rule, with progress toward 150 (per series; the grade
  pools both).

## Evidence (read-only analysis, 2026-11-24)

Raw-rule trades whose side agreed with the sign of m15, split in time
(train = first 60% of oil/gas windows, test = the rest), ceil fee:

| subset | train | held out |
|---|---|---|
| oil + gas, agrees m15 | +3.7c (n=146) | **+10.8c (n=107, day low95 +2.2)** |
| oil + gas, disagrees m15 | +0.0c (n=130) | +0.4c (n=95) |
| unfiltered rule | | +5.8c (n=204) |
| WTI + Brent only, agrees (post-hoc) | +6.1c (n=76, low95 +0.6) | +23.4c (n=58, low95 +15.6) |

NatGas runs the other way in both halves (agree +1.1c / −4.1c, disagree
+6.4c / −0.2c), so it is out. Momentum as a standalone bet breaks even;
only the filter on the model's own trades held.
