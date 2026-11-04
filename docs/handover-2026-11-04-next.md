# Handover: Algo Trade Hub, Nov 4, 2026 (from Claude Code, near the usage limit)

Main is at or past 812392a. Read `docs/handover-for-claude-2026-11-03-evening.md` for rules and standing state; PRs #353-#366 came after it. Where anything conflicts, trust the code and tell Kevin.

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
