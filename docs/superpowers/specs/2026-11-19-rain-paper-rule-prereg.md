# Preregistration — the rain paper rule (weather_rain, ens-v2.1)

Frozen 2026-11-19 (action plan step 19; the Nov 9 models review's
proposal, carried by the Nov 10 deep dive: "Keep. Paper rule as proposed
Nov 9; judge it by days, not rows"). PREREG_AT = **2026-11-19T06:00:00Z**.
No rain row frozen before that instant scores — the Nov 9/10 evidence
selected this rule, so it cannot also grade it.

## Why this model gets a paper rule at all

Rain ens-v2.1 is the one statistically real skill the Nov 9 review found
in the hub: Brier gap −0.021 (z −2.6), +14¢ a simulated trade over 69,
and the raw model beats its own blend. The deep dive's caution stands
beside it: the skill sits in the contested rows (66 of 184), the record
was 8 days, and cities share weather systems — rows within a day are
not independent evidence. Hence this rule is judged by days.

## The rule (frozen)

- **Population.** Settled `weather_rain` forecasts at version
  `ens-v2.1`, frozen at or after PREREG_AT, carrying a recorded quote.
  A row with no quote in its payload is counted as unquoted and never
  scored.
- **The trade.** The journal's own simulation convention, unchanged
  (`tradehub/journal/costs.py::simulated_trade`): buy the side with the
  larger after-fee edge at its visible ask, only when that edge is
  positive and the price clears the no-longshot floor; one contract;
  settle at 0 or 100¢; net of the Kalshi taker fee. No new parameters.
- **Judged by days.** Rows group by ET day of the freeze. A scored day
  is a day with at least one trade; its score is the mean net ¢ per
  trade that day. The headline is the mean of the daily scores with a
  95% lower bound over days (each day one observation).
- **Verdict.** At **20 scored days**: proven if the lower bound is
  above zero. At **40 scored days**: failed if the lower bound is at or
  below zero. Between, and before 20 days, the rule is accruing and no
  verdict is read. A proven rule earns a promotion conversation with
  Kevin — nothing here places a real or demo order, and the forecaster
  itself is untouched.
- **The cap, stated.** Kalshi lists about 35 rain markets a day (the
  journal froze 34–36 ens-v2.1 rows a day over Nov 12–18, 2026), so the
  rule can take at most ~35 one-contract trades a day before its edge
  floor cuts that down. That is what this model can ever earn at this
  size; the report carries the recent listings pace beside the score.

The scorer is `tradehub/research/rain_paper.py`; the runner
(`tradehub/scripts/rain_paper_run.py`) writes
`$TRADEHUB_RESEARCH_DIR/rain_paper.json`. Read-only, like every shadow.
