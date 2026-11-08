# Call Tone Backtest Results

Generated: 2026-11-07T14:26:20.539022

## Data Summary

- Total calls processed: 3445
- Unique tickers: 97
- Date range: 2015-12-22 00:00:00 to 2025-05-15 00:00:00
- Calls with delta_tone (>=4 priors): 3445
- Speaker turns usable: Yes (management = prepared-remarks speakers, all their turns; see tone.management_text)

## Exploration Split

- Calls: 2119
- Date range: 2015-12-22 00:00:00 to 2021-12-20 00:00:00
- Unique tickers: 95

| Signal | Horizon | Mean IC | t-stat | Tercile Spread | Quarters |
|--------|---------|---------|--------|----------------|----------|
| delta_tone_ret_60d |  | 0.0221 | 0.83 | -0.0011 | 24 |
| delta_tone_ret_20d |  | 0.0077 | 0.35 | -0.0011 | 24 |
| tone_level_ret_60d |  | 0.0349 | 1.00 | 0.0011 | 24 |
| tone_level_ret_20d |  | -0.0369 | -1.27 | -0.0100 | 24 |
| delta_uncertainty_ret_60d |  | -0.0070 | -0.25 | 0.0023 | 20 |
| delta_uncertainty_ret_20d |  | -0.0138 | -0.58 | -0.0019 | 20 |

## Holdout Split

- Calls: 1326
- Date range: 2022-01-14 00:00:00 to 2025-05-15 00:00:00
- Unique tickers: 97

| Signal | Horizon | Mean IC | t-stat | Tercile Spread | Quarters |
|--------|---------|---------|--------|----------------|----------|
| delta_tone_ret_60d |  | 0.0048 | 0.14 | -0.0021 | 14 |
| delta_tone_ret_20d |  | 0.0172 | 0.55 | -0.0010 | 14 |
| tone_level_ret_60d |  | -0.0126 | -0.43 | -0.0086 | 14 |
| tone_level_ret_20d |  | -0.0192 | -0.76 | -0.0040 | 14 |
| delta_uncertainty_ret_60d |  | -0.0379 | -1.16 | -0.0113 | 10 |
| delta_uncertainty_ret_20d |  | -0.0264 | -0.78 | -0.0052 | 10 |

## Preregistered Rule (Holdout, 60d, delta_tone)

- Mean IC: 0.0048
- t-statistic: 0.14
- Tercile spread (after 20 bps): -0.0021

**FAIL**

*All three conditions: Mean IC > 0 (True), t >= 2.0 (False), Spread > 0 (False)*
