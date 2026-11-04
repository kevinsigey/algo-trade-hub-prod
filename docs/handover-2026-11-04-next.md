# Handover: Algo Trade Hub, Nov 4, 2026 (from Claude Code, near the usage limit)

Main is at or past 812392a. Read `docs/handover-for-claude-2026-11-03-evening.md` for rules and standing state; PRs #353-#366 came after it. Where anything conflicts, trust the code and tell Kevin.

## Latest: Oil page and 15-minute research (Nov 4, 05:15 UTC, read-only, nothing built)

**Status changes:** circuit breakers are done (4% daily, 15% drawdown, both books, `enabled: true` on `/api/portfolio?book=main|big`, not tripped). Work item 2 and the "code defaults" line below are superseded. Commit nothing that changes the Oil page until Kevin says yes to the plan here.

**Kevin's asks:**
1. Reassess the Oil page: best edge isn't direction. He wants direction, a range, when to buy and at what price.
2. He used the page and saw an edge signal come true about 30 minutes later. He thinks the gap is real but needs time, and asks whether that can time entries and become the signal. He also says part of this is his own skill.
3. Build a 15-minute model now that we have live data.
4. EIA data: is it natural gas only? Natural gas should get its own page under Commodities.
5. He likes "buy below", to set limits at several prices, with sizing math.
6. Later, automate this into an edge signal once it's somewhat reliable.

**Findings. All old-feed: `wti-hourly-v1` on delayed CL=F, Nov 2-4 only, and oil fell from about $100 to $95 in that window. The newer feed is untested: `v4-hl-shadow` has 76 rows, under 2 hours.**
- The model has no direction view. It's a Normal centred on the live price with trailing sigma. YES edges high plus NO edges low only mean our range is wider than Kalshi's that hour.
- 38 settled hours: 87% landed in our 80% range. Model buckets 25-75% are within 3 pts of actual. Its 90-100% rows hit 81% against 97% predicted (rows overlap within an hour, so rough). Mean miss on the settled price: ours $0.33, Kalshi $0.27.
- When Kalshi's midpoint and our price differed by at least 10c (21 hours), it settled on Kalshi's side 81% of the time. Likely our anchor lagging.
- Entry timing replay, 41 hours: biggest model-vs-mid gap of at least 5 pts per hour, cost 20-80c, freeze about 44 min to close, Kalshi 1-minute candlesticks, real ask, 7% quadratic taker fee. **Kevin's convergence idea did not show up on this feed: the price moved away from the model.**

| Entry after the freeze | Hours | Hit | Net per contract (SE) | Mid moved toward model |
|---|---|---|---|---|
| +0 min | 40 | 32% | -15.1c (7.0) | n/a |
| +10 min | 41 | 34% | -10.3c (6.7) | 41% of hours |
| +20 min | 39 | 31% | -9.3c (5.6) | 38% |
| +30 min | 37 | 27% | -8.3c (5.3) | 32% |
| +40 min | 34 | 26% | -5.6c (5.0) | 26% |

  Later entries lose less only because the price had already moved against the pick, so this isn't evidence that waiting works. One good trade doesn't contradict it, and it doesn't test the live feed either. Retest on the live feed before saying Kevin's idea is wrong.
- A resting "buy below" limit has a catch: on this data it would tend to fill when the price moves against the model. Test fills before recommending ladders.
- **15-minute markets exist. Our code comments say they don't (`tradehub/engines/oil_hourly.py:6`, `tradehub/journal/forecasters/oil_hourly.py:13`); fix them.** `KXWTI15M`, `KXBRENT15M`, `KXNATGAS15M`. One up/down contract per window: YES if the close is at least the price at the start. So it is a direct direction market. Settles on Pyth PYTHOIL, BRENT, NATGAS; our key gets 403 on PYTHOIL.
- 15-minute volume per market: WTI about 81k contracts, natural gas about 18k, Brent about 7k. One snapshot of WTI spread: 0.4c. Settled history: WTI and natural gas 4,790 each since Aug 28, Brent 927 since Oct 21.
- 15-minute base rates: up WTI 51.2%, Brent 52.2%, natural gas 50.4%. Next window same direction: WTI 47.7% (SE 0.7), Brent 47.4% (SE 1.6), natural gas 49.9% (SE 0.7).
- WTI "reversal" looks real on 4,790 windows (47.7% same, SE 0.7) but fails at real prices: last 300 windows, reversal bought at minute 1, 3 or 5 hit 50.2%, cost about 50.5c, net about -2c (SE 2.5-2.8). At 50c the break-even after the 1.75c fee is about 52%. No tradable edge from simple momentum or reversal.
- EIA is not natural gas only: it also publishes weekly crude and petroleum stocks. From memory, verify: petroleum Wednesdays and gas storage Thursdays, 10:30 ET. `EIA_API_KEY` is set, and no code reads it.
- Natural gas has no page. The only link under Commodities is `/oil` (`market_sentiment_tool/src/App.tsx:121`). `natgas_daily` has one day of journal rows (Nov 3).

