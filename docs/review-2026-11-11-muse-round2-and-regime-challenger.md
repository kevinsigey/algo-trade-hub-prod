# Muse round 2 checked, and a regime challenger for the 15-minute blend: Nov 11, 2026 (Claude)

Covers #482 (blend shadow), #483 (LEAPS shadow), #484 (A4 guidance guards, open), #485 (LEAPS index, open),
read on `origin/main` at e42d91d plus the two open branches. Database checks were run against production.

## Part 1: what Muse shipped

| PR | Verdict | Findings |
|---|---|---|
| #482 blend shadow | **Matches the preregistration** | Weight, gate, fresh-only scoring, paired delta and the reversal hold all match spec. CodeRabbit reviewed it. No weight rows exist yet: the start time (PREREG_AT) is Nov 12 00:00 UTC, so recheck the weights table after that. Expect about 3 weeks to 100 trades, since only gas should trade (about 4–5 a day). Minor: the day's weight is frozen on the first pass, so last night's windows that haven't settled yet are left out. The weight row records how many contested windows it used, so that's acceptable. |
| #483 LEAPS shadow | **Two gate faults; fix before the first pair opens** (0 pairs today) | See below. |
| #484 A4 guards | TMUS fixed; **MRK still mis-anchored**; not reviewed by CodeRabbit | See below. |
| #485 LEAPS unique index | **Fine to merge** | The index is live in the database (checked) and recorded as row 82. No rows exist, so applying it was risk-free. |

### #483: the LEAPS gate can't judge what it was built to judge

1. **The delivery bar can't fire.** `delta_delivered` divides the LEAPS return per premium dollar by the share
   line's return per share dollar. A 0.80-delta deep-in-the-money call costs about a third of its delta-notional
   (spot 100, strike 75: ask ≈ 27 against 80 of notional). So a LEAPS that tracks the shares perfectly reads about
   3.0, and the "under 80% kills it" bar only fires after a near-total failure. Measure what the bar means:
   `leaps_pnl / share_pnl` on the same delta-notional, pooled over the cohort (sum over sum). A mean of
   per-pair ratios blows up when a stock barely moves.
   Muse followed the claim's own wording ("per dollar of premium-side capital"), so this is **Kevin's call**:
   either the definition changes or the 80% bar does. They can't both stay.
2. **The carry bar fires on day one.** Drag is annualised over days held, with a 1-day floor, so the entry spread
   alone gets multiplied by about 365 on the first night. The cohort is judged the moment the 4th pair opens, so
   that pair's first mark can kill the trial. The verdict is also recomputed every night and never stored, so it
   can flip from killed to pass as the drag settles.
   Fix: judge the cohort only when every pair in it has 90 or more days of marks or is closed, then store the
   first verdict.

### #484: TMUS is fixed, MRK is not

- The reported-result screen and the 0.45× floor are sound. I found no false positives on forward-looking wording.
- MRK: the filing check is right that 2.66–2.76 is a real guide. But it includes $2.43 a share of one-time charges,
  and the peer multiple it is valued against is built on earnings without one-offs. The band now values MRK at about
  half of what the old guide implied, and a note under the table doesn't stop that. The consensus field (2.78)
  agrees, so the corroboration escape doesn't catch it either.
- Fix: when consecutive full-year guides step by more than 35%, mark the sheet "basis break, not banded" until
  Kevin confirms. Don't anchor on the new figure.
- The PR needs a CodeRabbit review before merge. It was rate limited.

## Part 2: the regime question, and the one challenger worth running

**What a regime actually changes here.** The model doesn't use price level or direction. Its input is the move
since the window opened, scaled by recent 1-minute volatility. So "oil coming down" doesn't change the formula.
What can change with a regime is **how much the model knows that the price doesn't**, and that's what the blend's
weight measures. The open question is whether one weight per series is too coarse.

**Volatility is where it splits.** Same data as before: contested windows, earned weight by each series' own
median 1-minute volatility. In-sample, so the split uses look-ahead.

