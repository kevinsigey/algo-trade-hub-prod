---
title: quants.md strategies and TradingAgents, mapped to the Workshop
type: research
domain: trading-hq
status: active
settlement_source: none
tags: [workshop, strategies, quants-md, tradingagents]
summary: Which quants.md strategies the Workshop can test after step 6, which need new engine features, how they link to ideas 3/5/6, and where TradingAgents fits.
---

# quants.md strategies → the Workshop (2026-10-31)

Sources: Kevin's `quants_md_mapping_2026-10-31.md` (rules read from the QuantJourney code) and
`TradingAgents-Ideas-Feed-Spec.md`. Site ideas today: **#3** "Gold does better when stocks are down" (no run yet),
**#5** "Oil as a ballast against the fall of the S&P" (no run yet), **#6** XLE pipeline test (live, 1 share).

"Step 6" means the buy/sell-when rules now being built (Part A: price signals; Part B: analyst signals).

## What can be tested now

These run on the Workshop as single-ticker ideas once step 6 Part A is deployed:

| Card | Rule in Workshop terms | Closest idea | Notes |
|---|---|---|---|
| **W01** SMA trend (Sharpe 0.45) | hold XLE (or GLD); buy when `sma_cross` 50/200 > 0; sell when `sma_cross` < 0; otherwise CASH; claim `smoother_ride` vs the same ticker | **#5** oil, **#3** gold | Their version runs 9 sectors, each on its own rule. The engine gives one rule to all legs, so test one ticker per idea. |
| **W03** RSI reversion (DD −49%) | hold XLE; buy when `rsi`(14) < 35; sell when `rsi` > 60; add `max_days` 20 | **#6** XLE | The audit's point: with no filter it buys falling knives. Run it raw first, then with a trend filter (all of: RSI < 35, `vs_sma` 200 > 0). That shows what the filter is worth. |
| **O03** limit dip buyer | buy when `rsi` < 40; limit order 150 bps under; `take_profit_pct` 3, **plus** `stop_loss_pct` and `max_days` | none (new) | Its 100% win rate comes only from never closing a loser. Our exits book every position, so the honest version needs a stop and a time exit. Our backtest assumes a limit order always fills, so this is optimistic. |
| **O15** bracket | `exits.mode = intraday`, stop 0.4% / take-profit 0.6% | none (practice) | This is the step 5 bracket on daily bars. The 5-minute RSI entry can't be built (no minute bars). |
| **Oil ballast, done right** | hold XLE; buy when SPY `vs_sma` 200 < 0 (stocks in a downtrend); claim `ballast` | **#5** | This tests #5 directly. Our prior is that oil fell with stocks in 2008 and 2020, so expect FAIL. That is a cheap result to have on record. |
| **Gold when stocks are down** | hold GLD; buy when SPY `pct_change` 21 < 0; otherwise SPY; claim `ballast` | **#3** | #3 as written. W05/W20 say ballast improves Sharpe but not return, so judge it on `ballast` or `smoother_ride`, not `beats_benchmark`. |

## What needs a new engine feature

| Card | Missing piece | Worth building? |
|---|---|---|
| **W18 / O17** multi-asset momentum rotation (Sharpe 0.57 / 0.53) | **Ranking**: each month, hold the top 3 of 8 ETFs by 126-day return. The engine can't rank tickers against each other. | **Yes, top pick for step 7.** It's new to us, confirmed twice in the library, and fits monthly paper execution. GLD and DBC are in its universe, so it holds #3's and #5's assets with a reason. Build it at 1× (no vol-target leverage). |
| **W05** inverse-vol / **W20** risk parity | **Weights**: legs are equal weight today. | Later. W05 (weights ∝ 1/63-day volatility) is the easy one and could become the default "ballast basket" weighting. W20 is just SPY with extra steps (correlation 0.94). |
| **W13 / W14** pairs z-score | A spread series between two tickers. | **No.** Sharpe −0.05 and −0.30 even with no borrow cost. Confirms the IWM/QQQ pair we already killed. |
| **W15** cross-sectional momentum | Ranking plus long/short. | **No.** +1.3% total over 26 years; same null as our Fama-MacBeth test. |
| **W12** drift-band rebalance | Partial rebalancing. | Engineering only; matters once rotation (W18) trades monthly. |
| **WF01** walk-forward | Rolling folds. | Our backtest already holds back a true unseen span and requires a 63-day live gate. Rolling refit folds would be a stricter extra check. Park it until there is a fitted parameter to refit. |

The library's audit lessons are already in our engine:
- A strategy whose only exit is a take-profit fakes a perfect record. Our exits close every position.
- Headline returns aren't comparable across cards; Sharpe is. Our verdict compares each idea with its benchmark on unseen years.

## TradingAgents (LLM debate feed)

This is a different kind of thing from the strategies above. It is a qualitative memo per ticker, not a rule the engine can backtest. The spec keeps it fenced off: no orders, no signals, and graded after the fact (+5 and +20 trading days, Hold counts as no-call). That fits the hub.

**Proposed order:** after step 6 Part B, as its own plan, before or beside W18 rotation.

**Kevin needs to:**
- Answer the spec's 3 open questions. My defaults are:
  - the mid-tier model through the OpenRouter key we already have, if the framework supports it at the pinned SHA;
  - live-date runs only;
  - Nov 2–6 earnings names first.
- Add an LLM key to the VPS himself if a paid model is chosen.

**Build risk:** TradingAgents pulls in LangGraph and its own data vendors. It runs in a separate venv or container, so its dependencies never touch the tradehub image. The §8 import-isolation test enforces that.

## Proposed next steps

1. **Step 6 Part A ships** (in review now). Then, with Kevin's OK, create the W01-XLE, W03-XLE, #5-done-right and #3 runs as Workshop ideas. They are research runs only; nothing goes live without the 63-day gate.
2. **Step 6 Part B**: analyst ratings and price targets.
3. **Step 7**: rotation (ranking) for W18/O17, at 1×, with W05 inverse-vol weights as an option.
4. **TradingAgents feed**: its own plan, once Kevin answers the questions above.
