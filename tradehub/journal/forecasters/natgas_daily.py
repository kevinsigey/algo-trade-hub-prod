"""Kalshi daily natural gas (KXNATGASD), graded against the market and a persistence baseline.

The market settles on the Pyth NATGAS index at 5:00 PM Eastern. The model
(`natgas_daily`, `natgas-v1`) prices each strike as a Normal centred on the live
NG=F print with the trailing daily sigma of Kalshi's own settled values, scaled
by sqrt(time-to-close) -- the hourly WTI engine's construction at a daily grain
(`engines/natgas_daily.py` carries the reasoning and the futures-vs-index basis
caveat). Beside it the journal grades the Kalshi mid on the same contract
(`KalshiImplied`) and a persistence baseline: the last settled day's value as
the level, with the same daily sigma stretched over the span since that
settlement. The registry adds the w25 market-shrunk row (`natgas_daily_cautious`)
from day one, the house pattern for new families.

Not in v1, deliberately: EIA weekly storage (the release-day fundamental --
it needs a free EIA API key, Kevin's to register, and it moves the weekly
level more than the last two hours of a day) and the degree-day weather tilt
(`/cache/degree-days.json` exists). Either earns its place as a separate
shadow row graded against v1, never folded into it silently.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.natgas import natgas_last_price
from tradehub.engines.natgas_daily import (
    DECISION_LEAD,
    GAS_RESOLUTION,
    SERIES,
    daily_changes,
    daily_sigma,
    event_time,
    natgas_prob,
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

FAMILY = "natgas_daily"
VERSION = "natgas-v1"
LEAD = DECISION_LEAD
MIN_CHANGES = 20          # three trading weeks of daily changes before the model speaks
RECENT_EVENTS = 150       # settled events to pull per run (the sigma reads the last 60 changes)
MAX_PRICE_AGE = timedelta(minutes=30)


class DailyInputs:
    """Kalshi's settled daily values and the live NG=F print, loaded once per run
    (keyed on `now`, the hourly oil inputs' rule)."""

    def __init__(self, live, *, price_fn: Callable[[], Any] = natgas_last_price):
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


class _DailyBase:
    cadence = "daily"

    def __init__(self, live, fetch: Callable[[str], Any], inputs: DailyInputs):
        self._live, self._fetch_market, self._inputs = live, fetch, inputs
        self._open: dict[str, Any] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for lm in self._live.open_markets(SERIES)
                      if in_freeze_window(lm, now, LEAD)}
        return [entry_for(lm, FAMILY, self.cadence) for lm in self._open.values()]

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class NatgasDaily(_DailyBase):
    name, version = "natgas_daily", VERSION

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        changes = daily_changes(self._inputs.settled(now))
        if len(changes) < MIN_CHANGES:
            return None
        price = self._inputs.price(now)
        if price is None or now - price.published_at > MAX_PRICE_AGE:
            return None  # no live anchor: a gap, never a stale price dressed as live
        minutes = (lm.market.close_time - now).total_seconds() / 60.0
        sigma_d = daily_sigma(changes)
        return Forecast(self.name, self.version, entry.target,
                        natgas_prob(lm.market, price.value, sigma_d, minutes),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "live_price": price.value,
                                 "price_at": price.published_at.isoformat(),
                                 "sigma_d": sigma_d, "sigma_eff": sigma_for(sigma_d, minutes),
                                 "minutes_to_close": round(minutes, 1),
                                 "changes_used": min(len(changes), 60)})


class NatgasDailyPersistence(_DailyBase):
    version = "v1"

    def __init__(self, live, fetch, inputs):
        super().__init__(live, fetch, inputs)
        self.name = baseline_name(PERSISTENCE, FAMILY)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        settled = self._inputs.settled(now)
        changes = daily_changes(settled)
        if len(changes) < MIN_CHANGES:
            return None
        last = max(settled, key=lambda o: event_time(o.name))
        span_minutes = (lm.market.close_time - event_time(last.name)).total_seconds() / 60.0
        if span_minutes < 60:
            return None
        sigma = sigma_for(daily_sigma(changes), span_minutes)
        return Forecast(self.name, self.version, entry.target,
                        prob_in_interval(last.value, sigma, yes_interval(lm.market, GAS_RESOLUTION)),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "last_settlement": last.value,
                                 "last_settlement_event": last.name,
                                 "span_minutes": round(span_minutes, 1), "sigma": sigma,
                                 "basis": "last settled day's value as the level, trailing "
                                          "daily sigma stretched over the span since it"})


def build_natgas_daily(live, fetch: Callable[[str], Any] = fetch_market,
                       inputs: DailyInputs | None = None) -> list:
    inputs = inputs or DailyInputs(live)
    return [NatgasDaily(live, fetch, inputs),
            KalshiImplied(FAMILY, (SERIES,), "daily", live, fetch, lead=LEAD),
            NatgasDailyPersistence(live, fetch, inputs)]