| Series | Low-volatility half | High-volatility half |
|---|---|---|
| Natural gas | 0.26 (n 250) | **1.08** (n 250) |
| WTI | 0.22 (257) | −0.52 (257) |
| Brent | 0.06 (250) | 0.20 (250) |
| Gold | −0.38 (81) | 0.26 (80) |
| Silver | 0.90 (82) | −0.99 (81) |
| Copper | 0.28 (70) | 0.04 (69) |

- Gas earns its weight almost entirely on fast-moving windows. That fits the mechanism: Kalshi's quote lags the
  move, and the lag matters more when the move is large. Brent leans the same way, more weakly.
- WTI and silver point the opposite way, which reads as noise. A clamped weight with a minimum sample would
  keep them near 0.

**Trend was tested and is not worth a challenger.** I checked the market's error after a 2-hour move, sorted into
up, flat and down by more than half a standard deviation:
- After up moves: gas −4.0¢ (n 198), WTI −4.4¢ (n 121).
- After down moves: −1.9¢ to +1.5¢.
- The standard errors are about 3.5–4.5¢, so none of this is significant, and the series don't agree with each
  other. There's no momentum or reversal the market misses.

**The challenger, to preregister: `v3-volregime-shadow`**
- **The change.** It's the same as the blend with one exception: each series gets two daily weights. One is for
  windows whose frozen `sigma_1m` is above that series' trailing 10-day median, taken from earlier days only. The
  other is for windows below that median.
- **How each weight is set.** Each weight is computed only from that regime's contested windows on earlier days and
  clamped to 0–1. A regime with fewer than 30 contested windows gets a weight of 0.
- **What it's paired against.** The `v2-blend-shadow` decisions for the same window, not the raw rule. It has to
  beat the blend, not just the thing the blend already beats.
- **Promotion.** At least 100 fresh trades, low95 above 0, and the paired delta's low95 above 0. It can only take
  the live gate after the blend has been promoted. Before then it stays a record.
- **What stays fixed.** Same freeze, quotes, fee netting, 10-point bar and halt exclusion. It's one challenger,
  following step 4 of the previous review: one at a time per series.

What this gives Kevin: when gas markets go quiet the system trusts the model less, and when they move fast it trusts
it more, learned from past days only. It still won't invent a new edge. A regime the data has never seen starts at
weight 0.

## Part 3: prompt for Muse

> Read `docs/review-2026-11-11-muse-round2-and-regime-challenger.md`. Implement, one PR each, CodeRabbit on
> every PR, migrations only with Kevin's go and recorded in `migrations-applied.md`:
>
> 1. **#485**: merge as is (the index is already live).
> 2. **LEAPS gate (#483 follow-up), before any pair opens.**
>    - Ask Kevin first which to change, the delivery definition or the 80% bar. Default: delivery =
>      `sum(leaps_pnl) / sum(share_pnl)` over the cohort.
>    - Judge the cohort only once every pair has 90 or more days of marks or is closed.
>    - Store the first verdict and never recompute it.
>    - Add tests for a perfect-tracking LEAPS (delivery ≈ 1.0), a day-1 mark (no verdict) and a stored verdict
>      that later marks can't change.
> 3. **#484 amendment.** When consecutive full-year guides step by more than 35%, the sheet is "basis break, not
>    banded" until Kevin confirms; it is not anchored on the new figure. Keep the MRK note. Get a CodeRabbit review
>    before merge.
> 4. **Regime challenger `v3-volregime-shadow`.**
>    - Write the preregistration first, frozen before the first row, with PREREG_AT at least a day after merge.
>    - Rules exactly as in Part 2: two weights per series by trailing 10-day median `sigma_1m`, at least 30
>      contested windows per regime or the weight is 0, paired against `v2-blend-shadow`, the same promotion bar,
>      and promotable only after the blend has been promoted.
>    - Reuse `tradehub/fifteen_blend.py`. The weight function takes a regime filter; don't copy the module.
>    - Use its own decisions, weights and evals tables, or a `variant` column on the blend's tables, whichever is the
>      smaller migration.
>    - Never modify the live rule or the blend's frozen rows.
> 5. **After Nov 12 00:00 UTC**, confirm `fifteen_blend_weights` has six rows for Nov 12 and that
>    `fifteen_blend_decisions` is filling in. Report gas's weight.
>
> Don't build live Kalshi order placement. Don't change a live model in place.
