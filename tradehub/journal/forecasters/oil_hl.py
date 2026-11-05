"""`oil_wti_hourly` at `wti-hourly-v4-hl-shadow`: v1's math with only the anchor changed from the delayed CL=F
print to the live Hyperliquid perp, so paired grading against v1 and the market isolates what the feed is worth.
A dead feed is a gap, never a stale price. v1 and its record are untouched.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from tradehub.data.hyperliquid import HyperliquidUnavailable, hyperliquid_oil_price
from tradehub.journal.forecasters.oil_hourly import HourlyInputs, OilWtiHourly

log = logging.getLogger(__name__)

HL_VERSION = "wti-hourly-v4-hl-shadow"


def _hl_price_or_none():
    try:
        return hyperliquid_oil_price(datetime.now(UTC))
    except HyperliquidUnavailable as exc:
        log.warning("oil hyperliquid shadow: %s", exc)
        return None


class OilWtiHourlyHlShadow(OilWtiHourly):
    name, version = "oil_wti_hourly", HL_VERSION


def build_oil_hl_shadow(live, fetch: Callable[[str], Any] | None = None) -> list:
    from tradehub.core.kalshi_feed import fetch_market

    return [OilWtiHourlyHlShadow(live, fetch or fetch_market, HourlyInputs(live, price_fn=_hl_price_or_none))]
