# Action plan to finish the backlog (Claude, Nov 12)

Kevin asked Claude to check Muse's progress, review Muse's plan, and turn the remaining work into one ordered
list Muse can finish. This file is that list. It **replaces the ordering** in the "Prompt for Muse" in
`review-backlog-2026-11-12.md`; that file still has the full detail for each numbered item.

## Where things stand (checked Nov 12 against `origin/main`, GitHub and the live site)

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
| 1 | **Follow-up PR** | Kev seat: a watch or pass choice forces direction `none`, and an act with direction `none` raises `SeatUnavailable` (#495 comment). LEAPS: never store an `insufficient_data` verdict (#495). The four #496 items: weekday-only `curveTradingDays`, symbol+idea row keys on the fallback path, leg side and ratio in the full orders table, and the BandCrossings `findByLabelText` flake | No |
| 2 | **Kalshi demo runner** | Spec in the #492 comment "Kalshi demo runner". Demo host enforced in code, live host refused, guard test against other POSTs, 1-contract limit orders at the frozen quote, daily contract and loss caps, cancel if unfilled. **Add:** record the contracts on offer at the ask, and skip when it's under 1. Migration for the `kalshi_demo_orders` table | **Yes: go on the migration** |
| 3 | **Kalshi Portfolio tab** | Spec in the #492 comment "Kalshi gets its own Portfolio tab": `/portfolio?book=kalshi`, `/api/kalshi-demo`, a header with DEMO, Positions, Performance (demo against shadow), Orders, no order ticket. May share step 2's PR | No |
| 4 | **Gas fill check** (model 1) | Mark every past gated gas trade with the contracts on offer at its ask (#472 data). Report how many would have filled | No |
| 5 | **Health precompute** (product 7) | Build Health in the hourly job, then Macro and Weather. Target: `/api/health` under 1 s | No |
| 6 | **Overview landing page** (product 1) | One-sentence pitch, three headline numbers, what works and what failed, how it's built | Domain: Kevin |
| 7 | **Scoreboard** (model 2) | `earned_weight` column, contested rows only, error bars in days, hide empty rows, label retired rows | Yes: migration |
| 8 | Guidance method and naming (product 2) | As in the backlog | Skip the MRK part until Kevin decides |
| 9 | Workshop idea page split (product 3) | | No |
| 10 | Workshop falsifiable claims (product 4) | Equal-beta SPY-plus-cash test | No |
| 11 | Weather page trim (product 5) | | No |
| 12 | Copy pass (product 6) | | No |
| 13 | Oil "YES costs 0c" check (product 8) | | No |
| 14 | Hourly oil v7 shadow (model 3) | Preregister first | No |
| 15 | Replay anchors (model 4) | | No |
| 16 | Oil 15-minute filters (model 5) | Preregister both | No |
| 17 | Rain paper rule (model 6) | Preregister, judge by days | No |
| 18 | Volatility-regime challenger | From `review-2026-11-11-muse-round2-and-regime-challenger.md`, as a new shadow version | No |
| 19 | Code health (product 9) | Split `api/main.py` into routers; rewrite the README. Do this last so it doesn't conflict with the steps above | No |

**Skip until Kevin answers:** the MRK rule for guide steps over 35%; freezing Deals, IPOs, the Level watcher and
Agent debates; and whether Screening becomes a tracked idea.

## Done means (every step)
1. Tests are written first; there's no network in CI (stub Alpaca and Kalshi); Python, Vitest and tsc all pass.
2. CodeRabbit is requested. If it's rate limited, say so on the PR and Claude reviews instead.
3. Any migration waits for Kevin's go, is recorded in `docs/superpowers/plans/migrations-applied.md`, and is
   applied before the code that needs it merges.
4. The step's status is updated in `review-backlog-2026-11-12.md` in the same PR.
5. After the deploy, check the change on the live site (an endpoint or page) and quote the result in the PR.

## Hard rules
- No live Kalshi orders, anywhere. Demo only, enforced in code.
- Never change a live model in place: add a new shadow version beside it, preregistered first.
- Don't touch the live 15-minute rule, the blend's frozen rows, shadow scoring, or the Alpaca paper-order path.
- Never write secret values. Server and timer changes go in the PR as commands; Claude installs them.
- Never merge a PR flagged "do not merge without Kevin's approval".
