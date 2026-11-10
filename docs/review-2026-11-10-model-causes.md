# Worst models: causes found, Nov 10, 2026 (Claude; unfinished, usage limit reached)

Follows `docs/review-2026-11-09-models.md`. Each finding comes from the live `journal_forecasts` and
`journal_settlements` rows (Supabase), read Nov 10. Nothing below is fixed yet.

## Bugs (wrong inputs, not weak models)
1. **Weather high/low (ens-v2.1): the bias fit has never run.** Every row carries `fit_pairs: 0, fitted: false`.
   `tradehub/data/hindcast.py::parse_day_values` reads `hourly["temperature_2m_ecmwf_ifs025"]`, but Open-Meteo's
   previous-runs API returns the key `temperature_2m` when one model is requested (checked live: HTTP 200, 96 values,
   parser returns 0 days). The failure is swallowed by design ("fits nothing, never crashes"). It should also request
   `temperature_2m_previous_day1` (the forecast as made a day earlier), not the latest run.
   Measured on 170 station-days since Nov 2: highs run **2.1°F too cold** (sd 1.64), lows 1.2°F too warm.
   Re-scored with a walk-forward bias (normal approximation on the stored mean, ~580 rows): highs 0.1975 → 0.1706,
   market 0.128. So the fix recovers about a third of the gap; it does not make temperatures competitive. Anchoring on
   yesterday's actual plus the model's day-over-day change gives about the same (0.173).
2. **Natural gas daily: wrong price.** Nov 9 20:14 UTC `live_price` 3.205 while Kalshi priced 98% above 3.27 and the
   15-minute page showed 3.389. 13 of 66 forecasts were confidently wrong (81% of its error). Use the 15-minute
   model's price source.
3. **Daily WTI and Brent: no intraday price.** Frozen ~75 minutes before settlement but centred on yesterday's
   settlement with a $3 sigma (Nov 4: 99.6% above $88.49 from a $96.09 prior settle; it settled below). Replace with
   the hourly engine applied to the daily strike, or retire.
4. **Gasoline: missing input and no trend.** `rbob_change` is null on 7 of 30 days, and the model ignores that AAA's
   daily change repeats (lag-1 autocorrelation 0.65, same direction 91% of 23 days). Add yesterday's change.
5. **ERCOT:** mean forecast 65% against a 51% base rate (biased high); Kalshi spreads are wide (bid 15 / ask 56), so
   the "market" reference is a soft mid. Also check the day mapping: target `…-26NOV10` carries
   `operating_day: 2026-11-09`.

## Not bugs: no information beyond the market
6. **Sports winners:** calibrated (slope 0.78 CFB, 1.11 NFL) but weight beyond the market is 0.00–0.06.
   **Spreads and totals are anti-predictive:** outcome regressed on our probability has a negative slope (CFB −0.15,
   NFL totals −0.53); the market sits at ~50% on these lines and our 7–12 point disagreements are noise. The feed
   snapshot is about 2 days old at freeze. The NFL repo excludes market lines by design and its own docs show the
   moneyline recalibration failed.
   Tracking gaps: `realized_value` is null on every settlement (no margin or total stored), the model's
   `margin_mu`/`sigma` are not in the payload, and there is no closing-line comparison. Add the closing Kalshi mid at
   kickoff and score closing-line value: it shows information in far fewer games than outcomes do.
7. **Oil hourly v4:** weight beyond the market is positive (0.16–0.34) but worth about 0.0003 Brier. Real, too small
   to trade. v6 is not better than v4.

## Still to check
- Whether rain (the one model beating the market) and natgas_15m survive clustering by day: weather ens-v2.1 rows only
  start Nov 2, so rain's 239 forecasts are about 8 days across correlated cities. The query was written but not run.
- Crypto hourly, the macro models (most under 30 settled), the NBM weather variants (payload has no mean to audit).
- Fix order I would take: weather hindcast key (1), natgas daily price (2), retire or rebuild daily oil (3), then the
  sports tracking fields (6).
