"""Kalshi hourly WTI (KXWTIH): the spot-and-realized-vol forecaster.

The contract settles on the close of the 1-minute candle at the top of the
hour on the Pyth WTI index (the series' own rules). The model is the crypto
desk's ladder logic carried to oil: at freeze time the settlement is

    last CL=F price + Normal(0, sigma_hour * sqrt(minutes_to_close / 60)),

with sigma_hour the trailing 5-minute realized vol scaled to an hour. No
drift term and no fitted parameters -- an hour is too short for the daily
model's regression to mean anything, so the row prices the tape's own vol
against the market's ladder, nothing more. Freeze window: 5-50 minutes
before the close -- late enough that the remaining move is mostly vol,
early enough that a journal run lands inside it. CL=F is the anchor, not
the Pyth index itself; the basis between them is part of what the graded
record measures. No persistence row: at a 30-minute horizon persistence IS
this model with the vol set by hand, so it would grade nothing extra.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.wti import wti_intraday
from tradehub.engines.oil import hourly_prob, hourly_sigma
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.kalshi_linked import (
    KalshiImplied,
    entry_for,
    kalshi_target,
    quote_mid,
    quote_payload,
    settle_on_kalshi,
)

HOURLY_SERIES = "KXWTIH"
FAMILY = "oil_hourly"
VERSION = "wti-hourly-v1"
MIN_TO_CLOSE = timedelta(minutes=5)
MAX_TO_CLOSE = timedelta(minutes=50)


class HourlyInputs:
    """CL=F 5-minute bars, loaded once per run (keyed on `now`, the house rule)."""

    def __init__(self, bars_fn: Callable[[], list] = wti_intraday):
        self._bars_fn = bars_fn
        self._now: datetime | None = None
        self._bars: list = []

    def bars(self, now: datetime) -> list:
        if now != self._now:
            self._now = now
            try:
                self._bars = [b for b in self._bars_fn() if b[0] <= now]
            except Exception:  # noqa: BLE001 -- a dead tape freezes nothing, never crashes the run
                self._bars = []
        return self._bars


class OilHourly:
    name = "oil_wti_hourly"
    version = VERSION
    cadence = "hourly"

    def __init__(self, live, fetch: Callable[[str], Any], inputs: HourlyInputs):
        self._live, self._fetch_market, self._inputs = live, fetch, inputs
        self._open: dict[str, Any] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {}
        for lm in self._live.open_markets(HOURLY_SERIES):
            to_close = lm.market.close_time - now
            if MIN_TO_CLOSE <= to_close <= MAX_TO_CLOSE:
                self._open[kalshi_target(lm.market.ticker)] = lm
        return [entry_for(lm, FAMILY, self.cadence) for lm in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        bars = self._inputs.bars(now)
        if not bars:
            return None
        sigma_h = hourly_sigma(bars)
        if sigma_h is None:
            return None
        mu = bars[-1][1]
        minutes = max((lm.market.close_time - now).total_seconds() / 60.0, 1.0)
        sigma = sigma_h * math.sqrt(minutes / 60.0)
        return Forecast(self.name, self.version, entry.target,
                        hourly_prob(lm.market, mu, sigma), market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "spot": mu, "sigma_hour": round(sigma_h, 3),
                                 "sigma": round(sigma, 3), "minutes_to_close": round(minutes, 1),
                                 "anchor": "CL=F last 5m close; settles on the Pyth WTI index candle"})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


def build_oil_hourly(live, fetch: Callable[[str], Any] = fetch_market,
                     inputs: HourlyInputs | None = None) -> list:
    inputs = inputs or HourlyInputs()
    return [OilHourly(live, fetch, inputs),
            KalshiImplied(FAMILY, (HOURLY_SERIES,), "hourly", live, fetch, lead=MAX_TO_CLOSE)]
