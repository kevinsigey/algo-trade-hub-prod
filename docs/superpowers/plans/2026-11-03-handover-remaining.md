# Handover: remaining work from the 2026-11-03 deep dive

Checklist source: `docs/reviews/2026-11-03-deep-dive.md`. Work top to bottom.

## Done (#333-#337)
RLS on the three open tables, Health and Macro reads, security headers, `day` instead of `opg` for open orders, go-live refusing sizes that can't trade tested options, fill check (`paper_order_checks`), Portfolio redo, chokepoint explainer. Idea 12 killed, idea 16 paused, idea 50 resized to 2%, `PORTFOLIO_ACCOUNT_NUMBER` set.

## Rules
- Paper only, never real money. Don't touch Predictor repos. Never read or print secrets, or `/opt/stack/.env` values. Kevin sets VPS secrets himself with `scripts/set-vps-secret.sh`.
- Prod, credential and live-trading changes need Kevin's explicit yes.
- Migrations go in `market_sentiment_tool/supabase/migrations/` and are recorded in `docs/superpowers/plans/migrations-applied.md`. `paper_orders` and `order_switches` are append-only. Every new table enables RLS.
- Check test exit codes, not just the totals line. Run frontend tests with blank Supabase env; a failing vitest fails the deploy. A page test that imports `adminJson` needs `vi.mock("@/lib/supabase")`.
- Write the failing test first. Fakes hide query bugs: check real PostgREST behaviour (1000-row cap; jsonb `contains` takes a JSON string).
- Serialize merges and merge pinned: `gh pr merge --merge --match-head-commit <sha>`. Curl the live site after each deploy.

## 1. Watch the next order runs first
Mon-Fri 12:30 UTC orders, 14:45 UTC protect and fill check. Confirm `day` orders fill, `paper_order_checks` gets rows, and Book 2's first orders behave. Nothing has proved `day` orders yet.

## 2. Screener rebuild (`pages/Screening.tsx`, `tradehub/screening/`)
Kevin: too slow; the list should show right under the search bar; clicking a stock should show its last quote and a chart.
- Slow because `run_spec` enriches up to 300 names one at a time from rate-limited yfinance, synchronously in the request. Measure first, then pre-compute a daily universe snapshot (timer plus cache), so a run filters stored data. Show the data's age.
- Move results directly under the search box, above universe, presets and library. They currently render last.
- Row click opens a panel with last quote, day change, volume and a price chart, using `workshop_closes`-style data. Label delayed data. Keep provenance reachable.

## 3. Ideas tab and PASS rigor
Kevin: PASS should be heavily critiqued, and not 30+ tracked ideas for no reason. Drop the 63-day concern.
- Hub-wide test registry; show "Nth idea tested" with a deflated or FDR-adjusted bar.
- Group related ideas into families (the five chip ideas are one bet).
- Label pick-then-test and screen-promoted ideas "hindsight-selected".
- Make walk-forward part of PASS (`verdict_of(on_u[0], p, bar)` ignores the folds).
- `tradehub/agent/gate.py` passes `variations=1`: count attempts per spec. Check a blocked spec can't return to draft.
- Cleaner tab: active and meaningful ideas first, grouped, "gate overridden" labelled. Cache `/api/ideas` (7.6 s).
- Existing PASS verdicts may change: show Kevin the before and after before switching.

## 4. Options
Skew curve, bid-ask cost and calibration against real Alpaca prices (options design doc section 2), plus a calibration report. Label option PASSes unproven until then. Don't re-enable idea 16: it needs about 100 SPY shares, so Kevin decides whether it moves to the $1M book.

## 5. Chokepoints and commodities
- Ship feed: on Nov 3 all 18 ships were near Dubai, none in the gate, 14 with no type. The model's gate-entry signal can't fire while the median is 0. Find a real flow source.
- IMF PortWatch `Daily_Chokepoints_Data` has the right fields (`n_tanker`, `capacity_tanker`), but its ArcGIS `/query` returned "Invalid URL" on every try. Try its CSV download. Other free sources are from memory and untested.
- Test one more chokepoint for coverage before adding others (Bab el-Mandeb or Suez).
- Natural gas forecaster first (`KXNATGASD`): EIA storage needs a free key Kevin registers; degree days exist. Check which benchmark the contract settles on. Then power, grains, softs, metals. New models freeze in shadow first.

## 6. Smaller fixes
- Protect job only covers the main book: `store.auto_ideas` ignores `big`. No Book 2 idea uses intraday exits yet.
- `machine_api.stop_capacity` and `broker_orders` ignore the book.
- Audit remaining unpaged reads (`api/main.py` ~line 2193, 105 `.select(` calls). 11 Health problems remain, mostly news-tone families: check if real.
- Journal growth: 19k rows/day, DB 234 MB, plan limit unchecked. Check it soon and consider rollups.
- Standardize 76 silent excepts (log plus a visible "unavailable", never zeros). Slippage from `paper_order_checks`. Shadow vs real-fill comparison. Portfolio sector limits (a warning exists). Manual-action dedupe ignores idea.
- ESLint: 9 `no-explicit-any` errors in Deals. Split `api/main.py`. Retire `market_sentiment_tool/backend`. Trim public `/api/health`. CI route-auth inventory. Stale scoreboard labor figure (0.1792 vs 0.17391).
- Prune merged remote branches and `_wt`: merged only, keep dirty. PR #172 needs Kevin's decision.

## Ask Kevin
Keep or revoke the "mac scripts" machine key. Rotate the four BLOCKERS keys from `PL_Predictor/.env`.
