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
