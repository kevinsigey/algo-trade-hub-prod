"""Jobless claims through the journal: the weekly KXJOBLESSCLAIMS level model.

History is ALFRED first prints of ICSA, snapshot at every Thursday in the
window (the DOL release day; a shifted holiday release reads through the next
Thursday's vintage instead). `ClaimsData` memoizes per ET day, mirroring
`LaborData`; the engine (`tradehub.engines.claims`) is pure.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Callable

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.alfred_vintages import fetch_vintages
from tradehub.data.kalshi_live import LiveMarket
from tradehub.data.labor_inputs import cache_dir_from_env
from tradehub.engines.claims import (
    CLAIMS_RESOLUTION,
    CLAIMS_SERIES,
    claims_mu_sigma,
    claims_pairs,
    claims_prob,
    fit_claims_model,
)
from tradehub.engines.labor import first_prints
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
CLAIMS_TRAIN_START = date(2023, 1, 1)
VERSION = "claims-v1"


def _thursdays(start: date, end: date) -> list[date]:
    first = start + timedelta(days=(3 - start.weekday()) % 7)  # weekday(): Thu == 3
    out, d = [], first
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


class ClaimsData:
    """ICSA first prints, fetched at most once per ET day."""

    def __init__(self, fetch: Callable[..., dict] = fetch_vintages):
        self._fetch = fetch
        self._memo: dict[date, list[tuple[date, float]]] = {}

    def prints(self, now: datetime) -> list[tuple[date, float]]:
        """[(week-ending Saturday, first print)] ascending."""
        today = now.astimezone(ET).date()
        if today not in self._memo:
            vintages = self._fetch("ICSA", _thursdays(CLAIMS_TRAIN_START, today),
                                   cache_dir=cache_dir_from_env(), today=today)
            self._memo = {today: sorted(first_prints(vintages, change=False).items())}
        return self._memo[today]


def _claims_targets(live, data: ClaimsData, now: datetime,
                    lead: timedelta = FREEZE_LEAD) -> dict[str, tuple[LiveMarket, list[tuple[date, float]]]]:
    """Open claims markets inside the freeze lead whose print history ends with
    the immediately preceding release -- a stale or gapped history forecasts
    nothing, the same honesty rule as the gas/oil last-settlement anchor."""
    prints = data.prints(now)
    if len(prints) < 8:
        return {}
    last_week = prints[-1][0]
    out = {}
    for lm in live.open_markets(CLAIMS_SERIES):
        if not in_freeze_window(lm, now, lead):
            continue
        try:
            release = event_date(lm.market.event_ticker)
        except ValueError:
            continue
        target_week = release - timedelta(days=5)  # the Saturday this release reports
        if timedelta(days=6) <= target_week - last_week <= timedelta(days=8):
            out[kalshi_target(lm.market.ticker)] = (lm, prints)
    return out


class ClaimsForecaster:
    name = "claims_nowcast"
    version = VERSION
    cadence = "weekly"

    def __init__(self, live, fetch_market: Callable[[str], Any], data: ClaimsData, *,
                 lead: timedelta = FREEZE_LEAD):
        self._live, self._fetch_market, self._data, self._lead = live, fetch_market, data, lead
        self._open: dict[str, tuple[LiveMarket, list[tuple[date, float]]]] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = _claims_targets(self._live, self._data, now, self._lead)
        return [entry_for(lm, "claims", self.cadence) for lm, _ in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        if entry.target not in self._open:
            return None
        lm, prints = self._open[entry.target]
        values = [v for _, v in prints]
        model = fit_claims_model(claims_pairs(values))
        if model is None:
            return None
        mu, sigma = claims_mu_sigma(values, model)
        return Forecast(self.name, self.version, entry.target,
                        claims_prob(lm.market, mu, sigma), market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "mu": round(mu), "sigma": round(sigma),
                                 "last": values[-1], "n_train": model.n_train})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class ClaimsPersistence:
    """The naive weekly benchmark: next print = last print, change-stdev sigma."""

    name = "baseline_persistence_claims"
    version = VERSION
    cadence = "weekly"

    def __init__(self, live, fetch_market: Callable[[str], Any], data: ClaimsData, *,
                 lead: timedelta = FREEZE_LEAD):
        self._live, self._fetch_market, self._data, self._lead = live, fetch_market, data, lead
        self._open: dict[str, tuple[LiveMarket, list[tuple[date, float]]]] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = _claims_targets(self._live, self._data, now, self._lead)
        return [entry_for(lm, "claims", self.cadence) for lm, _ in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        if entry.target not in self._open:
            return None
        lm, prints = self._open[entry.target]
        values = [v for _, v in prints]
        changes = [b - a for a, b in zip(values, values[1:])]
        if len(changes) < 20:
            return None
        mean = sum(changes) / len(changes)
        sigma = max((sum((c - mean) ** 2 for c in changes) / (len(changes) - 1)) ** 0.5, 5000.0)
        return Forecast(self.name, self.version, entry.target,
                        prob_in_interval(values[-1], sigma,
                                         yes_interval(lm.market, CLAIMS_RESOLUTION)),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "mu": values[-1], "sigma": round(sigma)})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


def build_claims(live, fetch: Callable[[str], Any] = fetch_market, data: ClaimsData | None = None) -> list:
    """Weekly jobless claims (macro audit, Nov 1): the level model, the market
    itself and persistence, sharing one calendar and one settlement source."""
    data = data or ClaimsData()
    return [
        ClaimsForecaster(live, fetch, data),
        KalshiImplied("claims", (CLAIMS_SERIES,), "weekly", live, fetch),
        ClaimsPersistence(live, fetch, data),
    ]
