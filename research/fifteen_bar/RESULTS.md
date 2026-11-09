---
title: "Fifteen-minute rule: would a 5-point net-edge bar beat 10 on the oil series?"
type: research-note
domain: oil
status: complete
settlement_source: Kalshi settlements via journal_settlements (hub record)
tags: [fifteen-rule, edge-gate, counterfactual, oil, kalshi]
summary: "Counterfactual on the frozen forward record: oil's edges ARE thinner than gas's, but the [5,10) band the lower bar would admit lost money on oil (-2.9c/contract combined; WTI -11.6c). Recommendation: do NOT amend the oil bar to 0.05. Brent alone is not-enough-data."
---

# Results — a 5-point bar for the oil series? (counterfactual, 2026-11-09)

**Question (Kevin, 2026-11-09):** oil's edges are probably thinner than natural
gas's — should the fifteen-rule's net-edge bar be +5 points instead of +10 for
the oil series, to capture them?

**Method:** no new model runs. A snapshot of production tables pulled
2026-11-09 ~18:17 UTC (`data/`: journal_forecasts, journal_settlements,
fifteen_rule_decisions, fifteen_window_offsets) was replayed through the
production rule's own functions (`tradehub.oil_fifteen_rule` — `net_edges`,
`pnl`, `_stats`, halt and session rules) at bars 0.10 and 0.05 over the
identical window set: first frozen forecast per target, halt windows excluded,
settled only, forward only (frozen at/after PREREG_AT 2026-11-07T00:00Z). The
decision point is the freeze, ~5 minutes into each window. Code: `analyze.py`;
full numbers: `results.json`. **No production change was made: the live gate
still runs at 0.10 for every series.**

**Validity, before anything else:** the replay at the live 0.10 bar reproduces
the production gated record *exactly* — 39 trades, +17.9¢/contract (WTI 7 @
+16.4¢, Brent 10 @ +5.5¢, natural gas 22 @ +23.9¢, total +$6.97, low95 +5.3¢) —
and the persisted decisions table's `best_edge_net` matches the recomputed
freeze-moment edge on 474 of 474 comparable windows (worst difference 3e-8).
One snapshot caveat found and fixed during the audit: the SQL pull renders
timestamps with a space separator, so all date comparisons here are on parsed
datetimes (a string compare silently drops every Nov 7 window — the
closed-session Saturday ones).

## The descriptive claim is TRUE: oil's edges are thinner

Best-side net edge on offer at the freeze, forward windows that were quoted and
not halted (WTI 94, Brent 93, natural gas 95 windows):

| Series | Mean | Median | P75 | <0 | 0–5 pts | 5–10 pts | ≥10 pts |
|---|---|---|---|---|---|---|---|
| WTI | +3.7 | +2.7 | +5.5 | 19% | 53% | 20% | **7%** |
| Brent | +3.3 | +2.0 | +6.3 | 37% | 33% | 18% | **12%** |
| Natural gas | +7.0 | +3.7 | +8.4 | 21% | 36% | 19% | **24%** |

Only 7% of WTI windows and 12% of Brent windows ever clear the live bar, vs
24% for gas. Kevin's premise holds — the oil distributions sit lower.

## The counterfactual: the [5,10) band loses money on oil

Settled forward trades. "@0.10" is the live record; "band" is exactly the
trades a 0.05 bar would add; "@0.05" is the combined record under the lower bar.

| Series | Record | n | Net/contract | Win | Low95 | Total |
|---|---|---|---|---|---|---|
| WTI | @0.10 | 7 | +16.4¢ | 71% | −8.8¢ | +$1.15 |
| WTI | band 5–10 | 19 | **−11.6¢** | 37% | −26.4¢ | −$2.19 |
| WTI | @0.05 | 26 | −4.0¢ | 46% | −17.5¢ | −$1.05 |
| Brent | @0.10 | 10 | +5.5¢ | 50% | −16.7¢ | +$0.55 |
| Brent | band 5–10 | 17 | +6.8¢ | 47% | −12.7¢ | +$1.15 |
| Brent | @0.05 | 27 | +6.3¢ | 48% | −8.2¢ | +$1.70 |
| **Oil combined** | @0.10 | 17 | +10.0¢ | 59% | −6.4¢ | +$1.70 |
| **Oil combined** | band 5–10 | 36 | **−2.9¢** | 42% | −15.2¢ | −$1.05 |
| **Oil combined** | @0.05 | 53 | +1.2¢ | 47% | −8.7¢ | +$0.65 |
| Natural gas (ref) | @0.10 | 22 | +23.9¢ | 68% | +5.7¢ | +$5.27 |
| Natural gas (ref) | band 5–10 | 18 | +2.2¢ | 61% | −16.1¢ | +$0.39 |
| Natural gas (ref) | @0.05 | 40 | +14.1¢ | 65% | +0.9¢ | +$5.66 |

