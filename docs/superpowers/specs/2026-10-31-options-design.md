---
title: Options in the Workshop (model-priced backtests, Alpaca paper execution)
type: spec
domain: trading-hq
status: draft for Kevin's review
settlement_source: none
tags: [workshop, options, black-scholes, alpaca]
summary: Option legs on Workshop ideas, backtested with Black-Scholes prices from volatility indexes, checked against Alpaca's real 2024+ prices, then paper-traded on Alpaca.
---

# Options in the Workshop: design

**Kevin's answers (2026-10-31):**
- Plays: buy calls/puts on a signal, covered calls, protective puts, spreads, and "something else" (still to be named).
- History: model prices first; pay for data only if something looks worth it.

## 1. Why model prices

Free real option history covers about 2.5 years: Alpaca's bars start February 2024. Our test keeps the most recent 30%
of the data unseen and needs at least 504 unseen days (2 years), so 2.5 years can't pass that. Yahoo has only
today's option chain. Paid history (ThetaData, Polygon/Massive, ORATS) costs about $30-80 a month.

## 2. How model prices work

An option's fair price depends on five inputs:

| Input | Where we get it |
|---|---|
| Stock price | the ETF's daily close (already fetched) |
| Strike and days left | the idea's own rule, e.g. "30 days out, strike 5% below today's price" |
| Interest rate | the 3-month Treasury bill, FRED `DTB3` |
| Dividend yield | the ETF's trailing 12-month dividends ÷ price (yfinance) |
| **Volatility** (how much the market expects the price to swing) | **CBOE volatility indexes, free on FRED**; see the table below |

The Black-Scholes formula turns these five numbers into a price. Every option desk uses it as its baseline.

The only input you can't see on a chart is volatility, and CBOE publishes it every day for the big ETFs:

| ETF | Volatility index (FRED) | From |
|---|---|---|
| SPY | `VIXCLS` | 1990 |
| QQQ | `VXNCLS` | 2001 |
| IWM | `RVXCLS` | 2004 |
| GLD | `GVZCLS` | 2008 |
| USO (oil) | `OVXCLS` | 2007 |
| EEM | `VXEEMCLS` | 2011 |
| AAPL | `VXAPLCLS` | 2010 |

So on any past day we can answer "what would a 30-day, 5%-out-of-the-money SPY put have cost?" without option
history. Each day we re-price the contract with that day's close, rate, days left and volatility, which gives a
daily profit-and-loss series the existing engine can judge like any other idea.

**Where model prices are wrong, and what we do about it:**
- **Skew.** Out-of-the-money puts really trade at a higher volatility than the index, and out-of-the-money calls
  lower. With one volatility for all strikes, puts look too cheap: protective puts look better than reality, and
  covered calls look like they earn more premium than they do.
  - **Fix:** a simple skew curve (volatility as a function of moneyness and days left), fitted to Alpaca's real
    2024-2025 prices and checked on 2026. It is fitted once and stored, never re-fitted on the years being judged.
- **Bid-ask spread.** You buy at the ask and sell at the bid.
  - **Fix:** every option trade pays half the typical spread as a % of premium, measured from Alpaca quotes per ETF.
    SPY near the money is small; GLD and USO are bigger.
- **Early exercise and assignment.** These are American options, but the formula is European. That matters mainly
  for deep in-the-money calls right before an ex-dividend date.
  - **Fix:** a covered call whose strike is deep in the money the day before ex-dividend is treated as assigned.
- **Tickers with no volatility index.** Most single stocks have none.
  - **Fix:** those fall back to recent realised volatility × 1.1. The verdict labels that run "cruder model".

Every options verdict carries a **"model prices"** label and a calibration line. Example: "model vs Alpaca real,
2024-2026: median error 6% of premium". If the error for a play is too big, the verdict says so instead of
pretending to precision.

## 3. What an idea can say

Option legs sit beside the existing hold/short and rules. Each leg has:
- type (call or put) and side (buy or sell);
- days to expiry at entry (7-120) and strike as a % of the price (e.g. 95% = 5% below);
- a roll rule: roll N days before expiry, or close when the rule exits.

| Play | How it's written |
|---|---|
| Buy calls/puts on a signal | no stock leg; one bought option leg; enters and exits on the existing buy/sell rules |
| Covered call | hold the ETF; sell a call (e.g. 30 days, 105%); roll monthly |
| Protective put | hold the ETF; buy a put (e.g. 60 days, 90%); roll at 20 days left |
| Spread | two legs on one ETF (e.g. buy a 100% call, sell a 105% call); max 2 legs in v1 |

- **Sizing.** A bought option spends a set % of the idea's budget on premium, so it can only lose that. A covered
  call or protective put covers the shares held, one contract per 100 shares.
- **Never allowed:** selling an option that isn't covered by shares or by a bought leg (no naked calls or puts).

## 4. Build order (one PR each, reviewed like steps 5 and 6)

1. **Pricing core and data.**
   - A pure `options.py` with Black-Scholes price and the main sensitivities.
   - Fetchers for the volatility indexes, `DTB3` and dividends.
   - A calibration script that compares model prices with Alpaca's real 2024+ option bars and fits the skew curve
     and spreads.
   - Output: a calibration report you read before anything is backtested.
2. **Option legs in the spec, engine and editor.**
   - The four plays above, with the model-price label and calibration line on the verdict.
   - The deeper look (year by year, CSV) works for them too.
3. **Paper execution on Alpaca options.**
   - Contract choice (the listed contract nearest the leg's days and strike), order sizing and rolls.
   - Off by default, the same switch as stock auto orders, paper only.
   - This is a new order path, so it needs your yes when we get there.
   - The Alpaca paper account may also need its options trading level raised (a setting you change yourself in
     Alpaca).

## 5. Open for Kevin

- **"Something else" in your answer:** which play did you mean? Iron condors, calendars, and the wheel (sell puts,
  then covered calls once assigned) all fit this design.
- ~~Is a 2-leg cap fine for v1?~~ **Yes (Kevin, 2026-10-31): 2 legs for now.** Iron condors (4 legs) come after.

## 6. Not in scope

- Real option history before 2024. That waits for a paid source, and only if a model-priced play passes.
- Intraday option prices, Greeks-based hedging and portfolio margin.
