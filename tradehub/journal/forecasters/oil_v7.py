"""`oil_wti_hourly` at `wti-hourly-v7-rv-shadow`: v4 (the Hyperliquid anchor) with the
spread from 1-minute realised volatility instead of the trailing settled-changes sigma.

Preregistration: docs/superpowers/specs/2026-11-19-oil-hourly-v7-rv-shadow-prereg.md.
The variant differs from v4 ONLY in the sigma source, which is what makes their paired
grading meaningful. v1 and v4 are untouched; a dead or thin tape is no forecast, never
a fallback to the settled-changes sigma.

Amendment (Claude's review of this PR, before the first freeze): v7 scores off the
SAME frozen anchor observation v4 used for the target -- v4's payload `live_price` /
`price_at`, read back from its journal row -- not a second live read taken seconds
later, so the paired Brier compares two sigmas, not two anchors. No v4 row for the
target, no v7 row. And the candle read drops the in-progress minute, the way
`read_window` does: a candle counts only once its minute has fully elapsed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from tradehub.backtest.pit import Observation
from tradehub.data.hyperliquid import HYPERLIQUID_OIL, HyperliquidUnavailable, hyperliquid_candles
from tradehub.engines.oil_hourly import RV_WINDOW, realised_sigma
from tradehub.journal.contract import CalendarEntry, Forecast
from tradehub.journal.forecasters.oil_hl import HL_VERSION, _hl_price_or_none
from tradehub.journal.forecasters.oil_hourly import HourlyInputs, OilWtiHourly

log = logging.getLogger(__name__)

RV_VERSION = "wti-hourly-v7-rv-shadow"


def _hl_candles_or_none(now: datetime):
    try:
        candles = hyperliquid_candles(HYPERLIQUID_OIL, now - RV_WINDOW, now)
    except HyperliquidUnavailable as exc:
        log.warning("oil v7 rv shadow: %s", exc)
        return None
    # The in-progress minute is not a close: a candle counts only once
    # its minute has fully elapsed (read_window's rule).
    return [(t, v) for t, v in candles if t + timedelta(minutes=1) <= now]


def _v4_frozen_anchor(target: str) -> Observation | None:
    """v4's frozen anchor observation for this target, from its journal
    row's payload, or None when v4 has not frozen one -- v7 then has no
    pair to score against and stays a gap."""
    from tradehub.core.supabase_client import get_client
    from tradehub.journal.store import fetch_forecasts

    rows = fetch_forecasts(get_client(), "oil_wti_hourly", HL_VERSION, [target])
    if not rows:
        return None
    payload = rows[0].get("payload") or {}
    value, at = payload.get("live_price"), payload.get("price_at")
    if value is None or at is None:
        return None
    return Observation("xyz:CL", float(value), datetime.fromisoformat(str(at)))


class OilWtiHourlyRvShadow(OilWtiHourly):
    name, version = "oil_wti_hourly", RV_VERSION

    def __init__(self, live, fetch: Callable[[str], Any], inputs: HourlyInputs,
                 candles_fn: Callable[[datetime], Any] = _hl_candles_or_none,
                 anchor_fn: Callable[[str], Any] = _v4_frozen_anchor):
        super().__init__(live, fetch, inputs)
        self._candles_fn = candles_fn
        self._anchor_fn = anchor_fn
        self._rv_extra: dict[str, Any] = {}

    def _anchor(self, entry: CalendarEntry, now: datetime):
        return self._anchor_fn(entry.target)

    def _sigma(self, entry: CalendarEntry, now: datetime) -> tuple[float, int] | None:
        try:
            candles = self._candles_fn(now)
        except HyperliquidUnavailable:
            return None  # a dead feed is a gap (the default reader already logs it)
        if not candles:
            return None
        rv = realised_sigma(candles)
        if rv is None:
            return None  # thin tape: a gap, never a fallback to v4's sigma
        sigma_h, diffs_used, sigma_1m = rv
        self._rv_extra = {"sigma_source": "rv_1m_24h",
                          "rv_diffs_used": diffs_used,
                          "rv_sigma_1m": sigma_1m}
        return sigma_h, diffs_used

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        self._rv_extra = {}
        fc = self._forecast(entry, now)
        if fc is None:
            return None
        payload = {k: v for k, v in fc.payload.items() if k != "changes_used"}
        payload.update(self._rv_extra)
        payload["anchor_source"] = "v4_frozen"
        return replace(fc, payload=payload)


def build_oil_v7_shadow(live, fetch: Callable[[str], Any] | None = None) -> list:
    from tradehub.core.kalshi_feed import fetch_market

    return [OilWtiHourlyRvShadow(live, fetch or fetch_market,
                                 HourlyInputs(live, price_fn=_hl_price_or_none))]
