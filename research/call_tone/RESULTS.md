# Call Tone Backtest Results

Generated: 2026-11-07T14:18:23.714140

## Data Summary

- Total calls processed: 567
- Unique tickers: 43
- Date range: 2016-01-21 00:00:00 to 2025-05-15 00:00:00
- Calls with delta_tone (>=4 priors): 567
- Speaker turns usable: No (whole transcript used)

## Exploration Split

- Calls: 294
- Date range: 2016-01-21 00:00:00 to 2021-12-20 00:00:00
- Unique tickers: 39

| Signal | Horizon | Mean IC | t-stat | Tercile Spread | Quarters |
|--------|---------|---------|--------|----------------|----------|
| delta_tone_ret_60d |  | 0.0309 | 0.23 | 0.0178 | 5 |
| delta_tone_ret_20d |  | 0.1553 | 1.26 | 0.0174 | 5 |
| tone_level_ret_60d |  | 0.0120 | 0.12 | 0.0094 | 5 |
| tone_level_ret_20d |  | -0.0363 | -0.41 | 0.0034 | 5 |
| delta_uncertainty_ret_60d |  | 0.0000 | 0.00 | 0.0000 | 0 |
| delta_uncertainty_ret_20d |  | 0.0000 | 0.00 | 0.0000 | 0 |

## Holdout Split

- Calls: 273
- Date range: 2022-01-14 00:00:00 to 2025-05-15 00:00:00
- Unique tickers: 27

| Signal | Horizon | Mean IC | t-stat | Tercile Spread | Quarters |
|--------|---------|---------|--------|----------------|----------|
| delta_tone_ret_60d |  | -0.0453 | -0.52 | -0.0013 | 13 |
| delta_tone_ret_20d |  | -0.0670 | -0.97 | -0.0138 | 13 |
| tone_level_ret_60d |  | -0.1919 | -2.21 | -0.0476 | 13 |
| tone_level_ret_20d |  | -0.2084 | -3.41 | -0.0321 | 13 |
| delta_uncertainty_ret_60d |  | 0.0698 | 0.66 | -0.0273 | 7 |
| delta_uncertainty_ret_20d |  | -0.1796 | -2.63 | -0.0306 | 7 |

## Preregistered Rule (Holdout, 60d, delta_tone)

- Mean IC: -0.0453
- t-statistic: -0.52
- Tercile spread (after 20 bps): -0.0013

**FAIL**

*All three conditions: Mean IC > 0 (False), t >= 2.0 (False), Spread > 0 (False)*
