"""Kalshi hourly WTI crude (KXWTIH), graded against the market and a persistence baseline.

The market settles on the close of the 1-minute WTI candlestick at the top of the hour
(Pyth WTI). The model (`oil_wti_hourly`, `wti-hourly-v1`) prices each strike as a Normal
centred on the live CL=F price with the trailing hourly sigma of Kalshi's own settled
values, scaled by sqrt(time-to-close) -- the engine in `engines/oil_hourly.py` carries the
reasoning. Beside it the journal grades the Kalshi mid on the same contract
(`KalshiImplied`) and a persistence baseline (`baseline_persistence_oil_hourly`): the last
settled hour's value as the level, with the same hourly sigma stretched over the span
since that settlement. The registry adds the w25 market-shrunk row
(`oil_wti_hourly_cautious`) from day one, the daily oil row's precedent.

There is no Brent hourly series and no 15-minute oil series on Kalshi (the 15-minute
ladders are crypto-only), so this is the intraday oil build; Brent exists only as daily /
weekly / monthly ladders. Settled values come through `settled_values_recent`: the series
settles ~30 markets an event, and the full-history pull would grow without bound.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.wti import wti_last_price
from tradehub.engines.oil import OIL_RESOLUTION
from tradehub.engines.oil_hourly import (
    HOURLY_DECISION_LEAD,
    HOURLY_SERIES,
    event_hour,
    hourly_changes,
    hourly_prob,
    hourly_sigma,
    sigma_for,
)
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.forecasters.baselines import PERSISTENCE, baseline_name
from tradehub.journal.kalshi_linked import (
    KalshiImplied,
    entry_for,
    in_freeze_window,
    kalshi_target,
    quote_mid,
    quote_payload,
    settle_on_kalshi,
)
from tradehub.markets import prob_in_interval, yes_interval

FAMILY = "oil_hourly"
SERIES = HOURLY_SERIES
VERSION = "wti-hourly-v1"
LEAD = HOURLY_DECISION_LEAD
MIN_CHANGES = 24          # a full trading day of hourly changes before the model speaks
RECENT_EVENTS = 120       # settled events to pull per run (the sigma reads the last 72 changes)
MAX_PRICE_AGE = timedelta(minutes=15)


class HourlyInputs:
    """Kalshi's settled hourly values and the live CL=F print, loaded once per run
    (keyed on `now`, the daily oil inputs' rule)."""

    def __init__(self, live, *, price_fn: Callable[[], Any] = wti_last_price):
        self._live, self._price_fn = live, price_fn
        self._now: datetime | None = None
        self._settled: list = []
        self._price = None

    def _refresh(self, now: datetime) -> None:
        if now == self._now:
            return
        self._now = now
        recent = getattr(self._live, "settled_values_recent", None)
        values = (recent(SERIES, RECENT_EVENTS) if callable(recent)
                  else self._live.settled_values(SERIES))
        self._settled = [o for o in values if o.published_at <= now]
        self._price = self._price_fn()

    def settled(self, now: datetime) -> list:
        self._refresh(now)
        return self._settled

    def price(self, now: datetime):
        self._refresh(now)
        return self._price


class _HourlyBase:
    cadence = "hourly"

    def __init__(self, live, fetch: Callable[[str], Any], inputs: HourlyInputs):
        self._live, self._fetch_market, self._inputs = live, fetch, inputs
        self._open: dict[str, Any] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for lm in self._live.open_markets(SERIES)
                      if in_freeze_window(lm, now, LEAD)}
        return [entry_for(lm, FAMILY, self.cadence) for lm in self._open.values()]

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class OilWtiHourly(_HourlyBase):
    name, version = "oil_wti_hourly", VERSION

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        return self._forecast(entry, now)

    def _forecast(self, entry: CalendarEntry, now: datetime, *,
                  sigma_mult: float = 1.0, extra: dict | None = None) -> Forecast | None:
        """The v1 math, with an optional sigma multiplier and payload extras
        -- the geo shadow variant (oil_geo.py) reuses it so the two rows
        differ ONLY by the widening, which is what makes their paired
        grading meaningful."""
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        changes = hourly_changes(self._inputs.settled(now))
        if len(changes) < MIN_CHANGES:
            return None
        price = self._inputs.price(now)
        if price is None or now - price.published_at > MAX_PRICE_AGE:
            return None  # no live anchor: a gap, never a stale price dressed as live
        minutes = (lm.market.close_time - now).total_seconds() / 60.0
        sigma_h = hourly_sigma(changes) * sigma_mult
        return Forecast(self.name, self.version, entry.target,
                        hourly_prob(lm.market, price.value, sigma_h, minutes),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "live_price": price.value,
                                 "price_at": price.published_at.isoformat(),
                                 "sigma_h": sigma_h, "sigma_eff": sigma_for(sigma_h, minutes),
                                 "minutes_to_close": round(minutes, 1),
                                 "changes_used": min(len(changes), 72), **(extra or {})})


class OilHourlyPersistence(_HourlyBase):
    version = "v1"

    def __init__(self, live, fetch, inputs):
        super().__init__(live, fetch, inputs)
        self.name = baseline_name(PERSISTENCE, FAMILY)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        settled = self._inputs.settled(now)
        changes = hourly_changes(settled)
        if len(changes) < MIN_CHANGES:
            return None
        last = max(settled, key=lambda o: event_hour(o.name))
        span_minutes = (lm.market.close_time - event_hour(last.name)).total_seconds() / 60.0
        if span_minutes < 60:
            return None
        sigma_h = hourly_sigma(changes)
        sigma = sigma_for(sigma_h, span_minutes)
        return Forecast(self.name, self.version, entry.target,
                        prob_in_interval(last.value, sigma, yes_interval(lm.market, OIL_RESOLUTION)),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "last_settlement": last.value,
                                 "last_settlement_event": last.name,
                                 "span_minutes": round(span_minutes, 1), "sigma": sigma,
                                 "basis": "last settled hour's value as the level, trailing "
                                          "hourly sigma stretched over the span since it"})


def build_oil_hourly(live, fetch: Callable[[str], Any] = fetch_market,
                     inputs: HourlyInputs | None = None) -> list:
    inputs = inputs or HourlyInputs(live)
    return [OilWtiHourly(live, fetch, inputs),
            KalshiImplied(FAMILY, (SERIES,), "hourly", live, fetch, lead=LEAD),
            OilHourlyPersistence(live, fetch, inputs)]
