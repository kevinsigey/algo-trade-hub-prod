# Muse's first round checked, and a self-improving loop for the 15-minute models — Nov 11, 2026 (Claude)

## Part 1: Muse's work since the handover

| PR | Item | Works live? | Process |
|---|---|---|---|
| #472 | Depth on the minute tape | Yes. 4,869 of 4,978 rows since the merge carry ask sizes. | Merged by Muse, as handed over. |
| #477 | A1 order attribution | Yes. All 15 machine orders since the deploy carry a reason; Trades and Orders shows "Tested ideas +$177 (31 closed, 20 won) / Discretionary −$1,768 (33, 3 won)". | **Not reviewed by CodeRabbit.** |
| #478, #479 | A2 verdicts under the current bar | Not seen live (admin sign-in had lapsed). Code read: re-judges each stored run, stamps the bar on new runs. | **Not reviewed by CodeRabbit.** #478 merged only its test file, so main carried a test for code that did not exist for two minutes; #479 carried the code. |

Two process problems, both against the handover's rules:
1. **CodeRabbit never reviewed any of the three.** It was not rate limited: on #477 the review was asked for after
   the merge ("Review failed: the pull request is closed"), and on #479 it shows "Trigger review" unticked. The
   rule is: request it, wait, and self-merge only if it is actually rate limited.
2. **The ship step merged the git index instead of the working tree** (#478). Muse caught and fixed it, and said
   so plainly. Add one check before merge: `gh pr view N --json files` must list the files the change needs.

Two findings on the substance of A1:
- **The gate records; it does not constrain.** All 15 orders since the deploy chose `reason`, none an idea id.
  Most reasons refer to Muse's own plan ("T9 propagation — IREN industry-loser short, LEANS, modal check fails
  in file; Kevin approved 2026-11-11"). That is honest, and the Portfolio split will show it, but the order API
  is still a way to trade untested ideas on both books. Whether that is fine is Kevin's call.
- Wash-trade rejections continue (4 more since the deploy). Alpaca rejects a sell when the account holds a
  resting opposite order in the same symbol; the API should cancel or net the resting order first.

Verified here: the full Python suite on main (result at the end of this doc).

## Part 2: are the 15-minute models deteriorating?

Partly. By day (earned weight = how much of the model to mix with the market price; 0 = nothing to add):

| Day | Natural gas earned weight | Natural gas gated trades |
|---|---|---|
| Nov 4 | 1.23 | — (before the forward record) |
| Nov 5 | 0.05 | — |
| Nov 6 | 0.44 | 4 at +11.8¢ |
| Nov 8 | 0.20 | 7 at +12.1¢ |
| Nov 9 | 1.29 | 19 at +31.1¢ |
| Nov 10 | 0.05 | 15 at +11.1¢ |
| Nov 11 | 0.13 | 6 at −21.1¢ |

Gas's information comes and goes by day; it is not a steady decline. Two of its seven days carried most of it.
The other five series never had any (WTI's weight is negative on four of seven days; gold, copper and silver have
lost money on their gated trades since they started on Nov 9: 42 at −7.7¢, 66 at −0.9¢, 14 at +5.1¢).

What it means: a fixed rule that trades whenever the model disagrees with the price will trade straight through
the days when the model knows nothing. That is what Nov 11 looks like.

## Part 3: a loop that improves itself without fooling itself

The calibration study (research/fifteen_calibration) already showed the trap: refitting the model to a few
hundred windows makes it worse, because the fit's noise is larger than the bias it corrects. So the loop must
learn **one number per series, slowly, from past days only**, and every change must be judged on days it has
not seen.

**Step 1: trade the blend, not the raw model.** Each day, before the first window, compute each series' earned
weight `w` from all of its previous days (contested windows only, 10–90% market price), clamp it to 0–1, and
gate on `p = market + w × (model − market)` instead of the raw model. When the model stops knowing anything,
`w` falls toward 0, the blend sits on the price, and the 10-point gate stops firing on its own.

Replay on the forward record (Nov 7–11, halt windows excluded, weights from earlier days only; the raw policy
reproduces the live record exactly):

| Series | Raw rule (live) | Blend, weight from all earlier days |
|---|---|---|
| Natural gas | 51 trades, +14.9¢, low95 +2.6¢, +$7.62 | 23 trades, **+23.8¢, low95 +6.0¢**, +$5.47 |
| WTI | 23, −4.7¢, −$1.08 | 0 trades |
| Brent | 23, +3.8¢, +$0.88 | 0 trades |
| Gold | 42, −7.7¢, −$3.23 | 0 trades |
| Silver | 14, +5.1¢, +$0.71 | 0 trades |
| Copper | 66, −0.9¢, −$0.62 | 0 trades |
| **All six** | **219 trades, +$4.28** | **23 trades, +$5.47** |

A three-day weight instead of all days: gas 18 trades at +21.6¢, low95 +0.6¢. Use all days.

Honesty caveat: no weight saw its own day, but I chose this policy after seeing this week's data. It earns a
preregistered shadow record, not a switch.

**Step 2: run it as a shadow with automatic promotion**, the same machinery as the oil minute-1 shadow
(`tradehub/fifteen_shadow.py`): stamp rows `gate_version = 'v2-blend-shadow'`, score fresh windows only, and
promote automatically when, on fresh data, it has 100 or more trades, a low95 above 0, and a policy-paired delta
against the live rule whose low95 is above 0. Reversal is one command.

**Step 3: switch a series off by itself.** If a series' 10-day earned weight is below 0.1, the live rule takes no
trades on it and the page says why. It comes back when the weight recovers. This is the "stop when it stops
working" half of self-improvement, and it needs no new model.

**Step 4: let challengers compete, one at a time.** Each new idea (minute-1 entry, 1-minute volatility, the
no-long-shots filter) is a frozen challenger scored on fresh windows against the current champion with the same
promotion rule. At most one challenger per series at a time, so the multiple-testing problem stays visible.

**What stays fixed:** the model formula, the fee math, the 10-point bar, the halt exclusion. The loop only learns
how much to trust the model, and when to stop.

**Before any of this trades real money:** the depth now recorded by #472 says the bottom tenth of minutes has
about 1 contract at the gas ask (median 147). The fill check comes first.

---
Full Python suite on main at d4f93e6 (after #479): 3,430 passed, 12 skipped, exit 0. This matches Muse's report.
The frontend suite was not rerun here.
