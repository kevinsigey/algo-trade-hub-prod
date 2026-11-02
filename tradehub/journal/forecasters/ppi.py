"""PPI YoY through the journal: the monthly KXUSPPIYOY level model.

Unlike the other macro series, the event ticker carries the *release date*
(KXUSPPIYOY-26NOV13 for the mid-November release), and the reference month is
the month that release reports. History is ALFRED first prints of the
final-demand index (PPIFIS), snapshot at month-ends -- each month's print is
the newest observation in the following month-end vintage.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.alfred_vintages import fetch_vintages
from tradehub.data.labor_inputs import cache_dir_from_env
from tradehub.engines.labor import add_months, first_prints, month_end
from tradehub.engines.ppi_yoy import (
    PPI_RESOLUTION,
    PPI_SERIES,
    fit_ppi_model,
    ppi_mu_sigma,
    ppi_pairs,
    ppi_prob,
)
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
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
from tradehub.markets import event_date, prob_in_interval, yes_interval

ET = ZoneInfo("America/New_York")
PPI_TRAIN_START = date(2019, 1, 1)
VERSION = "ppi-yoy-v1"


def _month_ends(start: date, end: date) -> list[date]:
    out, m = [], date(start.year, start.month, 1)
    while m <= end:
        out.append(month_end(m))
        m = add_months(m, 1)
    return out


class PpiData:
    """PPI final-demand first prints -> YoY series, fetched once per ET day."""

    def __init__(self, fetch: Callable[..., dict] = fetch_vintages):
        self._fetch = fetch
        self._memo: dict[date, list[tuple[date, float]]] = {}

    def yoy(self, now: datetime) -> list[tuple[date, float]]:
        """[(reference month, YoY %)] ascending, from first-print levels."""
        today = now.astimezone(ET).date()
        if today not in self._memo:
            vintages = self._fetch("PPIFIS", _month_ends(PPI_TRAIN_START, today),
                                   cache_dir=cache_dir_from_env(), today=today)
            levels = first_prints(vintages, change=False)
            series = []
            for month in sorted(levels):
                year_ago = add_months(month, -12)
                if year_ago in levels and levels[year_ago] > 0:
                    series.append((month, (levels[month] / levels[year_ago] - 1.0) * 100.0))
            self._memo = {today: series}
        return self._memo[today]


def _ppi_targets(live, data: PpiData, now: datetime, lead: timedelta = FREEZE_LEAD):
    """Open KXUSPPIYOY markets inside the freeze lead whose reference month's
    predecessor has already printed (the payrolls adjacency rule, on release
    dates instead of reference months)."""
    series = data.yoy(now)
    if len(series) < 3:
        return {}
    last_month = series[-1][0]
    out = {}
    for lm in live.open_markets(PPI_SERIES):
        if not in_freeze_window(lm, now, lead):
            continue
        try:
            release = event_date(lm.market.event_ticker)
        except ValueError:
            continue
        reference = add_months(date(release.year, release.month, 1), -1)
        if add_months(reference, -1) == last_month:
            out[kalshi_target(lm.market.ticker)] = (lm, series)
    return out


class PpiForecaster:
    name = "ppi_nowcast"
    version = VERSION
    cadence = "monthly"

    def __init__(self, live, fetch_market: Callable[[str], Any], data: PpiData, *,
                 lead: timedelta = FREEZE_LEAD):
        self._live, self._fetch_market, self._data, self._lead = live, fetch_market, data, lead
        self._open: dict = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = _ppi_targets(self._live, self._data, now, self._lead)
        return [entry_for(lm, "ppi", self.cadence) for lm, _ in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        if entry.target not in self._open:
            return None
        lm, series = self._open[entry.target]
        values = [v for _, v in series]
        model = fit_ppi_model(ppi_pairs(values))
        if model is None:
            return None
        mu, sigma = ppi_mu_sigma(values, model)
        return Forecast(self.name, self.version, entry.target,
                        ppi_prob(lm.market, mu, sigma), market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "mu": round(mu, 2), "sigma": round(sigma, 3),
                                 "last": round(values[-1], 2), "n_train": model.n_train})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class PpiPersistence:
    """The naive monthly benchmark: next YoY = last YoY, change-stdev sigma."""

    name = "baseline_persistence_ppi"
    version = VERSION
    cadence = "monthly"

    def __init__(self, live, fetch_market: Callable[[str], Any], data: PpiData, *,
                 lead: timedelta = FREEZE_LEAD):
        self._live, self._fetch_market, self._data, self._lead = live, fetch_market, data, lead
        self._open: dict = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = _ppi_targets(self._live, self._data, now, self._lead)
        return [entry_for(lm, "ppi", self.cadence) for lm, _ in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        if entry.target not in self._open:
            return None
        lm, series = self._open[entry.target]
        values = [v for _, v in series]
        changes = [b - a for a, b in zip(values, values[1:])]
        if len(changes) < 20:
            return None
        mean = sum(changes) / len(changes)
        sigma = max((sum((c - mean) ** 2 for c in changes) / (len(changes) - 1)) ** 0.5, 0.05)
        return Forecast(self.name, self.version, entry.target,
                        prob_in_interval(values[-1], sigma,
                                         yes_interval(lm.market, PPI_RESOLUTION)),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "mu": round(values[-1], 2), "sigma": round(sigma, 3)})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


def build_ppi(live, fetch: Callable[[str], Any] = fetch_market, data: PpiData | None = None) -> list:
    """Monthly PPI YoY (macro audit: medium add, built after oil/claims/U3):
    the fitted level model, the market itself and persistence."""
    data = data or PpiData()
    return [
        PpiForecaster(live, fetch, data),
        KalshiImplied("ppi", (PPI_SERIES,), "monthly", live, fetch),
        PpiPersistence(live, fetch, data),
    ]
