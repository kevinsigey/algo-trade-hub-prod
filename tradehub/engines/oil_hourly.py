"""Hourly WTI (KXWTIH) settlement math: a live-price Normal with a trailing hourly sigma.

Kalshi's hourly WTI markets settle on the close of the 1-minute WTI candlestick at the top
of the hour (Pyth WTI; verified live 2026-11-01: event KXWTIH-26NOV0122 closes 03:00Z and
its rules read "the close price of the 1-minute candlestick for WTI Oil ... at 10:00 PM
EST"). There is no Brent hourly series and no 15-minute oil series on Kalshi -- those
15-minute ladders are crypto-only -- so this hourly WTI model is the intraday oil build.

The model is deliberately the simplest honest one: the settlement an hour out is a random
walk from the live CL=F price (the tape the daily engine already validated against Kalshi
settlements to the cent), with sigma = the trailing stdev of Kalshi's own settled hourly
changes, scaled by sqrt(time-to-close / 1h) so a freeze 5 minutes out prices tighter than
one 55 minutes out. No drift term: an hour is too short for the daily regression's drift
to be anything but noise. Sigma counts only changes between settlements exactly one hour
apart, so the daily trading halt and the weekend gap never inflate it.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from tradehub.backtest.pit import Observation
from tradehub.engines.oil import OIL_RESOLUTION
from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

HOURLY_SERIES = "KXWTIH"
# The journal runs hourly; a 65-minute lead catches the next top-of-hour close from any
# run phase (a 55-minute lead would miss forever if the timer fires in the first five
# minutes of the hour). A run in the last five minutes before an hour also catches the
# imminent contract -- honestly graded, with its sigma scaled to minutes.
HOURLY_DECISION_LEAD = timedelta(minutes=65)
MIN_HOURLY_SIGMA = 0.05   # dollars; a floor so a dead-quiet stretch never prices at 0/1
SIGMA_CHANGES = 72        # trailing hourly changes in the sigma fit (three trading days)
MIN_SIGMA_MINUTES = 5.0   # the sigma scaling never assumes less than five minutes of travel
_EASTERN = ZoneInfo("America/New_York")


def event_hour(name: str) -> datetime:
    """'KXWTIH-26NOV0122' -> 2026-11-01 22:00 America/New_York (the settlement hour).

    The ticker's date part is YY + MON + DD + HH in Eastern wall time, the same shape the
    daily series uses with its 14 suffix; `markets.event_date` reads only the date.
    """
    part = name.split("-")[1]
    day = datetime.strptime(part[:7], "%y%b%d").date()
    return datetime.combine(day, time(int(part[7:9])), tzinfo=_EASTERN)


def hourly_changes(settled: list[Observation]) -> list[float]:
    """Per-hour settlement changes, counting only settlements exactly one hour apart."""
    ordered = sorted(settled, key=lambda o: event_hour(o.name))
    return [cur.value - prev.value
            for prev, cur in zip(ordered, ordered[1:])
            if event_hour(cur.name) - event_hour(prev.name) == timedelta(hours=1)]


def hourly_sigma(changes: list[float]) -> float:
    """Stdev of the trailing SIGMA_CHANGES hourly changes, floored at MIN_HOURLY_SIGMA."""
    window = changes[-SIGMA_CHANGES:]
    if len(window) < 2:
        return MIN_HOURLY_SIGMA
    return max(MIN_HOURLY_SIGMA, statistics.stdev(window))


def sigma_for(sigma_h: float, minutes: float) -> float:
    """Sigma for a settlement `minutes` away: random-walk scaling from the hourly sigma."""
    return sigma_h * math.sqrt(max(minutes, MIN_SIGMA_MINUTES) / 60.0)


def hourly_prob(market: KalshiMarket, live_price: float, sigma_h: float,
                minutes_to_close: float) -> float:
    """P(settlement resolves YES) for a Normal centred on the live price."""
    return prob_in_interval(live_price, sigma_for(sigma_h, minutes_to_close),
                            yes_interval(market, OIL_RESOLUTION))
