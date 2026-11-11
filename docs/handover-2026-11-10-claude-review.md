# Handover from Claude's review — Nov 10, 2026 (for Muse and Kevin)

Kevin's instruction: Claude reviews, Muse implements. This is the work list. Evidence for the model items is in
`review-2026-11-10-models-deep-dive.md`; the admin-page review is the addendum in `review-2026-11-09-product.md`.
The live-page findings below are new (signed-in pass, Nov 10 evening, phone-width pane).

## Done today
- #470 retired 57 scoreboard rows (settle-only from now on). **Not yet confirmed live**: check after the next
  hourly journal run that `oil_wti_hourly` freezes only `wti-hourly-v4-hl-shadow`.
- #471 machine keys start with no scope; Screening and Health wording.
- #472 (open, safe to merge, migration applied): the minute tape records contracts on offer at each ask.
- Local only, unpushed: branch `feat/earned-weight-score` on Kevin's Mac holds `earned_weight()` and its tests.

## Findings from the live admin pages

### 1. Workshop: the retry penalty does not see the search that produced the idea (most important)
Idea 47 is titled "Random Lab Gen 3 trial 54". Its page says "Variations tried on this idea: 1 · bar raised
accordingly" and passes at p = 0.029. It is at least the 54th trial of a third generation of a random search,
so a p of 0.029 is what chance alone produces two or three times in 54 tries. The Workshop shows 45 PASS
against 10 fail. On Nov 10 four versions of one idea (SPY/QQQ above the 200-day average, "Spec E-1" to "E-4")
were tested as four separate ideas, and three passed.
- Fix: carry a search id on every lab-generated or sibling idea, and raise the bar by the number of trials in
  that search, not the number of variations on the one idea.
- Until then, show "trial N of a search of M" on the verdict.

### 2. Workshop: stale verdicts under the old bar
Idea 47's page still reads PASS with "needs < 0.05". Kevin's bar since #359 is p ≤ 0.01 and 3 of 4 folds, and
47 fails it. Either re-label stored runs under the current bar or print which bar a verdict was judged on.

### 3. Workshop: easy claims pass
Most live ideas claim "to cushion down days" for defensive holdings (utilities, staples, gold). Low-beta
assets fall less than SPY on down days by construction, so the test confirms the definition. Require a claim
that could fail: for example, a better return per unit of drawdown than a plain SPY-plus-cash mix of equal beta.

### 4. Workshop: where the money was lost
Closed paper P&L by idea: all tested ideas together about +$268; "No idea yet (manual)" −$1,752 on 31 trades.
The loss on the main book is the untested manual trades. Worth saying on the Portfolio page.

### 5. Guidance: 36 of 49 names are in a "strong" zone
8 strong buy, 28 strong short, 1 neutral. The method (the company's own guide × its peer group's median
multiple) calls every stock that trades at a premium to peers a strong short (LLY $1,431 against a $411–470
band, WMT $126 against $44–50, PLTR $166 against $25–28) and every discounted one a strong buy (ADBE $234
against $485–540). That is a peer-relative P/E screen, and it does not discriminate.
- Fix options: value each name at a blend of its own 5-year median multiple and the peer median; or keep the
  method and rank by distance, showing only the top and bottom few.
- Two bands look like data errors and should be checked against the filings: MRK ($30.80–35.51 against a
  $147 price) and TMUS ($22.60–25.11 against $169).
- Small: the tile says "28 in strong short zones" while the summary line says "28 in short zones"; the
  snapshot stamp is printed twice.
- The band-crossing record is the real test of this page: publish whether past crossings predicted returns.

### 6. Agent debates: nothing has been graded
Every debate on the page ran on Nov 2. The +5-day grade was due Nov 9 and the record still shows "0 graded".
Check that the grading job runs. Also: the intro says the hub "runs it on your Gemini key" while the runs
list `nvidia/nemotron-3-ultra` (free); and ARM's stated entry ($202.50) was 19% above the traded price
($170.26), which the page flags itself. The panel invents price levels.

### 7. Health still does not load in 10 seconds
The page showed "Loading…" after a 10-second wait. Precompute it in the hourly job.

### 8. Screening: preset text still shows `--` and jargon
#471 fixed the page's own text. The preset blurbs come from the server and still read "-- the W18-style
selection layer", "FCC lens", "the Finviz value screen in native functions". "My tickers" reads "bundled
proxy — not yet refreshed", which means nothing to a reader.

### 9. Tests reach the live Alpaca paper API
Seven tests in `tests/test_machine_api.py` and `tests/test_machine_exit_exemption.py` failed in one run with
a DNS error for `paper-api.alpaca.markets` (GET `/v2/orders`), then passed when the network was back. Tests
should not depend on, or touch, the broker.

## Model work, in order (each as a new shadow version beside the current one)
1. **Stage 2 of gas automation.** Kalshi's demo exchange lists KXNATGAS15M but its book is empty (bid 1¢, ask
   $1.00), so demo orders test plumbing only. Do the fill check first: once #472 has a few days of data, mark
   every gated trade with the contracts that were on offer at its ask. Demo plumbing needs a demo API key on
   the server (Kevin's call).
2. **Hourly oil v7** = v4 with the spread taken from 1-minute realized volatility (v4 says 65/75/85% and gets
   73/83/93%).
3. **Replay test**: anchor daily natural gas and Brent on the latest Kalshi 15-minute strike (the free read of
   the Pyth index) instead of the futures price.
4. **Oil 15-minute shadow filters**: no trades on the side the model puts under 50%; trade only when the
   spread is 3¢ or more. Preregister both before looking at more data.
5. **Scoreboard**: wire `earned_weight` (needs a jsonb column on `journal_scores`), score contested rows
   only, count error bars in days, hide rows with zero settled forecasts, label retired rows as retired.
6. **Rain**: preregister the paper rule; judge by days.

## Product work, in order
1. Workshop search-level bar (finding 1) and stale verdicts (finding 2).
2. Guidance method and naming (finding 5; one name, neutral zone words).
3. Split the idea page into Draft, Verdict and Go live; build the gate panel once.
4. A visitor landing page and a real domain.
5. Weather page: highs, lows and ERCOT are retired, so trim the page to rain or move it to an archive.
6. One-sentence intros, one heading style, Agent debates folded into Guidance.

## Not reviewed
Machine keys and Deals were not opened live (read from source only). Desktop-width layout was not checked;
the pane was phone width.
