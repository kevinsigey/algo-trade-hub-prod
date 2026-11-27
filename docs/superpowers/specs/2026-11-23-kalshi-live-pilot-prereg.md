# Kalshi live micro-pilot: oil & gas raw rule, 1 contract, real money ($10 start)

Preregistration for the live pilot specced in issue #590 (Kevin's ruling,
2026-11-23). PREREG_AT = the deploy time of the merged PR that ships the
lane. The fixed terms below are committed verbatim from the issue.

## Goal

Kevin's ruling, 2026-11-23: put the 15-minute oil & gas rule on his **live**
Kalshi account with real money, starting at about $10, at one contract per
trade. The pilot answers one question the paper record can't: **do the paper
fills actually happen?** Every paper trade assumes a fill at the frozen ask.
The prod-book observation lane already says otherwise for gas: 8 of 25
decisions would have filled (32%), at −3¢ a contract on the 8 settled. Fill
rate and slippage are the primary output of this pilot; P&L comes second.

Evidence behind the ruling (hub, Nov 23): oil & gas forward since the Nov 7
prereg, raw rule: 414 trades, +5¢ net a contract, low95 +0.7¢. The fee-netting
gate never changes a trade, only deletes windows (rescore
`kalshi_15min_rescore_2026-11-23.md`), so the live lane trades the **raw**
rule. Deflated Sharpe is 0.65 after ~20 variants: "probably something", not
proven.

## Fixed terms

**Rule.** The original oil & gas rule in `oil_fifteen_rule.RULE`: at the
freeze, buy a side when the model's chance beats its price by 10 points or
more (the gross bar, **no fee-netting gate**). Hold to settlement. No trades
4:45–6:30 PM ET.

**Series, locked.** `KXWTI15M`, `KXBRENT15M`, `KXNATGAS15M`. Nothing is
added, dropped or reweighted during the pilot. Metals, the blend, volregime,
the v4 family and the gated basis stay off the live lane.

**Sizing.**
- **Balance under $45:** 1 contract per decision (about 4–5% of a $10
  account; Kevin accepts this as the minimum tradable unit).
- **Balance $45 or more, and the 150-trade gate below has passed:**
  `contracts = max(1, floor(0.02 × balance / live_ask))`. Until that gate
  passes, stay at 1 contract whatever the balance.
- **Window cap:** the total cost of live positions open in one 15-minute
  window is at most 3 contracts while under $45, and at most 5% of balance
  after that.

**Daily stop.** No new orders for the rest of the ET session once the
session's settled live loss reaches **$2.00**.

**Floor halt.** If the balance falls below **$5.00**, the live lane halts
until Kevin re-enables it.

**Execution.** Reuse the demo lane's cross exactly:
- re-read the live book;
- recompute the edge at the live ask against the raw 10-point bar;
- send immediate-or-cancel at that ask;
- skip, with its reason, on an unreadable book, an unmeasured probability, an
  edge that no longer clears, or a live ask more than **3¢** above the frozen
  quote.

Nothing ever rests on the book. Buys only: no sells and no early exits.

**Gates (automatic, evaluated each pass, results posted to the alert feed).**
1. **Execution check at 50 live fills.** If mean live fill price minus frozen
   paper price is above **2¢**, halt the live lane and alert Kevin. Report
   the fill rate alongside.
2. **Edge check at 150 settled live trades.** If live net per contract
   (fee-netted, day-clustered) has low95 below **0**, halt. If it passes,
   stage-3 sizing unlocks at $45.

Halts are never lifted automatically.

**Natgas.** No change during the pilot. It is reviewed at the 150-trade
check; no ad hoc removal.

## Hard ceilings (in code)

Per order 5 contracts, per day 100 contracts, per day $25 notional.
Environment variables may lower these, never raise them.

## Kevin does (not Muse)

- Fund the live account (~$10).
- Mint the live API key and place it on the VPS as `KALSHI_LIVE_KEY_ID` and
  `KALSHI_LIVE_PRIVATE_KEY_PATH`. It never goes in the repo, the chat or the
  logs.
- Set `KALSHI_LIVE_ENABLED=1` himself after reviewing the merged PR. The
  lane ships with it unset.

## Out of scope

Metals; any gate or candidate lane on live money; changes to the paper rule
or its scoring; the Alpaca books; sizing above 5% of balance.

## Amendment — execution only (2026-11-25, issue #619)

Kevin's amendment, approved 2026-11-25 after the lane's first two days.
Effective at the deploy time of the merged PR that ships it. It changes
how sends happen, never what gets decided: the rule, the series, the
sizing, the 3¢ slippage cap, the edge bar, the $2 daily stop, the $5
floor halt and both gates are all unchanged. Natgas stays paused.

**Evidence.** Nov 24–25, oil only: 26 decisions → 15 never sent
(edge_below_bar / slippage_cap at the cross — by design, not a defect),
11 sent → 7 filled, 4 unfilled. All 4 unfilleds were Nov 25, all IOC at
the live ask, all with latency_s 46–55s and the live ask below the
frozen quote: the ~55s freeze→send gap of the 5-minute runner cadence
loses the race on a moving tape. Day 1 sent 6/6 filled.

**The three changes.**

1. **Latency.** The runner loops inside the minute (cron every minute,
   passes every ~8s), so a frozen decision is sent within seconds of
   landing — target ~10s of frozen_at. latency_s keeps being recorded
   on every row.
2. **One bounded re-cross.** If an IOC returns unfilled, the lane
   re-reads the book once and re-sends once — only if the edge still
   clears the bar at the fresh ask and the fresh ask is at most the
   frozen quote + 3¢ (the existing cap; it does not move). Same window
   only, never a third attempt, and the re-send carries the same
   decision's already-reserved contracts, never a second exposure.
3. **+1¢ aggression inside the cap.** The limit is the live ask + 1¢,
   still bounded by frozen + 3¢; if ask + 1¢ would breach the cap, the
   limit is the cap. Kalshi matches at the resting price, so when the
   book holds this costs nothing; it only rescues 1¢ uptick races.

**Ledger marks.** `kalshi_live_orders.attempts` counts a row's sends
(1 = first send, 2 = the re-cross went out) and `filled_attempt` says
which send filled. Rows sent before this amendment carry attempts 0,
so the 150-trade edge check can split the ledger pre/post amendment on
that column, and first-send fills split from re-cross fills on
filled_attempt.

**Acceptance.** The first full day after deploy reports: sent→fill
rate and mean latency_s against the ~55s / day-1 baseline, the
re-cross count, and how many re-crosses filled.
