# Model deep dive — Nov 10, 2026 (Claude, for Kevin and Muse)

Follows `review-2026-11-09-models.md`. That one read the scoreboard; this one reads the model code and the
forecast rows behind it (`journal_forecasts` joined to `journal_settlements`, pulled 22:30 UTC Nov 10).

Two measures used below, both on **contested rows only** (Kalshi price between 10% and 90%):
- **Earned weight**: the share of the model you would mix with the Kalshi price to get the best forecast
  (slope of `outcome − market` on `model − market`). 0 = the model adds nothing the price lacks. 1 = trust the model.
- **Information**: the correlation behind that slope. It says whether the weight is distinguishable from 0.

Limits: the 15-minute and hourly data cover 5 to 8 days. Forecasts on the same day move together, so every
significance figure here is optimistic. Nothing below was changed in production.

## 1. Why natural gas 15-minute works, and what carries over

**It is not the model.** All six 15-minute models run the same formula (`engines/fifteen_min.py`: the move so
far, divided by recent 1-minute volatility). Their accuracy is nearly identical. What differs is the opponent.

| Series | Windows | Model Brier | Kalshi Brier | Information | Model–price correlation | Avg spread | Gated trades (net a contract) |
|---|---|---|---|---|---|---|---|
| Natural gas | 440 | 0.190 | **0.194** | **+0.18** | 0.86 | 2.9¢ | 55 at +19.1¢ |
| Brent | 440 | 0.196 | 0.193 | +0.06 | 0.94 | 2.5¢ | 21 at +4.9¢ |
| WTI | 440 | 0.193 | 0.187 | −0.02 | 0.95 | 1.1¢ | 21 at −2.0¢ |
| Silver | 94 | 0.178 | 0.170 | −0.09 | 0.97 | 1.0¢ | — |
| Gold | 94 | 0.191 | 0.179 | −0.02 | 0.93 | 0.9¢ | — |
| Copper | 89 | 0.177 | 0.159 | +0.08 | 0.79 | 3.9¢ | — |

- The natural gas **market** is the worst-priced of the six, and its price follows the underlying move least
  closely (0.86). The model's read of that move is information the price has not absorbed. Earned weight 0.88;
  information positive on all 7 days.
- WTI's price already contains the move (0.95, 1¢ spread on 383 of 440 windows). The same model earns nothing.
- So "apply what we did on gas" means **pick markets the way gas was picked by luck**, not copy a model.

What carries over, as hypotheses for shadow records (small samples, not rule changes):
1. **Rank markets by information before modelling them.** Run this one statistic on every Kalshi short-horizon
   series we can price from a free tape. Trade only where it is positive on two separate weeks.
2. **Oil: stop buying long shots.** Gated oil trades that bought the side the model itself put under 50% won
   2 of 18 (−$3.02). Trades on the side the move favoured won 19 of 24 (+$3.63). Gas does not show this.
3. **Oil: thin quotes only.** Brent's information is +0.17 when the spread is 3–4¢ (95 windows) and about 0
   at 2¢ or less (294 windows). WTI is almost never thin, which is why it has no edge.

Risks on the gas record that the page should state:
- 37 of the 55 trades and $9.59 of the $10.48 came on Nov 9 and 10.
- 44 of 55 trades bought YES. The model averaged 54.7% up against 51.8% realized, so it leans up on gas.
- Fills are assumed at the quoted ask. Book depth at the decision minute is still not recorded.

Tried here and rejected (each scored worse or showed nothing):
- Anchoring on Kalshi's strike plus a rolling basis instead of the perp's own open: gas Brier 0.230 vs 0.190.
- Basis change since the previous window, and the previous window's outcome, as extra signals: no relationship.

Metals after one day: all three are behind their markets. Copper's perp agrees with the Kalshi result in only
85% of windows (97% for oil), so its price feed is a poor proxy for what settles. Gold's volatility sat at the
hard floor in 20% of windows. Too early to act on either.

## 2. Every other family, worst first

