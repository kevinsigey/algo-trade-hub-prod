# Earnings-call tone: preregistered backtest (2026-11-07)

Kevin asked (2026-11-07) whether reading earnings calls can consistently tell us a company's outlook. This file fixes the
test BEFORE any result is seen. Nothing here is tuned after the fact; a failed result is reported as failed.

## Question
Does a change in management's tone on an earnings call, against that company's own recent calls, predict the stock's
return relative to SPY over the following 60 trading days?

## Data
- Transcripts: Hugging Face `kurry/sp500_earnings_transcripts` (MIT, 2005-2025, parquet). Read-only research input.
- Universe: tickers in `tradehub.guidance.universe.UNIVERSE` (today's S&P 100). Survivorship bias: companies that left
  the index are missing, which flatters any long-only result. Stated in the results, not corrected.
- Prices: yfinance adjusted daily closes for each ticker and SPY, cached locally.
- Calls from 2015-01-01 to the end of the dataset.

## Tone (deterministic, no model)
- Word lists: the Loughran-McDonald Master Dictionary (Notre Dame SRAF, free), Positive, Negative and Uncertainty.
- Management text only: drop operator and analyst turns when the transcript marks speakers. If it does not, use the
  whole transcript and say so in the results.
- tone = (positive - negative) / (positive + negative + 1); uncertainty share = uncertainty words / all words.
- Signal: delta_tone = tone - mean(tone of the same company's previous 4 calls). Calls with fewer than 4 prior calls
  are dropped.

## Timing (no look-ahead)
- Call date D from the dataset. Entry is the close of the first trading day AFTER D (calls can be before or after the
  bell; D+1 close is safe for both).
- Outcome: log return of the stock minus log return of SPY, entry close to the close 60 trading days later (primary)
  and 20 trading days later (secondary, reported only).

## Statistics
- For each calendar quarter, the Spearman rank correlation (IC) of delta_tone with the outcome across the calls in that
  quarter (quarters with fewer than 15 calls are dropped).
- Mean IC, t = mean / sd * sqrt(number of quarters).
- Tercile spread: mean outcome of the top third of delta_tone minus the bottom third, per quarter, averaged, minus
  0.20% for a round trip on both legs.
- Comparisons reported, never used to pass: tone level instead of change, and delta of the uncertainty share (sign
  flipped: more uncertainty, lower expected return).

## Split
- Exploration: calls up to 2021-12-31. Holdout: 2022-01-01 to the end of the data. The holdout is computed once, with
  exactly the rules above.

## Pass rule (holdout, 60-day outcome, delta_tone)
Mean IC > 0 AND t >= 2.0 AND the tercile spread after costs > 0. All three, or it fails.

## If it passes
It becomes a shadow idea first (live calls scored the same way, tracked without trading) before any paper money.
