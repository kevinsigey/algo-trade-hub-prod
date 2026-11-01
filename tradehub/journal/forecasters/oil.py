"""Kalshi daily WTI crude (KXWTI), graded against the market and a persistence baseline.

The market settles on the day's ICE WTI settlement (~14:30 ET). The model (`oil_wti`,
`wti-v1`) is the oil engine's regression of the per-day settlement change on the CL=F 5-close
change, fit and applied at the same decision time (close minus the 2h lead), anchored on the
last Kalshi settlement -- Kalshi's own settled values are the settlement history, the same
arrangement as gas's AAA prints. Beside it the journal grades the Kalshi mid on the same
contract (`KalshiImplied`) and a persistence baseline (`baseline_persistence_oil`): the last
settlement as the level, with the sigma of past per-day settlement changes. The registry adds
the w25 market-shrunk row (`oil_wti_cautious`) from day one -- the row gas never got.

Built on the 2026-11-01 audit's evidence: KXWTI is open and liquid (the settled Oct 30 event
traded 223,133 contracts) and Yahoo CL=F matched its settlement to the cent, keyless.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.wti import wti_closes
from tradehub.engines.oil import (
    OIL_DECISION_LEAD,
    OIL_SERIES,
    MIN_OIL_SIGMA,
    OilModel,
    fit_oil_model,
    oil_prob,
    oil_training_pairs,
    settlement_daily_changes,
    wti_change,
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
from tradehub.markets import KalshiMarket, event_date

FAMILY = "oil"
SERIES = OIL_SERIES
VERSION = "wti-v1"
LEAD = OIL_DECISION_LEAD
MIN_TRAIN = 30


def target_day(market: KalshiMarket) -> date:
    return event_date(market.event_ticker)


class OilInputs:
    """Kalshi's settled KXWTI values and the CL=F closes, loaded once per run (keyed on
    `now`, the gas inputs' rule: a cache that outlives a run could freeze off a settlement
    that is not out yet)."""

    def __init__(self, live, *, closes_fn: Callable[[], list] = wti_closes):
        self._live, self._closes_fn = live, closes_fn
        self._now: datetime | None = None
        self._settled: list = []
        self._closes: list = []

    def _refresh(self, now: datetime) -> None:
        if now == self._now:
            return
        self._now = now
        self._settled = [o for o in self._live.settled_values(SERIES) if o.published_at <= now]
        self._closes = self._closes_fn()

    def settled(self, now: datetime) -> list:
        self._refresh(now)
        return self._settled

    def closes(self, now: datetime) -> list:
        self._refresh(now)
        return self._closes


class _OilBase:
    cadence = "daily"

    def __init__(self, live, fetch: Callable[[str], Any], inputs: OilInputs):
        self._live, self._fetch_market, self._inputs = live, fetch, inputs
        self._open: dict[str, Any] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for lm in self._live.open_markets(SERIES)
                      if in_freeze_window(lm, now, LEAD)}
        return [entry_for(lm, self.name, self.cadence) for lm in self._open.values()]

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class OilWti(_OilBase):
    name, version = "oil_wti", VERSION

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        settled = self._inputs.settled(now)
        if len(settled) < MIN_TRAIN:
            return None
        day = target_day(lm.market)
        last = max(settled, key=lambda o: event_date(o.name))
        horizon = (day - event_date(last.name)).days
        if horizon < 1:
            return None
        closes = self._inputs.closes(now)
        model = fit_oil_model(
            [(x, y) for x, y, published in oil_training_pairs(settled, closes, lead=LEAD)
             if published <= now],
            settlements=settled,
        )
        x = wti_change(closes, now)
        return Forecast(self.name, self.version, entry.target,
                        oil_prob(lm.market, last.value, horizon, x, model),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "last_settlement": last.value,
                                 "last_settlement_event": last.name, "horizon_days": horizon,
                                 "cl_change_5": x, "alpha": model.alpha, "beta": model.beta,
                                 "sigma": model.sigma})


class OilPersistence(_OilBase):
    version = "v1"

    def __init__(self, live, fetch, inputs):
        super().__init__(live, fetch, inputs)
        self.name = baseline_name(PERSISTENCE, FAMILY)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        settled = self._inputs.settled(now)
        if len(settled) < MIN_TRAIN:
            return None
        day = target_day(lm.market)
        last = max(settled, key=lambda o: event_date(o.name))
        horizon = (day - event_date(last.name)).days
        if horizon < 1:
            return None
        sigma = max(MIN_OIL_SIGMA, statistics.stdev(settlement_daily_changes(settled)))
        return Forecast(self.name, self.version, entry.target,
                        oil_prob(lm.market, last.value, horizon, None, OilModel(0.0, 0.0, sigma)),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "last_settlement": last.value,
                                 "horizon_days": horizon, "sigma": sigma,
                                 "basis": "last KXWTI settlement as the level, sigma of past "
                                          "per-day settlement changes"})


def build_oil(live, fetch: Callable[[str], Any] = fetch_market, inputs: OilInputs | None = None) -> list:
    inputs = inputs or OilInputs(live)
    return [OilWti(live, fetch, inputs),
            KalshiImplied(FAMILY, (SERIES,), "daily", live, fetch, lead=LEAD),
            OilPersistence(live, fetch, inputs)]