| Family | Earned weight | What is wrong | Do |
|---|---|---|---|
| Daily WTI, daily Brent | — (Brier 3.5× and 6.5× the market) | **Design fault.** Frozen 2 hours before settlement but centred on *yesterday's* settlement (`forecasters/oil.py`, `last.value`). It ignores today's price. Brent says 85% and gets 44%. | Retire. If a daily row is wanted, reuse the hourly construction (live price, time-scaled spread). |
| Daily natural gas | — (Brier 5× the market) | Uses the live price, but the NYMEX future, while the market settles on the Pyth index. Says 99%, gets 94%: the level is off. | Retire, or test one fix: anchor on the latest Kalshi 15-minute strike (see section 3). |
| Gasoline | — (Brier 9× on 67 rows) | Not read this pass. | Retire. |
| Weather highs | −0.11 (v2.1), −0.09 (NBM) | On contested rows the model's probability has no relationship to the result, with an average 20-point disagreement. The per-station bias fit in v2.1 did not help. | Retire all versions. |
| Weather lows | 0.14, 0.08 | Same shape, slightly less bad. | Retire. |
| Sports spreads and totals | −0.13 to −0.56 | Negative: where the feed disagrees with the line, the line is right. | Retire, with the `+cal` rows. |
| Sports winners | 0.02 to 0.06 | No information beyond the price. | Keep as a record or drop; no further work. |
| ERCOT peak | 0.09 | Badly under-confident (says 75%, gets 85%; says 85%, gets 96%). The spread is too wide. | Retire, or one cheap try: refit the spread. |
| Oil hourly v1, v2, v5 | 0.02, −0.02, 0.03 | Old delayed price feed. | Retire. |
| Crypto hourly BTC, ETH | −0.43, −0.10 (unstable) | Nothing beyond the price on about 650 contested rows each. | Stop development; keep only if the page needs it. |
| Oil hourly v4, v6 (live feed) | 0.26, 0.21 | Some information (0.05 on 1,349 rows). Under-confident: says 65/75/85%, gets 73/83/93%. | Keep **v4 only**. Next version: take the spread from 1-minute realized volatility, the change that won crypto's preregistered test. |
| Rain (v2.1) | 0.6 to 1.7 | The skill sits in the contested rows (66 of 184), not in easy strikes. But it is 8 days, and cities share weather systems. | Keep. Paper rule as proposed Nov 9; judge it by days, not rows. |

## 3. One free data source the hub is not using

Kalshi's 15-minute strike **is** the Pyth index price at each window's open (WTI, Brent, natural gas, gold,
silver, copper). Pyth itself is gated, but the strike is public, so the hub can read the true settlement index
every 15 minutes for free. Measured gap between the perp and that index: natural gas 93 basis points on average
(about 3¢, where daily strikes sit 0.5¢ apart), Brent 20, WTI 11. The daily and hourly models that settle on
Pyth could anchor on the latest strike plus the perp's move since. Untested; a replay from stored rows would
settle it. It did not help inside a 15-minute window (above).

## 4. How predictions are tracked

1. **Add earned weight to the scoreboard**, with a first-half and second-half figure. It answers "does this
   model know anything the price doesn't", which the Brier gap does not: natural gas is PROMOTED on a Brier
   gap of z −0.8, and its real case is the 0.88 weight.
2. **Score contested rows only.** Crypto's 33,886 settled forecasts contain 643 contested ones.
3. **Count days, not rows**, in every error bar.
4. **Hide empty rows.** 15 scoreboard entries have zero settled forecasts (`ens-v2`, the three `15m-v1`, others).
5. **Record book depth** at the 15-minute decision minute. Without it the gas record cannot be trusted for size.
6. **One preregistered hypothesis per family at a time.** The 15-minute family has three open studies on a
   week of data.

## Not done
- Gasoline, CPI, claims, labor, unemployment, FOMC and the direction models: too few settled forecasts to say
  anything (most under 30).
- Stock ideas and the earnings-outlook work.
- The admin pages left open in the product review (Workshop, Guidance, Screening, Deals, Agent debates,
  Health, Machine keys).
