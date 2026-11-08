# Earnings-call outlook statements: preregistered backtest (2026-11-07)

Kevin (2026-11-07): not tone. Parse the calls for real forward-looking financial statements ("we expect margins to
shrink 2% next quarter", "we expect increased revenue next quarter", "tariffs will raise our costs") and trade them both
ways, long and short. This file fixes the test before any result is seen. A failed result is reported as failed.

## Data
Same as the tone test (docs/superpowers/specs/2026-11-07-call-tone-prereg.md): kurry/sp500_earnings_transcripts, today's
S&P 100 (survivorship bias stated, not corrected), calls 2015-01-01 to the end of the data, yfinance adjusted closes,
management speakers = tone.management_text.

## Extraction (free models only, no Claude credits)
1. Deterministic prefilter: keep management sentences that contain a forward cue (expect, anticipate, guidance, outlook,
   forecast, will, should, plan, project, believe, headwind, tailwind, next quarter, next year, second half, full year,
   fiscal 20xx). Cap 6,000 words per call, keeping sentence order.
2. One free OpenRouter model call per call (tradehub.workshop.draft._models(), rotating on errors) returns a list of
   statements: topic (revenue, demand, pricing, gross_margin, operating_margin, eps, costs, tariffs, guidance, capex, other), direction
   (up, down, flat), magnitude_pct (number or null), horizon (next_quarter, full_year, longer, unspecified), quote.
3. Verification: the quote must appear in the call text (normalized whitespace and case); a percent given must appear in
   the quote. Failing statements are dropped and counted. Extractions are cached per call (resumable).

## Signal (fixed)
- Sign for the stock: revenue, demand, pricing, gross_margin, operating_margin, eps: up +1, down -1. costs, tariffs:
  up -1, down +1. flat 0. other: excluded.
- guidance (the company's own outlook vs its prior outlook): raised +1, cut or withdrawn -1, kept 0. capex: recorded,
  not scored. (Amended 2026-11-08 after the pilot and before the full run: no results had been computed.)
- Direction counts only when the speaker states a comparison; a bare range is flat (pilot finding, same amendment).
- Only horizons next_quarter and full_year.
- score = (sum of signs) / (number of signed statements); a call with no signed statements has no score.
- Primary signal: score (what management said). Comparison (reported, never used to pass): score minus the company's
  previous scored call.

## Trading rule (both ways)
Entry at the close of the first trading day after the call. Outcome: log return of the stock minus SPY over 60 trading
days (primary) and 20 (reported).
- Long when score >= +0.5. Short when score <= -0.5. Otherwise no trade.
- Costs: 0.20% round trip per position (shorts the same; borrow cost ignored for S&P 100 names, stated).

## Statistics
Per calendar quarter (>= 15 scored calls): Spearman IC of score with the outcome. Mean IC, t = mean/sd*sqrt(quarters).
Long book: mean outcome of long trades after costs. Short book: mean of (-outcome) of short trades after costs.

## Split
Exploration: calls up to 2021-12-31. Holdout: 2022-01-01 to the end. The holdout runs once.

## Pass rule (holdout, 60 days, primary score)
Mean IC > 0 AND t >= 2.0 AND the long book after costs > 0 AND the short book after costs > 0.
The short side must stand on its own: Kevin wants the signal to work both ways.

## If it passes
Shadow first: live calls (a transcript source is needed; Alpha Vantage has them) scored the same way and tracked
without trading, before paper money.
