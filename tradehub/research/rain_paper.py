"""Step 19: the rain paper rule -- weather_rain ens-v2.1 traded on paper
under the journal's own simulated-trade convention, judged by days.

Preregistration: docs/superpowers/specs/2026-11-19-rain-paper-rule-prereg.md
(frozen 2026-11-19). Pure computation over injected rows; the runner
(scripts/rain_paper_run.py) does the reading. Cities share weather
systems, so rows within a day are not independent evidence: a day's
score is its mean net cents per trade, and the verdict reads the days.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from tradehub.fifteen_volregime import clustered_low95
from tradehub.journal.costs import frozen_quote, simulated_trade

PREREG_AT = datetime(2026, 11, 19, 6, tzinfo=UTC)
FORECASTER = "weather_rain"
VERSION = "ens-v2.1"
PROVE_DAYS = 20
FAIL_DAYS = 40
_ET = ZoneInfo("America/New_York")


def _et_day(when: datetime) -> str:
    return when.astimezone(_ET).date().isoformat()


def evaluate(rows: list[dict]) -> dict:
    """Score the settled rows (each: frozen_at, probability, payload,
    outcome) frozen at or after PREREG_AT. Trades are the journal's own
    simulated_trade over the row's recorded quote -- no new parameters."""
    scored = unquoted = trades = 0
    by_day: dict[str, list[float]] = {}
    for row in rows:
        if row["frozen_at"] < PREREG_AT:
            continue
        scored += 1
        quote = frozen_quote(row.get("payload"))
        if quote is None:
            unquoted += 1
            continue
        trade = simulated_trade(float(row["probability"]), quote[0], quote[1],
                                int(row["outcome"]))
        if trade is None:
            continue
        trades += 1
        by_day.setdefault(_et_day(row["frozen_at"]), []).append(trade["net_cents"])
    day_means = {day: sum(v) / len(v) for day, v in sorted(by_day.items())}
    items = [(day, mean) for day, mean in day_means.items()]
    mean_day = sum(day_means.values()) / len(day_means) if day_means else None
    low95 = clustered_low95(items) if items else None
    days = len(day_means)
    if days >= PROVE_DAYS and low95 is not None and low95 > 0:
        state = "proven"
    elif days >= FAIL_DAYS and (low95 is None or low95 <= 0):
        state = "failed"
    else:
        state = "accruing"
    return {"rows": scored, "unquoted": unquoted, "trades": trades,
            "days_scored": days,
            "day_means": {d: round(m, 2) for d, m in day_means.items()},
            "mean_day_net_cents": round(mean_day, 2) if mean_day is not None else None,
            "day_low95": round(low95, 2) if low95 is not None else None,
            "state": state,
            "prove_days": PROVE_DAYS, "fail_days": FAIL_DAYS}


def listings_pace(rows: list[dict], *, days: int, now: datetime) -> dict:
    """How many rain rows the journal froze per ET day over the trailing
    window -- Kalshi's listing pace, the cap on what the rule can earn."""
    start = now - timedelta(days=days)
    counts: dict[str, int] = {}
    for row in rows:
        if start <= row["frozen_at"] <= now:
            counts[_et_day(row["frozen_at"])] = counts.get(_et_day(row["frozen_at"]), 0) + 1
    observed = len(counts)
    total = sum(counts.values())
    return {"window_days": days, "days_observed": observed, "rows": total,
            "mean_per_day": round(total / observed, 2) if observed else None}
