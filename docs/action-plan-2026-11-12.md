# Action plan to finish the backlog (Claude, Nov 12)

Kevin asked Claude to check Muse's progress, review Muse's plan, and turn the remaining work into one ordered
list Muse can finish. This file is that list.

**Nov 12 update:** steps 1 and 4 merged (#499, #501). Step 2 is in review (#500: two fixes, then Kevin's go on the migration). Step 5, the Portfolio redesign, was added after Kevin asked whether the plan covered everything he'd asked for. It hadn't: the first version was built from the backlog, which predates the Portfolio review. It **replaces the ordering** in the "Prompt for Muse" in
`review-backlog-2026-11-12.md`; that file still has the full detail for each numbered item.

## Status, Nov 12 20:45 UTC
- Merged: steps 1–4 (#499, #500, #501, #505), 6 (#502), the page-load fix #504, and step 5 part 1 (#506). #500, #504, #505 and #506 merged without Claude's review.
- **Blocking: #500's runner can never trade** (gas decisions are written only after their window closes). Fix spec: the #500 comment of Nov 12, 20:08 UTC. Do this before the rest of step 5.

## Where things stood (checked Nov 12 against `origin/main`, GitHub and the live site)

- **Merged:** everything in the backlog's "In flight" table (#484–#489), plus #493–#496. This PR moves those
  rows to Done.
- **No open Muse PRs.** No branch exists yet for the follow-ups, the Kalshi runner or any "Not started" item.
  Nothing has moved since #496 (03:25 UTC Nov 12).
- **Still true on the live site:**
  - `/api/health` takes **16.1 s**.
  - `tradehub/api/main.py` is 4,770 lines.
  - The volatility-regime challenger exists only as a review doc.
- **Decision now settled:** the Kalshi demo key is on the server (RSA, `KALSHI_ENV=demo`, $500 balance, read
  check passed on Nov 11). Remove "Gas demo plumbing needs a demo API key" from the decisions list.

## Review of Muse's plan (the backlog prompt)

The order is sound, but three things need changing:
1. **Kevin has since set a priority:** the follow-up PR first, then the Kalshi demo runner, ahead of everything
   else.
2. **The backlog says the gas fill check must come before any gas automation**, and that conflicts with point 1.
   - Resolution: the runner records the contracts on offer at the ask when it places each order, and refuses
     to order when the ask has fewer than 1.
   - The backward-looking fill check over past gated trades (model item 1) follows straight after the runner.
     Both rely on the same #472 depth data.
3. **The prompt never asks for a check after deploy.** Every item below is done only when the live site shows it
   (see "Done means").

## The plan, in order (one PR per step)

| # | Step | Detail | Needs Kevin |
|---|---|---|---|
| 1 | **Follow-up PR** ✅ #499 | Kev seat: a watch or pass choice forces direction `none`, and an act with direction `none` raises `SeatUnavailable` (#495 comment). LEAPS: never store an `insufficient_data` verdict (#495). The four #496 items: weekday-only `curveTradingDays`, symbol+idea row keys on the fallback path, leg side and ratio in the full orders table, and the BandCrossings `findByLabelText` flake | No |
| 2 | **Kalshi demo runner** (in review, #500) | Spec in the #492 comment "Kalshi demo runner". Demo host enforced in code, live host refused, guard test against other POSTs, 1-contract limit orders at the frozen quote, daily contract and loss caps, cancel if unfilled. **Add:** record the contracts on offer at the ask, and skip when it's under 1. Migration for the `kalshi_demo_orders` table | **Yes: go on the migration** |
| 3 | **Kalshi Portfolio tab** | Spec in the #492 comment "Kalshi gets its own Portfolio tab": `/portfolio?book=kalshi`, `/api/kalshi-demo`, a header with DEMO, Positions, Performance (demo against shadow), Orders, no order ticket. May share step 2's PR | No |
| 4 | **Gas fill check** (model 1) ✅ #501 | Mark every past gated gas trade with the contracts on offer at its ask (#472 data). Report how many would have filled | No |
| 5 | **Portfolio redesign** (added Nov 12; it was missing from the first version of this plan) | Everything under "The redesign Kevin asked for" and "Live updates" in `review-2026-11-12-portfolio.md`. **Header:** today split at the 4:00 PM ET close, SPY and QQQ benchmarks, and a warnings strip that replaces the Portfolio check card. **Tab 1, Book:** composition readable without scrolling, Positions with no idea information, By idea as expandable rows, movers by ticker. **Tab 2, Performance:** curve against SPY and QQQ with a drawdown band, daily return bars, stats, return by idea and sector, tested against discretionary over time, realized P&L by week. **Tab 3, Trade:** the order ticket open on the page, and full lists of staged and recent orders and closed trades, with no pop-ups. Metrics refresh on the 30-second cycle. The Kalshi book from step 3 sits beside Main and $1M. Split it into 2–3 PRs (header + Book, Performance, Trade) if one gets too big | No |
| 6 | **Health precompute** (product 7) | Build Health in the hourly job, then Macro and Weather. Target: `/api/health` under 1 s | No |
| 7 | **Overview landing page** (product 1) | One-sentence pitch, three headline numbers, what works and what failed, how it's built | Domain: Kevin |
| 8 | **Scoreboard** (model 2) | `earned_weight` column, contested rows only, error bars in days, hide empty rows, label retired rows | Yes: migration |
| 9 | Guidance method and naming (product 2) | As in the backlog | Skip the MRK part until Kevin decides |
| 10 | Workshop idea page split (product 3) | | No |
| 11 | Workshop falsifiable claims (product 4) | Equal-beta SPY-plus-cash test | No |
| 12 | Weather page trim (product 5) | | No |
| 13 | Copy pass (product 6) | | No |
| 14 | Oil "YES costs 0c" check (product 8) | | No |
| 15 | Hourly oil v7 shadow (model 3) | Preregister first | No |
| 16 | Replay anchors (model 4) | | No |
| 17 | Oil 15-minute filters (model 5) | Preregister both | No |
| 18 | Rain paper rule (model 6) | Preregister, judge by days | No |
| 19 | Volatility-regime challenger | From `review-2026-11-11-muse-round2-and-regime-challenger.md`, as a new shadow version | No |
| 20 | Code health (product 9) | Split `api/main.py` into routers; rewrite the README. Do this last so it doesn't conflict with the steps above | No |

**Skip until Kevin answers:** the MRK rule for guide steps over 35%; freezing Deals, IPOs, the Level watcher and
Agent debates; and whether Screening becomes a tracked idea.

## Done means (every step)
1. Tests are written first; there's no network in CI (stub Alpaca and Kalshi); Python, Vitest and tsc all pass.
2. CodeRabbit is requested. If it's rate limited, say so on the PR and Claude reviews instead.
   **Merge rule (Kevin, Nov 12, 20:11 UTC): no PR merges until Claude posts a review saying it's ready to merge.** This
   replaces "keep going without waiting" and the rate-limit rule for merges. Keep building the next step in a new PR
   while you wait, as long as it doesn't touch the open PR's files.
3. Any migration waits for Kevin's go, is recorded in `docs/superpowers/plans/migrations-applied.md`, and is
   applied before the code that needs it merges.
4. The step's status is updated in `review-backlog-2026-11-12.md` in the same PR.
5. After the deploy, check the change on the live site (an endpoint or page) and quote the result in the PR.

## Hard rules
- Never merge without Claude's ready-to-merge review (see "Done means" item 2).
- No live Kalshi orders, anywhere. Demo only, enforced in code.
- Never change a live model in place: add a new shadow version beside it, preregistered first.
- Don't touch the live 15-minute rule, the blend's frozen rows, shadow scoring, or the Alpaca paper-order path.
- Never write secret values. Server and timer changes go in the PR as commands; Claude installs them.
- Never merge a PR flagged "do not merge without Kevin's approval".

## Everything Kevin asked for, and where it is
| Ask | Where |
|---|---|
| Kalshi demo trading for the gas model, at 1% of the account per trade | Step 2 (#500) |
| Kalshi as its own Portfolio tab | Step 3 |
| Portfolio page bugs (Sharpe, duplicate tickers, counts, multi-leg names) | Done, #496 and #499 |
| Portfolio redesign: header, SPY and QQQ, warnings strip, Book / Performance / Trade tabs, live metrics | Step 5 |
| Auto-trader off until further notice | Done, #498 |
| Debate grading on a schedule | Done, #488; deploy crontab at 05:07 UTC |
| Everything in the Nov 9–11 reviews | Steps 6–20 (detail in `review-backlog-2026-11-12.md`) |