Session split of the band trades: WTI negative in both (open 15 @ −12.7¢,
closed 4 @ −7.1¢). Brent's positive band read is entirely open-session (12 @
+13.3¢) against a negative closed slice (5 @ −9.1¢, too thin to judge).

Read: on oil, the marginal band is 36 trades at −2.9¢ — lowering the bar would
have *reduced* oil's total (+$1.70 → +$0.65) while tripling its trade count,
and turned WTI's record negative outright. Even on gas, the [5,10) band earns
+2.2¢ against the ≥10 core's +23.9¢: the 5–10 zone is mostly model error, not
unharvested edge — the same shape the calibration study found (the gate earns
in the disagreement tail). The thinner oil distribution is real, but the extra
trades it would admit are the wrong ones.

**Sample honesty:** the oil band is n=36 (WTI 19, Brent 17) and every band
low95 crosses zero — no cell here is a settled statistical verdict. What the
data does support: WTI's band is negative on point estimate, win rate and both
sessions at n=19; the combined oil band is negative at n=36. Brent is the one
series the data does *not* contradict (band +6.8¢ at n=17, low95 −12.7¢) —
that is NOT ENOUGH DATA, not evidence for an exception.

## Sensitivity: entry minute (different lever, noted for completeness)

Recomputing the same [5,10) band as hypothetical entries at other minutes
(offsets table; overlapping cohorts, includes the runner-era windows, so
character only): at the freeze minute (5) the oil band is −3.5¢ (n=63) and gas
−0.9¢ (n=32), consistent with the primary read. At minute 1 the oil band shows
+26.7¢ (n=37, low95 +13.5¢) — that is the entry-*timing* effect the offset
dataset already flagged (minute 1 was the best realized entry overall), not
evidence about the freeze-moment bar. If oil has an unharvested lever, the
data points at *when* it enters, not at a lower bar for the same minute.

## Recommendation: AGAINST amending the oil bar to 0.05

- **WTI: against, on the numbers.** The band it would admit lost 11.6¢ a
  contract; the 0.05 record is negative where the 0.10 record is the family's
  second-best per-contract read.
- **Oil as a policy: against.** Combined band −2.9¢/contract, −$1.05 total;
  the amendment dilutes the go-live record's quality (oil @0.10 low95 −6.4¢ →
  @0.05 −8.7¢, total down) in exchange for volume.
- **Brent alone: NOT ENOUGH DATA.** The only variant not contradicted. The
  honest trigger to revisit is Brent's band sample roughly doubling at the
  same point estimate, or a forward gate-v2 Brent record (below) — not this
  window set.
- Revisit condition, stated in advance: a future read where the oil [5,10)
  band's low95 clears 0 on forward data. Until then the 10-point net bar is
  doing exactly the job the fee amendment built it for.

## If Kevin overrules: the amendment shape that keeps the record interpretable

The go-live bar (PR #424) counts settled gated forward trades — currently 39,
all gate-v1 (net 0.10, all series). Any lower oil bar must be segmented, or
the count becomes meaningless:

1. **Version the gate.** `gate-v1` = net 0.10 all series (everything frozen
   before the amendment). A `gate-v2` would set the bar per series (oil 0.05,
   gas 0.10) and applies ONLY to windows frozen at/after the amendment
   timestamp, frozen in the spec — the record is a read-time reconstruction,
   so the bar must become a function of (series, frozen_at) with v1 windows
   forever evaluated at 0.10. Never re-bar history.
2. **Segment the count.** The 300-trade go-live bar keeps counting gate-v1
   trades only (today's 39 stand). Gate-v2 oil trades accrue as their own
   forward record with their own count and their own ready test (n ≥ 300 and
   low95 > 0 on the v2 record), reported beside v1, never merged into it.
3. **Persist the version.** Stamp `gate_version` on each fifteen_rule_decisions
   row and each reconstructed trade, so the two records stay separable in the
   data, not just in the code.
4. **Raw control unchanged.** The gross reconstruction stays as the control
   for both versions.
