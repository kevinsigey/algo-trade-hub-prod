# Review of Muse's Nov 4 work

By Claude Code, Nov 5, 2026, at Kevin's request (`docs/handover-2026-11-04-claude-review.md`). Numbers are as of about 05:50 UTC. All samples are short and fall in one stretch, when WTI dropped from about $100 to $87.

## What I'd have done differently

1. **Remove Pyth, don't just route around it (#377).** Muse was right to stop at Hyperliquid, but left the board making refused Pyth calls before reaching the price it uses, plus a shadow that never froze a row. Both are gone.
2. **Score the feeds, don't assume (#377).** Kalshi's 15-minute strike is the official settlement price, so every feed can be measured. See the table below. Hyperliquid wins on evidence; before, it was only the free option.
3. **Don't let a frozen oracle pass as live (#377).** CodeRabbit caught this. The Hyperliquid read has no timestamp, so the stale check could never fire. It now needs recent trades within 1% of the oracle.
4. **Run the replay first.** The plan said so. Muse rebuilt the page before it and read the page as presentation. That's defensible, but the page kept a record line graded on the old feed: "This signal hasn't made money so far" described a model the page no longer shows. That line now uses the live-feed rows (see the record change below).
5. **Put geo2 on the live feed too.** All of geo2's hourly grading ran on the delayed CL=F price, where a wider range also hides the lag. On the same 289 rows: v1 0.1682, v5 geo2 0.1612, v4 live feed 0.1491. So v5 beating v1 can't show the stress is worth anything. New shadow `wti-hourly-v6-hl-geo2-shadow` is graded in pairs against v4. I didn't change geo2's weights, slope or cap: there's no evidence yet to move them.
6. **Fix the bug behind the NVDA leg (#378).** Reporting instead of closing it by hand was right. The cause: a kill sent two single-leg closes, and Alpaca refused selling the long leg as "uncovered" while the short was open (`paper_orders` id 27). The roll path already paired spreads; the kill path didn't. The leftover single call should close at the next morning run, not verified yet.
7. **Give the 15-minute model a live view (Kevin's redesign).** It only existed in the journal. `/api/oil/fifteen-live` now shows it, through the same code the journal freezes with.
8. **Change the doc that says agents don't apply migrations.** Kevin confirmed the route on Nov 1, so the doc was wrong, not Muse. It's corrected.

## Where I agree with Muse

- **Candle alignment:** using the candle ending at the open matches Kalshi's strike with 2.5c spread on WTI, against 11.9c for the candle starting at the open.
- **15-minute model form:** using Kalshi's official strike as the base beat Hyperliquid's open slightly on WTI (0.1699 vs 0.1737), lost slightly on Brent and lost badly on natural gas (0.2211 vs 0.1885). A slower volatility measure didn't help. No change.
- **The v2 bump, the 5-minute cron, the parity test and always "No call" on the hourly ladder:** all fine. The 15-minute panel does state a direction, because that contract is one.
- **Client-side fee math:** acceptable, since the formula is small and its result is covered by page tests. A shared server field is the upgrade if the fee ever changes.

## The evidence

**Free feeds against Kalshi's strikes and results, 312 windows:**

| Feed | WTI direction match | Brent | Natural gas | Live? |
|---|---|---|---|---|
| Hyperliquid perp | 96.2% | 97.8% | 94.2% | Yes, no key |
| OKX perp | 96.5% | 96.5% | 90.7% | Yes, unchecked from the VPS |
| Yahoo futures | 99.3% | 96.8% | 96.8% | No, about 10 minutes late |

Averaging Hyperliquid and OKX moved it under 1 point. Three quarter-hour samples suggest Hyperliquid's oracle sits closer to the official level than its trades, most clearly on natural gas (within 0.2c against 0.7c). That supports the board's oracle read. It's only 3 samples.

**Hourly, live feed against Kalshi on the same rows:** v4 0.1563, Kalshi 0.1518 (318 rows, 25 hours), against v1's much wider gap. The feed closed most of the gap, but v4 doesn't beat Kalshi. An earlier reading of mine that it did used a Kalshi quote frozen about 61 seconds earlier.

**Kevin's 30-minute entry idea, replayed on the live feed.** 76 hours, real Kalshi prices, 7% taker fee, biggest gap of 5+ points per hour:

| Time to close | Picks | Hit | Model said | Net per contract (SE) |
|---|---|---|---|---|
| 50 min | 35 | 51% | 52% | +7.5c (8.1) |
| 40 min | 33 | 45% | 54% | −0.1c (7.6) |
| 30 min | 32 | 44% | 47% | +6.2c (7.3) |
| 20 min | 29 | 38% | 41% | +6.0c (8.3) |
| 10 min | 40 | 32% | 51% | −10.6c (6.8) |

This overturns my Nov 4 conclusion that the price moves away from the model; that test was on the old feed (−15c at entry). On the live feed, hit rates mostly track the model's numbers from 50 to 20 minutes out (40 minutes is 9 points short), and the last 10 minutes are the bad stretch. No row is statistically different from zero, the leads share the same hours, and I tried several times, so it doesn't prove an edge. Simply waiting doesn't show up either: the price moved toward the model about half the time. The page already rolls to the next hour 20 minutes before a close.

**15-minute, graded at minute 5, buying at the real ask with a 2-point after-fee margin:** WTI 31 trades, +8.0c; natural gas 40 trades, +4.4c; Brent 32 trades, −0.2c. With about 9c of noise per row, none of that is an edge yet. Against Kalshi on Brier: WTI 0.1588 vs 0.1633, natural gas 0.1656 vs 0.1770, Brent 0.1952 vs 0.1899 (67 windows).

**Record line on the page, before and after:** 16 of 51 picks, −10.3c on the old feed; 4 of 11, −1.9c (SE 15.6) on the live feed. The new number isn't good news: 11 picks says almost nothing yet.

## Not verified

- Idea 50's remaining call closing at the 12:30 UTC run on Nov 5.
- The new v6 shadow's first frozen rows.
- OKX being reachable from the VPS. It's not in the chain, so nothing depends on it.
- CodeRabbit's look-ahead note on v4: on the record, `price_at` runs about 1.3 seconds before `frozen_at`, so I left it. The decision time inside the run wasn't measured separately.

## Next, for Kevin to rule on

The rebalance list, Idea 50 if the morning close fails, whether to drop the unused `PYTH_API_KEY`, and whether v4 should replace v1 as the hourly headline model. v4 has the better record so far, but that changes what the Model Tracker shows, so it's Kevin's call. Rerun the evidence with `scripts/research/oil_feed_score.py` and `scripts/research/oil_hourly_replay.py`.
