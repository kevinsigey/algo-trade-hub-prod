---
title: "15-minute rule, oil entry timing: minute-1 vs the freeze"
type: research
domain: energy
status: complete
settlement_source: Kalshi (journal settlements)
tags: [fifteen-rule, oil, entry-timing, counterfactual, paired-test]
summary: "Pure entry timing at the live 0.10 bar is NOT PROVEN (paired deltas +1-2c/window, intervals include 0). A bundled variant the data itself suggests -- oil only, minute-1 entry, 0.05 bar -- posts 44 trades @ +29.5c with a paired policy delta of +5.5c/window (low95 +2.0), but it is scored on substantially the data that suggested it: a strong hypothesis for a preregistered shadow record, not a gate amendment."
---

# Entry timing for the 15-minute rule's oil series

**Question (Kevin, 2026-11-09):** for WTI and Brent, at the live 0.10 net-edge bar, how does the hypothetical record vary by entry minute, and does entering earlier than the ~minute-5 freeze beat the freeze entry on the same windows? Secondary: does early entry rescue the [5,10) band the +5-bar study rejected at the freeze, and is any timing effect oil-specific?

**Verdict: timing alone is NOT PROVEN. A bundled variant — oil only, minute-1 entry, 0.05 bar — is a strong hypothesis, and the recommendation is to preregister it as a shadow record, not to amend the gate.** The live rule, gate and records are unchanged by this study.

Method: snapshot of production tables pulled 2026-11-09 ~18:47 UTC (`fifteen_window_offsets`, `fifteen_rule_decisions`, `journal_forecasts`, `journal_settlements`), replayed through the production rule's own functions. Cohort: 288 settled windows frozen at/after PREREG_AT 2026-11-07T00:00Z with halt windows excluded (96 per series), timestamps compared as parsed datetimes throughout. Analysis plan and verdict bar were stated in `analyze.py` before the results were read.

## Validation (the machinery reproduces the live record)

- The forecasts replay at the 0.10 bar reproduces the decisions table's forward buy record **exactly**: 41 gated trades @ **+19.6¢**, win 65.9%, low95 +7.4¢, total +$8.04 (WTI 7 @ +16.4¢, Brent 11 @ +11.6¢, Natural gas 23 @ +24.4¢).
- The offsets table's minute-5 read is the tape recorder's nearest-minute read, **not** the journal freeze itself: it prices 35 of those trades @ +22.3¢ (7 decision buys are unpriced or read differently at recorder-minute-5; 1 recorder-only pass; best edges agree within rounding on 255 of 275 comparable windows, worst diff 0.31). Timing conclusions therefore rest on *within-table* paired comparisons — and that is the right basis anyway: an early-entry rule would consume exactly this live read (`fifteen_live`, the read the every-minute tape recorder captures), not the journal's freeze.
- Outcomes in the offsets table agree with journal settlements on every row.

## Implementability: the early minutes are real

