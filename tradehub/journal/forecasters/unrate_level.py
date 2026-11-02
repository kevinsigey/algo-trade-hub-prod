"""U3 unemployment level through the journal: the monthly KXU3 level model.

History is the labor stack's own first prints (LaborData inputs, UNRATE
levels), so the level model and the older direction row read the same record;
the level row is the one graded against the market.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from tradehub.core.kalshi_feed import fetch_market
from tradehub.engines.labor import add_months, first_prints, month_end
from tradehub.engines.unrate_level import (
    UNRATE_RESOLUTION,
    UNRATE_SERIES,
    fit_unrate_model,
    unrate_mu_sigma,
    unrate_pairs,
    unrate_prob,
)
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.forecasters.labor import ET, LaborData
from tradehub.journal.kalshi_linked import (
    FREEZE_LEAD,
    KalshiImplied,
    entry_for,
    in_freeze_window,
    kalshi_target,
    quote_mid,
    quote_payload,
    settle_on_kalshi,
)
from tradehub.markets import event_month, prob_in_interval, yes_interval

VERSION = "unrate-level-v1"


def _levels(data: LaborData, now) -> list[tuple]:
    """[(month, first-print U3)] ascending from the shared labor inputs."""
    return sorted(first_prints(data.inputs(now).unrate, change=False).items())


def _u3_targets(live, data: LaborData, now, lead: timedelta = FREEZE_LEAD):
    """Open KXU3 markets inside the freeze lead whose reference month has ended
    and whose immediately preceding month has printed -- the payrolls rule."""
    levels = _levels(data, now)
    if len(levels) < 3:
        return {}
    last_month = levels[-1][0]
    out = {}
    for lm in live.open_markets(UNRATE_SERIES):
        if not in_freeze_window(lm, now, lead):
            continue
        month = event_month(lm.market.event_ticker)
        if month_end(month) < now.astimezone(ET).date() and add_months(month, -1) == last_month:
            out[kalshi_target(lm.market.ticker)] = (lm, levels)
    return out


class UnrateLevelForecaster:
    name = "unrate_nowcast"
    version = VERSION
    cadence = "monthly"

    def __init__(self, live, fetch_market: Callable[[str], Any], data: LaborData, *,
                 lead: timedelta = FREEZE_LEAD):
        self._live, self._fetch_market, self._data, self._lead = live, fetch_market, data, lead
        self._open: dict = {}

    def targets(self, now) -> list[CalendarEntry]:
        self._open = _u3_targets(self._live, self._data, now, self._lead)
        return [entry_for(lm, "labor", self.cadence) for lm, _ in self._open.values()]

    def forecast(self, entry: CalendarEntry, now) -> Forecast | None:
        if entry.target not in self._open:
            return None
        lm, levels = self._open[entry.target]
        values = [v for _, v in levels]
        model = fit_unrate_model(unrate_pairs(values))
        if model is None:
            return None
        mu, sigma = unrate_mu_sigma(values, model)
        return Forecast(self.name, self.version, entry.target,
                        unrate_prob(lm.market, mu, sigma), market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "mu": round(mu, 2), "sigma": round(sigma, 3),
                                 "last": values[-1], "n_train": model.n_train})

    def settle(self, target: str, now) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class UnratePersistence:
    """The naive monthly benchmark: next print = last print, change-stdev sigma."""

    name = "baseline_persistence_unrate"
    version = VERSION
    cadence = "monthly"

    def __init__(self, live, fetch_market: Callable[[str], Any], data: LaborData, *,
                 lead: timedelta = FREEZE_LEAD):
        self._live, self._fetch_market, self._data, self._lead = live, fetch_market, data, lead
        self._open: dict = {}

    def targets(self, now) -> list[CalendarEntry]:
        self._open = _u3_targets(self._live, self._data, now, self._lead)
        return [entry_for(lm, "labor", self.cadence) for lm, _ in self._open.values()]

    def forecast(self, entry: CalendarEntry, now) -> Forecast | None:
        if entry.target not in self._open:
            return None
        lm, levels = self._open[entry.target]
        values = [v for _, v in levels]
        changes = [b - a for a, b in zip(values, values[1:])]
        if len(changes) < 20:
            return None
        mean = sum(changes) / len(changes)
        sigma = max((sum((c - mean) ** 2 for c in changes) / (len(changes) - 1)) ** 0.5, 0.05)
        return Forecast(self.name, self.version, entry.target,
                        prob_in_interval(values[-1], sigma,
                                         yes_interval(lm.market, UNRATE_RESOLUTION)),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "mu": values[-1], "sigma": round(sigma, 3)})

    def settle(self, target: str, now) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


def build_unrate(live, fetch: Callable[[str], Any] = fetch_market, data: LaborData | None = None) -> list:
    """Monthly U3 level (macro audit, Nov 1): the level model, the market itself
    and persistence, sharing the labor calendar and settlements."""
    data = data or LaborData()
    return [
        UnrateLevelForecaster(live, fetch, data),
        KalshiImplied("unrate", (UNRATE_SERIES,), "monthly", live, fetch),
        UnratePersistence(live, fetch, data),
    ]
