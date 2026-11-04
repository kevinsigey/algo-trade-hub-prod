"""The Pyth shadow of the hourly WTI model: `oil_wti_hourly` at `wti-hourly-v3-pyth-shadow`.

One question, on a 14-day API trial: is the 10-minute-old CL=F anchor why the model trails Kalshi? This row
is v1's math with only the anchor changed to the feed Kalshi settles on, so paired grading against v1 and
the market isolates it. A dead or unkeyed feed is a gap, never a stale price. v1 and its record are untouched.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from tradehub.data.pyth import PythUnavailable, pyth_oil_price
from tradehub.journal.forecasters.oil_hourly import HourlyInputs, OilWtiHourly

log = logging.getLogger(__name__)

VERSION = "wti-hourly-v3-pyth-shadow"


def _price_or_none():
    try:
        return pyth_oil_price()
    except PythUnavailable as exc:
        log.warning("oil pyth shadow: %s", exc)
        return None


class OilWtiHourlyPythShadow(OilWtiHourly):
    name, version = "oil_wti_hourly", VERSION


def build_oil_pyth_shadow(live, fetch: Callable[[str], Any] | None = None) -> list:
    from tradehub.core.kalshi_feed import fetch_market

    return [OilWtiHourlyPythShadow(live, fetch or fetch_market, HourlyInputs(live, price_fn=_price_or_none))]
