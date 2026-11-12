# Review backlog: every recommendation since Nov 9, with status (Claude, Nov 12)

Kevin asked whether everything from the review was handed on. It wasn't. The last two Muse prompts covered only the
admin fixes (A1–A4) and the 15-minute loop. The product and model lists in `handover-2026-11-10-claude-review.md`
were never sent as a prompt. This file is the single list. Status was checked against `origin/main` and the
production database on Nov 12, 00:20 UTC.

## Done, or merged and working
| Item | Where |
|---|---|
| 57 models retired, settle-only | #470. Checked live: no weather or ERCOT forecasts frozen in the last 6 hours, and oil hourly freezes only `wti-hourly-v4-hl-shadow` (120 rows) |
| Machine keys start with no scope; Screening and Health wording | #471 |
| The 15-minute tape records contracts on offer at the ask | #472 |
| Every machine order carries an idea or a stated reason; Portfolio splits tested from manual | A1, #477 |
| Verdicts re-labelled under the current bar | A2, #478 and #479 |
| Ideas carry their search, with "Trial N of M" | A3, #480 |
| Self-weighting blend shadow | #482 (rows start Nov 12) |

## In flight (open PRs from Muse)
| Item | PR |
|---|---|
| Quarterly figures rejected as full-year guides (TMUS); needs the MRK "basis break" amendment | #484 |
| LEAPS one-open-pair index | #485 |
| Debate packets repaired (10 of 10 verdicts were void) | #487 (A5) |
| Debate grading scheduled (0 graded since Nov 2) | #488 (A6) |
| Tests stop calling the live Alpaca paper API | #489 (A7) |
| LEAPS gate faults and the volatility-regime challenger | `review-2026-11-11-muse-round2-and-regime-challenger.md` |

## Not started: product
1. **Overview rework and visitor landing page.** Overview hasn't changed since the Nov 9 polish. Plan: say what the
   hub is in one sentence; show three headline numbers (models beating the market, the 15-minute gas record with its
   95% range, tested ideas against manual trades); one line each on what works and what failed; and how it's built.
   Lead with the 15-minute rules and the stock book. Also get a real domain (it's still a raw IP under sslip.io).
2. **Guidance method and naming.**
   - 36 of 49 names sit in a "strong" zone. The method is a peer-relative P/E, so every premium stock reads as a short.
   - Value each name at a blend of its own 5-year median multiple and the peer median, or rank by distance and show
     only the extremes.
   - Use one name everywhere: the code still says "valuation sheet" and "fact sheet". Use neutral zone words
     ("below / in line / above guidance value"); the code still says "Strong short" and "buy zone".
   - Publish whether past band crossings predicted returns.
3. **Split the Workshop idea page** into Draft, Verdict and Go live, with the gate panel built once.
4. **Workshop: claims that could fail.** "Cushions down days" passes by definition for low-beta assets. Require a test
   against an equal-beta SPY-plus-cash mix.
5. **Weather page**: highs, lows and ERCOT are retired. Trim it to rain, or move it to a lab archive.
6. **Copy**:
   - One-sentence intros (Strategies, Debates, Guidance, Deals).
   - One heading style.
   - Fold Agent debates into Guidance.
   - Admin pages behind a lock in the public menu.
   - Screening preset blurbs (`--`, "W18-style selection layer", "FCC lens", "bundled proxy — not yet refreshed").
7. **Health page**: still slow (15 s, and still "Loading…" after a 10-second wait). Precompute it in the hourly job;
   do the same for Macro and Weather.
8. **Oil/Commodities page**: "YES costs 0c" on rows with no quote. Check this, as I couldn't confirm it from the
   source.
9. **Code health**:
   - Split `tradehub/api/main.py` into routers by area. It has grown to 4,770 lines from 4,410.
   - Rewrite the README, which still describes the Vercel-reads-Supabase architecture.

## Not started: models (each as a new shadow version, preregistered first)
1. **Gas fill check.** Mark every gated gas trade with the contracts on offer at its ask, using the #472 depth data.
   This comes before any gas automation, demo or live.
2. **Scoreboard**:
   - Wire `earned_weight` (needs a jsonb column on `journal_scores`).
   - Score contested rows only (10–90%).
   - Count error bars in days, not rows.
   - Hide rows with zero settled forecasts, and label retired rows as retired.
3. **Hourly oil v7**: v4 with the spread from 1-minute realised volatility (v4 says 65/75/85% and gets 73/83/93%).
4. **Replay**: anchor daily natural gas and Brent on the latest Kalshi 15-minute strike (the free Pyth read).
5. **Oil 15-minute filters**: no trades on the side the model puts under 50%, and trade only at spreads of 3¢ or more.
   Preregister both.
6. **Rain**: preregister the paper rule; judge it by days.

## Decisions for Kevin (nobody can build these without an answer)
- LEAPS: change the delivery definition or the 80% bar.
- MRK and any guide step over 35%: hold the band until confirmed?
- Freeze Deals and IPOs, the Level watcher, and the Agent debates page (no new work until used)?
- Screening: wire one screen into a tracked idea as a real test, or keep it as a lookup tool?
- Gas demo plumbing needs a demo API key on the server.

## Prompt for Muse (after the current A5–A7 PRs)
> Work from `docs/review-backlog-2026-11-12.md`, top to bottom within each section, one PR per numbered item,
> CodeRabbit on every PR, migrations only with Kevin's go and recorded in `migrations-applied.md`.
> - Start with model item 1 (the gas fill check), product item 1 (the Overview landing page) and product item 7
>   (Health precompute).
> - Then work through product items 2–9 and model items 2–6.
> - Skip any item whose decision is still open under "Decisions for Kevin".
> - Models: new shadow version beside the current one, preregistration first; never change a live model in place.
> - No live Kalshi order placement.
> - Mark each item's status in this file in the same PR that does it.