`prob_source` decides what was knowable live. Tick rows are captured in real time by the every-minute tape recorder, with real quotes; tape rows are recomputed later from candles and **never carry quotes — they are never priced, anywhere in the table**. In this cohort, minutes 1–14 are tick-captured for **100% of oil windows** (natural gas 90–95%). The minute-1 probability and quote were knowable live. Minutes 0 and 15 have zero oil tick rows — structurally unusable, excluded from candidacy. (A tick is the recorder's tick nearest the whole minute, ±0.5 min granularity.)

## The record by minute (unpaired, live 0.10 bar, recorder reads)

| Minute | Oil trades | Oil net/trade | Oil low95 | Gas trades | Gas net/trade |
|---|---|---|---|---|---|
| 1 | 21 | **+28.7¢** | +12.5 | 11 | +15.2¢ |
| 2 | 20 | +21.3¢ | +3.1 | 15 | +31.9¢ |
| 3 | 14 | +7.4¢ | −15.3 | 19 | +20.0¢ |
| 4 | 20 | +17.2¢ | −0.4 | 18 | +23.1¢ |
| 5 (freeze read) | 17 | +15.5¢ | −1.9 | 18 | +28.8¢ |
| 6 | 27 | +16.7¢ | +2.0 | 26 | +27.7¢ |
| 7 | 21 | +17.8¢ | −0.5 | 22 | +22.3¢ |
| 9–14 | 23–37/min | −2.4¢ to +12.6¢ | all < 0 | — | decays |

Oil's unpaired curve peaks at minute 1 and decays late (win rates 0.28–0.41 in minutes 9–14 despite the largest edges on offer — the familiar pattern). Gas shows **no early peak**: its freeze-minute read is as good as any minute. Whatever this is, it is oil-shaped, not family-wide. But unpaired curves mix trade sets — different minutes take different trades — so they cannot carry the verdict. The paired test can.

## The paired test (same windows, per-window policy PnL, minute k vs minute 5)

| Minute 1 vs 5 | Windows | Trades k / 5 | Paired Δ per window | Δ low95 |
|---|---|---|---|---|
| WTI | 92 | 12 / 7 | +2.2¢ | −1.6 |
| Brent | 94 | 8 / 10 | +1.0¢ | −2.8 |
| Oil | 186 | 20 / 17 | +1.6¢ | −1.1 |

Minutes 2–4 are inconsistent (Brent −0.1¢ at minute 2; WTI −2.1¢ at minute 3). And on the windows where the gate passed at **both** minutes — the identical trade set — the freeze read did *better* (oil minute 1: +16.3¢ vs +31.6¢ at minute 5, n=4). The small positive policy delta comes from trades minute 1 takes that minute 5 doesn't, not from better execution of shared trades.

**Against the pre-stated bar** (same direction in both series, material magnitude, ideally the interval excluding 0): minute 1 is the same direction in both series, but +1–2¢ per window with every interval including 0 is neither material nor separated. **Pure timing at the live bar: NOT PROVEN.** An exploratory session split is the one bright slice — oil closed-session minute-1 Δ +7.8¢/window (low95 +0.7, 37 windows) against open-session Δ 0.0 (149 windows); WTI's closed slice is too thin to report (17 windows). A subgroup of a null overall read is a hypothesis, not a result.

## The band at minute 1: the [5,10) zone is alive for exactly one minute

| [0.05, 0.10) band | n | Net/trade | Win | low95 |
|---|---|---|---|---|
| Oil @ minute 1 | 23 | **+30.3¢** | 78% | **+14.0** |
| — WTI @ minute 1 | 14 | +36.4¢ | 86% | +18.8 |
| — Brent @ minute 1 | 9 | +21.0¢ | 67% | −11.2 (n below the reportable floor) |
| Oil @ minute 5 (freeze) | 36 | −3.1¢ | 39% | −15.4 |
| Oil @ minutes 2–4 | 27–32 | +6.6¢ to +9.1¢ | — | all cross 0 |
| Gas @ minute 1 | 13 | +5.2¢ | 54% | −23.3 |

This replicates the +5 study's closing observation on the forward segment (it found +26.7¢ on a wider snapshot): the band the freeze rejects is worth ~+30¢/trade at minute 1 and dead by minute 5. It is a minute-1 phenomenon, and it is oil's — gas's band shows no minute-1 spike.

## The bundled variant the data suggests — and why it is not yet a verdict

Oil only, enter at minute 1, bar 0.05 (the ≥0.10 trades and the band are disjoint edge populations at that minute, so the variant's record is their sum):

- **Record: 44 trades @ +29.5¢, win 79.5%, low95 +18.1¢, total +$13.00** — against the live rule's oil record on the same segment, 18 trades @ +13.5¢.
- **Policy-paired against the live rule's actual decisions** on all 192 oil windows priced at minute 1: **Δ +5.5¢ per window, low95 +2.0, total +$10.57.**
- Decomposition: pure timing at 0.10 contributes ≈ +1.6¢/window (not significant); the rest is the bar×minute interaction — the 5–10 band is alive at minute 1 and dead at the freeze. Neither change alone produces it (the +5 study killed the bar change at the freeze; this study cannot separate timing alone from zero).
- The same variant on gas: 24 trades @ +9.8¢, low95 −10.4. No case.

**The honesty caveat that governs the recommendation:** the Nov 7–9 forward segment both *suggested* this variant (via the +5 study's offsets sensitivity) and *scores* it here. These are not independent samples. +29.5¢ with low95 +18.1 on the suggesting data is what a real effect looks like — and also what a fitted one looks like. The variant has earned a preregistered forward test, not a gate change.

## Recommendation

1. **Do not amend the live gate.** The commissioned question — pure timing at the live bar — is NOT PROVEN, and the variant bundles a bar change this segment cannot independently confirm.
2. **Preregister the variant as a shadow record** (spec frozen before the next window freezes): oil series only (WTI, Brent); decision read = the live tape read at minute 1 (tick nearest elapsed 1.0, the `fifteen_min_ticks`/`fifteen_live` read); bar 0.05 net of the taker fee; production side/cost construction; halt exclusion unchanged; hold to settlement. The offsets table already accrues every input, so the shadow costs nothing and touches nothing. Score it two ways on the fresh segment only: its own record, and the policy-paired delta against the live rule's decisions.
3. **Gate-version segmentation if it is ever adopted:** the live rule stays gate v1 (freeze read, 0.10, all series) and the 300-trade go-live bar keeps counting **v1 trades only** (41 today). The variant, as gate v2-oil, accrues its own forward count with its own ready test (the same 300-trade / low95 > 0 shape, if Kevin wants symmetry — his call). v2 trades never enter the v1 record.
4. **Instrumentation a live v2 would need:** one thing — a per-minute decision pass. The runner is a 5-minute cron that freezes at +5; the tape recorder proves the model's live read and quotes are available every minute. A v2 needs an evaluation at minute 1 writing its own decision rows (a `gate_version` stamp keeps the records separable). No new data plumbing: probs, quotes, settlements all exist.
5. **What settles it:** the shadow record on post-preregistration windows only. A fair read is ~150 shadow trades (at the observed ~44 trades per 288 oil windows, roughly 3–4 weeks of accrual), with the paired delta recomputed on the fresh segment and the closed-session slice re-checked on fresh data. If the fresh paired delta's low95 excludes 0 in the variant's favor, the amendment question comes back to Kevin with independent evidence behind it; if it fades toward the freeze-minute band (−3.1¢), the variant joins the +5 bar in the rejected pile and the minute-1 band spike is recorded as a two-day regime artifact.
