# Fifteen-minute rule: the oil minute-1 × 0.05-bar variant as a preregistered shadow record (2026-11-09)

Preregisters a **shadow record** for a variant of the 15-minute trade rule
(`tradehub/oil_fifteen_rule.py`, gate v1: freeze read, 0.10 net-of-fee bar, all
series; go-live bar PR #424: 300 settled gated forward trades with low95 > 0,
counted on gate v1 only — **41 at this freezing**). Kevin's direction,
2026-11-09: *"yeah pre register it and track it going forward and once it
performs better than the live model it should automatically be updated and i
can be notified… the end goal is automation."*

The variant comes from two studies on the Nov 7–9 forward segment, both
shipped as research notes:

- `research/fifteen_bar/` (PR #430): at the freeze, the [0.05, 0.10) net-edge
  band **loses** on oil (36 trades @ −2.9¢ combined) — a 0.05 bar at the freeze
  is rejected. WTI's band is decisively negative; Brent alone is not enough data.
- `research/fifteen_timing/` (PR #435): pure entry timing at the 0.10 bar is
  NOT PROVEN (paired minute-1 delta +1.6¢/window, low95 −1.1). But the
  [0.05, 0.10) band at **minute 1** posts 23 trades @ +30.3¢ (low95 +14.0),
  and the bundled variant below posts 44 @ +29.5¢ with a policy-paired delta
  of +5.5¢/window (low95 +2.0) against the live rule's decisions.

**Governing caveat, frozen with the design:** the Nov 7–9 segment both
suggested this variant and scored it. Those are not independent samples. The
variant is therefore tested here on **fresh windows only**; nothing in the
discovery segment counts toward its verdict.

## The variant (frozen)

For the two oil series only — WTI (`KXWTI15M`) and Brent (`KXBRENT15M`).
Natural gas is **not** in the variant (its minute-1 band showed no spike and
its freeze read is as good as any minute; gas stays on gate v1 whatever
happens here):

- **Decision read:** the live tape read at **minute 1** of the window — the
  `fifteen_min_ticks` tick nearest elapsed 1.0, exactly the read the offsets
  track consumes. The row's `prob_source` must be **tick**; a tape-recomputed
  value never counts (tape rows carry no quotes and are never priced anywhere
  in the offsets track — parity is by construction).
- **Bar:** net edge ≥ **0.05**, measured with the live gate's own math
  (`oil_fifteen_rule.net_edges`: edge net of Kalshi's taker fee
  `0.07·cost·(1−cost)`; YES bought at `yes_ask`, NO at `1 − yes_bid`; quotes
  sane iff `0.02 < yes_bid ≤ yes_ask < 0.98`).
- **Conventions:** one hypothetical contract, hold to settlement, PnL by
  `oil_fifteen_rule.pnl`. Halt windows excluded **identically** to the live
  rule (`in_halt` on the window's journal freeze moment, 16:45–18:30 ET).
- **Identity:** every shadow row carries `gate_version = 'v2-oil-shadow'`.

## The record

A new table, `fifteen_shadow_decisions`, mirroring `fifteen_rule_decisions`
plus `offset_min` and `bar`. A decision pass riding the existing
fifteen-minute runner (the same invocation that writes the v1 decisions and
the offsets track; a shadow failure is reported, never allowed to fail the
freeze pass) writes, **for every fresh oil window** — window open at or after
`2026-11-09T19:00:00+00:00` (the first window boundary after this freezing;
no earlier window ever gets a shadow row) — the full grid:

- offsets **1, 2, 3, 4, 5** × bars **{0.05, 0.10}** — 10 decision rows per
  window per series, each a buy or a skip with its reason named
  (`halt` / `no_tick` / `no_quote` / `no_edge`, mirroring the live rule's
  vocabulary; `no_tick` = no live tick read at that offset, the honest name
  for "not knowable live").
- The **variant cell** is (offset 1, bar 0.05). The rest of the grid is the
  dataset: the entry-time × edge-level surface, accrued so a future automated
  system can reason about *when* to enter and *at what bar*, per series —
  including combinations nobody has preregistered yet. Grid cells are
  evidence, not candidates: no grid cell other than the variant cell can
  promote under this preregistration.

## Segmentation (hard)

- Gate v1 is **byte-untouched**: `oil_fifteen_rule.py` is not modified; the
  live gate stays 0.10 at the freeze for all three series; the v1 decisions
  pass keeps its logic (it gains only a `gate_version` stamp, `'v1'` on every
  row it writes, so the records stay separable in the data).
- The 300-trade go-live bar keeps counting **gate-v1 freeze trades only**
  (41 at this freezing). Shadow rows never enter the v1 record, the v1
  stats, or the bar — in code, the v1 read paths never read the shadow table.
- The shadow's evaluation segment is **only** windows opened at or after
  `2026-11-09T19:00:00+00:00`. The Nov 7–9 discovery segment is excluded from
  every shadow verdict by construction (no rows exist for it).

## Evaluation and automatic promotion (Kevin's authorization, 2026-11-09)

A scheduled **daily** evaluation (the first fifteen-minute run pass of each
UTC day) computes, on the fresh segment only:

- the variant cell's settled record: trades `n`, net per contract, low95
  (the record's standing convention: mean − 1.96·sd/√n);
- the **policy-paired delta** against the live rule's actual decisions: per
  fresh oil window, (shadow policy PnL − live policy PnL), a skip scoring 0,
  over windows where both records are settled — its mean and low95;
- the **closed-session slice** re-check: the same paired delta restricted to
  futures-closed windows (reported, never a promotion input — the discovery
  segment's bright slice must re-prove itself on fresh data to be believed).

Each evaluation is persisted (`fifteen_shadow_evals`) whether or not it
promotes — the silent milestone trail. No notifications are wired in this
build beyond the promotion flag below.

**PROMOTION CRITERION (all required): n ≥ 150 fresh shadow trades; shadow
low95 > 0; paired-delta low95 > 0.**

**When the criterion is met**, the evaluation pass itself promotes, in the
same run:

1. An audit row is written to `fifteen_promotions` (kind `promotion`,
   from `v1` to `v2-oil`, with the full evidence pack: n, net per contract,
   both low95s, the paired delta, the closed-session slice, the flip
   timestamp).
2. From the flip timestamp, the **live gate for WTI and Brent becomes the
   variant**: the decisions pass writes oil decisions from the minute-1 tick
   read at the 0.05 bar, stamped `gate_version = 'v2-oil'`, for windows
   opened at or after the flip. Gas decisions stay v1. Windows before the
   flip keep their v1 rows — the v1 segment is closed and preserved, never
   rewritten. The go-live bar's v1 count freezes wherever it stands; the
   v2-oil live record accrues from its own decision rows.
3. A machine-readable **promotion flag** rides the fifteen-rule endpoint
   payload (`shadow.promotion`: state, criterion as frozen here, met,
   promoted_at, evidence) where a daily external check can read it.

**Reversibility (one action):** the flip is a state row, not a code change.
Inserting one reversal row — `python -m tradehub.fifteen_shadow revert` —
restores gate v1 for oil from that moment (rows already stamped `v2-oil`
stay as written; the segments remain separable by their stamps forever).

**If the criterion is never met, nothing ever flips.** Silence is the
default state; there is no expiry and no partial credit — a shadow that
fades toward the freeze-minute band (−3.1¢ on the discovery segment) joins
the +5-bar idea in the rejected pile on the strength of its own fresh record.

## Expected horizon

The discovery segment produced ~44 variant trades per 288 oil windows
(≈ 15% of windows). At the observed accrual rate the 150-trade criterion
needs roughly **3–4 weeks** of fresh windows. The criterion is a count of
settled trades, so the calendar read is approximate; the evaluation reports
the actual n daily.

## What this build does not do

No orders, no book interaction, no change to any forecast. The shadow is a
paper record beside a paper record. The live rule's text, gate and history
are untouched; the endpoint payload gains one additive `shadow` block and
nothing else changes shape.
