"""Daily natural gas (KXNATGASD) settlement math: a live-price Normal with a
trailing daily sigma -- the hourly WTI construction at a daily grain.

Kalshi's daily natural-gas markets settle on the Pyth NATGAS index at 5:00 PM
Eastern (verified live 2026-11-03: series settlement source "Pyth - NATGAS";
event KXNATGASD-26NOV0417 closes 22:00Z; ~60 `greater` strikes an event at
$0.005 steps near the money). The model is the simplest honest one, exactly
the hourly oil shape: the settlement is a random walk from the live NG=F
print, with sigma = the trailing stdev of Kalshi's own settled DAILY changes,
scaled by sqrt(time-to-close / 1 day) so a freeze two hours out prices
tighter than one a day out. No drift term. Sigma counts only changes between
settlements exactly one day apart, so a skipped day (or a weekend gap, if
the series ever takes one) never inflates it.

The anchor caveat, stated once: the settlement is a Pyth INDEX print and the
anchor is the NYMEX front-month future. Any basis between them is real model
error -- the same arrangement the WTI engines run under (CL=F against the
Pyth WTI candle, validated to the cent on the daily row), and the graded
record is what measures it here.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from tradehub.backtest.pit import Observation
from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

SERIES = "KXNATGASD"
# The journal runs hourly; a 125-minute lead catches the 17:00 ET settlement
# from the mid-afternoon run whatever the timer's phase, the hourly oil
# lead's reasoning one grain up.
DECISION_LEAD = timedelta(minutes=125)
GAS_RESOLUTION = 0.001    # the Pyth index prints to thousandths; the half-step is noise vs sigma
MIN_DAILY_SIGMA = 0.01    # dollars; a floor so a dead-quiet stretch never prices at 0/1
SIGMA_CHANGES = 60        # trailing daily changes in the sigma fit (two trading months)
MIN_SIGMA_MINUTES = 15.0  # the sigma scaling never assumes less than fifteen minutes of travel
_EASTERN = ZoneInfo("America/New_York")


def event_time(name: str) -> datetime:
    """'KXNATGASD-26NOV0417' -> 2026-11-04 17:00 America/New_York (the settlement).

    The ticker's date part is YY + MON + DD + HH in Eastern wall time, the
    hourly oil series' shape with the hour fixed at 17."""
    part = name.split("-")[1]
    day = datetime.strptime(part[:7], "%y%b%d").date()
    return datetime.combine(day, time(int(part[7:9])), tzinfo=_EASTERN)


def daily_changes(settled: list[Observation]) -> list[float]:
    """Per-day settlement changes, counting only settlements exactly one day apart."""
    ordered = sorted(settled, key=lambda o: event_time(o.name))
    return [cur.value - prev.value
            for prev, cur in zip(ordered, ordered[1:])
            if event_time(cur.name) - event_time(prev.name) == timedelta(days=1)]


def daily_sigma(changes: list[float]) -> float:
    """Stdev of the trailing SIGMA_CHANGES daily changes, floored at MIN_DAILY_SIGMA."""
    window = changes[-SIGMA_CHANGES:]
    if len(window) < 2:
        return MIN_DAILY_SIGMA
    return max(MIN_DAILY_SIGMA, statistics.stdev(window))


def sigma_for(sigma_d: float, minutes: float) -> float:
    """Sigma for a settlement `minutes` away: random-walk scaling from the daily sigma."""
    return sigma_d * math.sqrt(max(minutes, MIN_SIGMA_MINUTES) / 1440.0)


def natgas_prob(market: KalshiMarket, live_price: float, sigma_d: float,
                minutes_to_close: float) -> float:
    """P(settlement resolves YES) for a Normal centred on the live price."""
    return prob_in_interval(live_price, sigma_for(sigma_d, minutes_to_close),
                            yes_interval(market, GAS_RESOLUTION))