**Proposed plan, awaiting Kevin's yes:**
1. Rebuild the top of the Oil page: range first, Kalshi's beside it, direction "No call" by default, a "Buy below" column replacing "Best edge", and "No trade" replacing the Best strike banner.
2. Build a replay before anything else. Kalshi candlesticks are public at `/series/{s}/markets/{t}/candlesticks?period_interval=1`, so with minute prices for the anchor any entry rule can be tested without waiting weeks. Candidate anchors: Pyth Benchmarks history and Hyperliquid candles; neither is confirmed yet. Use it to retest Kevin's convergence idea on a live feed, entry timing, and limit fills.
3. Add a 5-minute board log going forward (paper, append-only, RLS).
4. 15-minute shadow in the journal for all three series, graded against Kalshi. A signal must clear about 52% at 50c; pre-register it.
5. Natural gas page under Commodities reusing the Oil page's parts, then the EIA storage shadow. Consider EIA report times as range wideners for oil.
6. Sizing on buy-below: contracts = budget / limit. Check maker fees per series; don't assume 7%.
7. Automation in stages: replay, shadow, paper through the gap tracker. Rule fixed before testing, unseen data, net positive after fees. The hub stays paper only; real money is Kevin's own decision.
8. Optional, for Kevin's skill point: log his manual entries so his judgement can be graded beside the model.

Ask Kevin before building; he may also change the order of this against the work list below.

## Kevin's decisions, in his words where it matters

- **Trade the best grouped ideas.** One lead per bet. Keep 47, 51, 54 trading.
- **Rebalance by moving the correct number of shares**, not by closing a whole position before opening another. Build programmatic closing and rebalancing. He accepts slippage; this is a long-term test.
- **Archive to the VPS slowly:** controlled, very targeted, possibly aggregated, to keep Supabase light. Check through the Supabase connector before and after. Move nothing without confirming the copy.
- **Breaker numbers delegated:** code defaults of 4% daily loss, 15% drawdown, both books, env can override.
- **NVDA spread:** closes only if the idea really died. It did: killed, and p 0.043 fails the bar. Check `closing_activations` closes it.
- **Drop unused tables, retire unused backend, decide PR #172:** approved, after verifying.
- **Crypto page:** reassess around our plays with specific trading metrics, or make it educational.
- **Screener:** he asks whether Finviz tools can improve it, "because everything is educational".
- **Handoff:** write a file like this at 95%+ usage.

## Work list, in order

1. **Pyth format.** `tradehub/data/pyth.py`: Pro feed WTIZ6 (3073) returns 200 but fails "wasn't in the expected shape". PYTHOIL and Hermes answer 403 not entitled; Kevin was asked to request a grant. Trial ends about Nov 18; then compare paired Brier for `wti-hourly-v1`, `v3-pyth-shadow`, `v4-hl-shadow`.
2. **Breakers.** Kevin was given the commands to set the four env limits with `scripts/set-vps-secret.sh`. Check the Portfolio rail reads "On" on both books; if not, set them with him. Code defaults aren't needed, and would trip test fakes that have no `last_equity`.
3. **Programmatic rebalance.**
   - Show Kevin the exact list and sizes and wait for his yes before any idea or order changes.
   - Passing bets: bonds/gold 17,31,52; defensives 36,38,53; SPY covered call 16,25; discount retail 33,49; TSM/INTC 37,58; WSM/RL 39,48; chip giants 43,55; chip equipment 26; ASML 42; real estate 45; commodities 57.
   - Main book's manual positions (XOM, XLE, CVX, XOP, XLU, AAPL short, MA, XLV, XLP, TWLO, META) have no closing job.
   - Design: compute target shares per symbol across the book's live ideas, diff against held shares, and send only the difference, sells first. Label the fills to the new idea so attribution stays right. Watch that `plan` currently sizes per idea against that idea's FIFO lots, so a net-by-symbol diff has to keep lots and `order_labels` consistent. Options need 100 shares per contract and go through go-live's structure check. The 25% per-symbol cap and the breakers still apply.
4. **Archive.** Biggest tables: signal_events 97 MB, predictions 71 MB, journal_forecasts 29 MB, agent_logs 16 MB; DB 239 MB; plan limit unknown. VPS 14G free of 38G. Find out if the two biggest are old data first. Never touch the frozen journal's graded rows without aggregating and verifying.
5. **Cleanup:** tables, `market_sentiment_tool/backend` (referenced by Dockerfile, tradehub/core/env.py, scripts/sniper_regrade.py, tests/test_env_hygiene, test_repo_layout, test_migration_exception_conditions, README, SYSTEM_ARCH), PR #172, CodeRabbit notes on #365 if any.
6. **Crypto page.**
7. **Screener research:** Finviz has no free official API. `finviz` and `finvizfinance` scrape the site and can break; check Finviz's terms before running one on a schedule. Twelve Data, Alpha Vantage and Finnhub have free tiers, limits unverified. The screener's real gap is fundamentals and speed through yfinance; compare before adding anything.

8. **EIA storage in the natural gas model.** `EIA_API_KEY` is set and listed in compose. No code reads it yet, so it's unverified. Build it as a new shadow version, not a change to natgas-v1.

## Rules that bit today

- Check the test exit code before committing.
- Self-merge only when CodeRabbit actually says it's rate limited, and say so on the PR. Post `@coderabbitai review` directly: `gm2.sh` stops at Vercel's free build limit first. Waiting caught a real desk-route bug on #358.
- Don't run `set-vps-secret.sh` or `vps-pass-env.sh` during a deploy: they collide.
- `/opt/stack/compose.yml` lists env vars explicitly. A new secret needs `scripts/vps-pass-env.sh NAME` too.
- Remote: `https://github.com/kevinsigey/algo-trade-hub-prod.git`.
- Paper only. Never read or print secrets. Don't touch Predictor repos.

## Open with Kevin

Pyth grant for PYTHOIL. 3 gap-tracker paper positions on KXWTI-26NOV0414 predate the 2-per-event limit. Dated watches stay with Muse unless he says otherwise.
