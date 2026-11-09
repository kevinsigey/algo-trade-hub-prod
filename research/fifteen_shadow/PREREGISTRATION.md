---
title: "15-minute rule, oil minute-1 x 0.05 bar: preregistered shadow record with automatic promotion"
type: preregistration
domain: oil
status: frozen
settlement_source: Kalshi (journal settlements)
tags: [fifteen-rule, oil, shadow-record, preregistration, entry-timing, edge-gate]
summary: "Frozen 2026-11-09T19:00:00Z segment open. Variant: WTI+Brent only, minute-1 live tick read, 0.05 net-of-fee bar, gate_version 'v2-oil-shadow'. Promotes to the live oil gate automatically iff, on fresh windows only: n >= 150 settled shadow trades, shadow low95 > 0, and the policy-paired delta vs the live rule's decisions has low95 > 0. Full spec: docs/superpowers/specs/2026-11-09-fifteen-shadow-oil-minute1-prereg.md."
---

# Preregistration — oil minute-1 × 0.05-bar shadow variant

**Frozen:** 2026-11-09 (Kevin's authorization the same day). **Evaluation
segment opens:** `2026-11-09T19:00:00+00:00` — windows opened before that
instant, including the whole Nov 7–9 discovery segment, never count.

**The variant.** WTI and Brent only. Decision read = the live tape read at
minute 1 of the window (`fifteen_min_ticks` tick nearest elapsed 1.0;
`prob_source` must be tick — tape-recomputed rows never count). Bar = net
edge ≥ 0.05 by the live gate's math (`net_edges`: fee-netted at
`0.07·cost·(1−cost)`, YES at `yes_ask`, NO at `1 − yes_bid`). One
hypothetical contract, hold to settlement, halt windows excluded identically
to the live rule. Every row stamped `gate_version = 'v2-oil-shadow'`. The
pass also accrues the full grid — offsets 1–5 × bars {0.05, 0.10} — as the
entry-time × edge-level dataset; only the (minute 1, 0.05) cell is the
variant and only it can promote.

**Segmentation.** Gate v1 (freeze read, 0.10, all series) is untouched; the
300-trade go-live bar keeps counting gate-v1 trades only (41 at freezing).
Shadow rows never enter the v1 record.

**Evaluation.** Daily, fresh segment only: the variant's settled record
(n, net/contract, low95), the policy-paired delta vs the live rule's actual
decisions per window (skip = 0) with its low95, and the closed-session slice
of that delta (reported, never an input).

**PROMOTION CRITERION (all required): n ≥ 150 fresh shadow trades; shadow
low95 > 0; paired-delta low95 > 0.**

**On promotion:** an audit row in `fifteen_promotions` with the full
evidence pack; from the flip timestamp the live oil gate is the variant
(decisions stamped `gate_version = 'v2-oil'`; gas stays v1; the v1 segment
closes preserved); the fifteen-rule endpoint's `shadow.promotion` flag
carries state + evidence for a daily external check. **Reversal is one
action** (`python -m tradehub.fifteen_shadow revert`) and restores v1 for
oil. If the criterion is never met, nothing flips.

**Horizon:** ~150 trades at the discovery segment's rate ≈ 3–4 weeks.
