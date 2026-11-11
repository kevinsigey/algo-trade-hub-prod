# Admin features: does each one work, and is it worth having? — Nov 11, 2026 (Claude)

Method: each feature checked against its own tables in production (05:30 UTC Nov 11), plus the signed-in pages.
"Works" means it does what its page says. "Worth" means it has produced something that changed a decision or
could be graded. Most records are under two weeks old, so "no evidence yet" is common and is not a failure.

| Feature | Works? | Worth it so far? | Evidence |
|---|---|---|---|
| Machine keys (order API) | Yes | Yes, but it bypasses the idea pipeline | 142 orders placed, 80 preflights. Guards fired when they should: daily cap, defined risk, position, scope, book, ownership. |
| Automatic paper orders | Mostly | Yes | Latest broker status: 100 filled, 5 expired, 1 cancelled. 17 orders rejected by Alpaca as "potential wash trade"; 34 skipped (too small, or waiting on shares). |
| Workshop tests | Runs as built | Not shown | 98 runs: 53 PASS, 35 FAIL, 10 not enough data. Forward record: 26 tracked ideas, median 6 days, 10 of 26 ahead of their benchmark, mean −1.5 points. Too early, and not ahead. |
| Guidance recorder | Yes | Yes, as a dataset | 363 filings read: 194 with guidance, 168 without, 1 failed. 541 records for 77 companies, 354 with a consensus figure. |
| Guidance bands and zones | Runs; two confirmed wrong inputs | No | 36 of 49 banded names are "strong". TMUS is valued on EPS of $2.99 and MRK on $2.66–2.76, which look like one quarter's figure used as the full year. |
| Band crossings | Runs | No evidence yet | 4 crossings ever, all on Nov 10, all suppressed, log-only. None graded. |
| Guidance debates (verdicts) | **No** | No | 10 verdicts rendered, 10 void. The free model's answers fail the format check ("rubric weight guide_credibility missing" ×5, "unknown choice 'watch_and_pass'" ×3). 70 candidates wait behind it. |
| Agent debates page | Runs | No | All runs are from Nov 2. Nothing graded. Feeds nothing by design. |
| Screening | Yes | Unused | 7 saved screens, all run, 0 promoted to a tracked idea. |
| Deals and IPOs | Yes | Unused | 6 runs, all on Nov 3. |
| Level watcher | Unknown | Unused | 0 watches have ever been created. |
| Idea critic | Check | Unclear | 74 critiques on 23 ideas; the last is dated Nov 8, so it missed two trading days. |
| Health | Loads slowly | Yes when it loads | Still "Loading…" after 10 seconds on Nov 10. |

## The three findings that matter

**1. Most trading does not go through a tested idea.** All 142 orders placed through the machine keys carry
no idea (order labels: `api:muse big book` 74, `api:mac scripts` 43, `api:muse main book` 25, every one with
a null idea). The Workshop tile says 75 of 133 fills are attributed. Closed paper P&L is about +$268 for all
tested ideas together and −$1,752 for "No idea yet (manual)". The site's claim is that every strategy has
rules fixed in advance; the order API is a second door with no such rule.
- Fix: the order API should require an idea id or a declared reason, and the Portfolio page should split
  results into "tested ideas" and "discretionary".

**2. A Workshop PASS is not yet evidence.** Three reasons, each from the data:
- 29 of the 49 passing runs with a p-value sit at the floor of the shuffle test (0.001). Those are mostly
  "cushions down days" claims for low-beta holdings, which are true by construction.
- 12 passing runs have p between 0.01 and 0.05, which fails the bar set on Nov 3. They still read PASS.
- About 46 of 74 ideas came from generated batches ("Random Lab", "Spec E-n"), and the retry penalty counts
  variations per idea, not per batch.
The forward record is the only thing that will settle it, and after a median of 6 days it is slightly behind.

**3. The Guidance stack has no working output.** The recorder underneath is good. Above it, the zones do not
discriminate, crossings have fired four times with none graded, and every debate verdict is void. The whole
chain from "zone" to "verdict" has so far produced nothing a person could act on or grade.
- Cheapest repair: validate full-year against quarterly figures at ingest (TMUS, MRK); make the verdict
  parser accept or repair near-miss answers, or use a model that follows the format; and judge the zones by
  the crossing record before building more on them.

## What I would cut, keep and fix
- **Keep and lead with:** the order API and paper-order automation, the guidance recorder, the Workshop's
  test engine (with the search-level bar).
- **Fix before adding anything:** order attribution, stale PASS labels, the void verdicts, the quarterly-as-
  annual inputs.
- **Freeze (no new work until used):** Deals and IPOs, Level watcher, the Agent debates page.
- **Screening:** it works and nobody promotes from it. Either wire one screen into a tracked idea as a real
  test of the funnel, or treat it as a lookup tool and stop building the promote path.

## Not checked
Whether the idea critic's cron is installed; the Health page's contents (it did not load); desktop layout.
