# Preregistration — the two oil filters on the fifteen-minute v4 family

Frozen 2026-11-19 (action plan step 18). Two new shadow candidates join
`tradehub/fifteen_candidates.py`'s family. Both are scored from their own
PREREG_AT, **2026-11-19T06:00:00Z** — the deep-dive numbers below are the
selection evidence, so the rows they were measured on never score these
candidates. Everything else is the family's frozen machinery: one trade
per window (the earliest accepted row at the live minute), the live
gate's own minute-5 decision as the paired baseline, the promotion
criterion (n >= 100 fresh trades, own low95 > 0, paired low95 > 0,
day-clustered) and the stopping rule (60 days or 300 fresh trades from
the candidate's own PREREG_AT). Promotion is never automatic: eligibility
raises the gate_switch alert and Kevin decides. The live rule is never
touched.

## The evidence (Nov 10 models deep dive, section 1)

1. **Stop buying long shots.** Gated oil trades that bought the side the
   model itself put under 50% won 2 of 18 (−$3.02 a contract). Trades on
   the side the model favoured won 19 of 24 (+$3.63). Gas does not show
   this — the filter is oil-only.
2. **Thin quotes only.** Brent's information is +0.17 when the spread is
   3–4¢ (95 windows) and about 0 at 2¢ or less (294 windows). WTI is
   almost never thin, which is why it has no edge. ("Thin" here means a
   wide quoted spread: the trade only counts at a spread of 3¢ or more.)

## The candidates (frozen)

- **`v4-side50-shadow`** — the live dial (minute 5, 10¢ bar) on WTI and
  Brent only, plus: the taken side's model probability must be at least
  0.50 (`prob_up` for a YES buy, `1 − prob_up` for NO). A row with no
  `prob_up` cannot prove its side and does not pass.
- **`v4-spread3-shadow`** — the live dial on WTI and Brent only, plus:
  the quoted spread at the entry row (`yes_ask − yes_bid`, the same on
  both sides by construction) must be at least 0.03. A row missing a
  quote does not pass.

Each filter gets its own candidate so the record attributes the effect;
a combined candidate is a later question, asked only if both pass.
