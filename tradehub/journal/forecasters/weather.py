"""Kalshi daily weather markets (highs, lows, rain), forecast from NOAA and ECMWF ensembles.

For each open market inside the journal's 24h freeze window, the forecast is the share of ensemble members
that land in the market's YES range: each member's climate-day high or low is smoothed by a fixed Normal
kernel (KERNEL_SIGMA, set before any result was seen; a different value is a new version), and rain is the
share of members with a reportable total. Beside it the journal grades the Kalshi mid on the same contract
(KalshiImplied) and a climatology baseline from the station's own history, the same week in past years.
All three settle on Kalshi's result.

ponytail: no bias correction or fitted spread; ens-v1 is the raw ensemble. Fit both walk-forward from
journal results (a new version) once a few hundred contracts have settled.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from tradehub.backtest.http import default_get_json
from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.acis import fetch_station, parse_station
from tradehub.data.ensemble import MODELS, day_members, fetch_ensemble, parse_members
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.forecasters.baselines import CLIMATOLOGY, baseline_name
from tradehub.journal.kalshi_linked import (
    KalshiImplied,
    entry_for,
    in_freeze_window,
    kalshi_target,
    quote_mid,
    quote_payload,
    settle_on_kalshi,
)
from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

VERSION = "ens-v1"
KERNEL_SIGMA = 2.0       # degrees F
RAIN_MEASURABLE = 0.005  # inches; reported to 0.01, and a trace settles NO
CLIMATOLOGY_YEARS = 30
CLIMATOLOGY_WINDOW = 7   # days either side of the target date
TEMP_RESOLUTION = 1.0
# Freeze only in the first hours of the climate day. Later, part of the day has already been observed and
# the ensemble is "forecasting" a high or low that may already have happened, so a late freeze is a gap.
MIN_LEAD = timedelta(hours=20)

# Series with traded markets on 2026-10-08, and the station each one's rules name (verified from the
# market rules text). KXRAIN is one series across many cities: the station is the ticker suffix,
# except where Kalshi's city code differs from the station id.
STATIONS: dict[str, tuple[str, str]] = {
    "KXHIGHNY": ("high", "NYC"), "KXHIGHLAX": ("high", "LAX"), "KXHIGHPHIL": ("high", "PHL"),
    "KXHIGHTNOLA": ("high", "MSY"),
    "KXLOWTAUS": ("low", "AUS"), "KXLOWTOKC": ("low", "OKC"), "KXLOWTATL": ("low", "ATL"),
    "KXLOWTDEN": ("low", "DEN"), "KXLOWTEWR": ("low", "EWR"), "KXLOWTSDF": ("low", "SDF"),
}
RAIN_SERIES = "KXRAIN"
RAIN_STATION = {"SATX": "SAT", "PHIL": "PHL", "NOLA": "MSY", "MIN": "MSP", "LV": "LAS", "DC": "DCA",
                "DAL": "DFW", "CHI": "ORD"}
KINDS = ("high", "low", "rain")


def series_for(kind: str) -> tuple[str, ...]:
    return (RAIN_SERIES,) if kind == "rain" else tuple(s for s, (k, _sid) in STATIONS.items() if k == kind)


def station_for(market: KalshiMarket) -> str | None:
    if market.series_ticker == RAIN_SERIES:
        suffix = market.ticker.rsplit("-", 1)[-1]
        return RAIN_STATION.get(suffix, suffix)
    found = STATIONS.get(market.series_ticker)
    return found[1] if found else None


def _shrunk_share(hits: int, n: int) -> float:
    """(k + 1/2) / (n + 1): a share that is never exactly 0 or 1, so one surprise cannot cost a Brier of 1."""
    return (hits + 0.5) / (n + 1)


def ensemble_prob(market: KalshiMarket, kind: str, members: list[float], *,
                  sigma: float = KERNEL_SIGMA, bias: float = 0.0) -> float:
    """Member-share with a Normal kernel. ens-v1 calls this with the defaults
    (fixed 2.0F kernel, no bias -- the values set before any result was seen);
    ens-v2 passes its fitted per-station (bias, sigma). Rain is a threshold
    share and takes neither."""
    if kind == "rain":
        return _shrunk_share(sum(v >= RAIN_MEASURABLE for v in members), len(members))
    interval = yes_interval(market, TEMP_RESOLUTION)
    return statistics.fmean(prob_in_interval(v + bias, sigma, interval) for v in members)


def climatology_prob(market: KalshiMarket, kind: str, days: dict[date, dict[str, float | None]],
                     target: date) -> float | None:
    """The share of past years' days within +/-CLIMATOLOGY_WINDOW of the target's date that were YES."""
    lo, hi = (0.0, float("inf")) if kind == "rain" else yes_interval(market, TEMP_RESOLUTION)
    hits = n = 0
    for back in range(1, CLIMATOLOGY_YEARS + 1):
        try:
            centre = target.replace(year=target.year - back)
        except ValueError:  # Feb 29
            centre = target.replace(year=target.year - back, day=28)
        for shift in range(-CLIMATOLOGY_WINDOW, CLIMATOLOGY_WINDOW + 1):
            value = (days.get(centre + timedelta(days=shift)) or {}).get(kind)
            if value is None:
                continue
            n += 1
            hits += value >= RAIN_MEASURABLE if kind == "rain" else lo < value < hi
    return _shrunk_share(hits, n) if n else None


def target_day(market: KalshiMarket) -> date:
    return datetime.strptime(market.event_ticker.split("-")[1], "%y%b%d").replace(tzinfo=UTC).date()


class WeatherInputs:
    """Station history and ensembles, each fetched at most once per station per process (one journal run)."""

    def __init__(self, get_json: Callable[..., Any] | None = default_get_json):
        self._get_json = get_json
        self._stations: dict[str, tuple[float, float, dict]] = {}
        self._ensembles: dict[str, Any] = {}
        self._ensembles_v2: dict[str, Any] = {}
        self._hindcasts: dict[str, dict] = {}

    def _fetch_station(self, sid: str, start: date, end: date) -> dict[str, Any]:
        return fetch_station(sid, start, end, self._get_json)

    def _fetch_ensemble(self, lat: float, lon: float) -> dict[str, Any]:
        return fetch_ensemble(lat, lon, self._get_json)

    def members_v2(self, sid: str, today: date):
        """ens-v2's wider, model-tagged ensemble (MODELS_V2), cached apart
        from ens-v1's -- the two versions never share a member pool."""
        if sid not in self._ensembles_v2:
            lat, lon, _days = self.station(sid, today)
            from tradehub.data.ensemble import MODELS_V2, fetch_ensemble as _fetch_v2, parse_members_tagged
            self._ensembles_v2[sid] = parse_members_tagged(
                _fetch_v2(lat, lon, self._get_json, models=MODELS_V2))
        return self._ensembles_v2[sid]

    def hindcast(self, sid: str, today: date) -> dict[date, dict[str, float]]:
        """Previous-runs day values for the station (ens-v2's fitting signal),
        fetched at most once per station per process."""
        if sid not in self._hindcasts:
            lat, lon, _days = self.station(sid, today)
            from tradehub.data.hindcast import fetch_hindcast, parse_day_values
            try:
                self._hindcasts[sid] = parse_day_values(fetch_hindcast(lat, lon, self._get_json))
            except Exception:  # noqa: BLE001 - a failed hindcast read fits nothing, never crashes the run
                self._hindcasts[sid] = {}
        return self._hindcasts[sid]

    def station(self, sid: str, today: date) -> tuple[float, float, dict]:
        if sid not in self._stations:
            start = today.replace(year=today.year - CLIMATOLOGY_YEARS - 1)
            self._stations[sid] = parse_station(self._fetch_station(sid, start, today))
        return self._stations[sid]

    def members(self, sid: str, today: date):
        if sid not in self._ensembles:
            lat, lon, _days = self.station(sid, today)
            self._ensembles[sid] = parse_members(self._fetch_ensemble(lat, lon))
        return self._ensembles[sid]


class _WeatherBase:
    cadence = "daily"

    def __init__(self, kind: str, live, fetch: Callable[[str], Any], inputs: WeatherInputs):
        if kind not in KINDS:
            raise ValueError(f"unknown weather kind {kind!r}")
        self.kind, self._live, self._fetch_market, self._inputs = kind, live, fetch, inputs
        self.family = f"weather_{kind}"
        self._open: dict[str, Any] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for s in series_for(self.kind)
                      for lm in self._live.open_markets(s)
                      if in_freeze_window(lm, now) and lm.market.close_time - now >= MIN_LEAD
                      and station_for(lm.market)}
        return [entry_for(lm, self.family, self.cadence) for lm in self._open.values()]

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class WeatherEnsemble(_WeatherBase):
    version = VERSION

    def __init__(self, kind, live, fetch, inputs):
        super().__init__(kind, live, fetch, inputs)
        self.name = self.family

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        sid = station_for(lm.market)
        values = day_members(self._inputs.members(sid, now.date()), lm.market.close_time, self.kind)
        if not values:
            return None
        mkt = lm.market
        return Forecast(self.name, self.version, entry.target, ensemble_prob(lm.market, self.kind, values),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "station": sid, "n_members": len(values),
                                 "ensemble_mean": round(statistics.fmean(values), 3), "models": list(MODELS),
                                 "kernel_sigma": KERNEL_SIGMA,
                                 "strike_type": mkt.strike_type,
                                 "floor_strike": mkt.floor_strike,
                                 "cap_strike": mkt.cap_strike,
                                 "yes_sub_title": mkt.yes_sub_title,
                                 "no_sub_title": mkt.no_sub_title})


def ensemble_prob_by_model(market: KalshiMarket, kind: str, by_model: dict[str, list[float]], *,
                           sigma: float = KERNEL_SIGMA, bias: float = 0.0) -> float:
    """ens-v2's probability: each MODEL's member-share first, then the mean
    across models -- equal weight per model family, never per headcount
    (pooled, ECMWF's 51 members would outvote GEFS's 31 and ICON's 40).
    Rain: the weighted share, shrunk with the total member count as v1 does."""
    if kind == "rain":
        shares, total = [], 0
        for values in by_model.values():
            if values:
                shares.append(sum(v >= RAIN_MEASURABLE for v in values) / len(values))
                total += len(values)
        if not shares or not total:
            return 0.5
        share = statistics.fmean(shares)
        return (share * total + 0.5) / (total + 1)  # _shrunk_share's form, on the weighted share
    interval = yes_interval(market, TEMP_RESOLUTION)
    per_model = [statistics.fmean(prob_in_interval(v + bias, sigma, interval) for v in values)
                 for values in by_model.values() if values]
    return statistics.fmean(per_model)


FIT_WINDOW_DAYS = 60
FIT_MIN_PAIRS = 20  # mirrors engines.weather.MIN_ERROR_PAIRS: below it, no fit is claimed


def fit_station_error(inputs: WeatherInputs, sid: str, kind: str, today: date):
    """(ErrorModel, n_pairs) for one station+kind, fit walk-forward: pairs are
    (ECMWF previous-run day value, ACIS actual) for days strictly before
    `today`, newest FIT_WINDOW_DAYS of them. Below FIT_MIN_PAIRS the fallback
    is exactly ens-v1's parameters (bias 0, kernel 2.0), so an unfitted
    station's v2 freeze equals its v1 freeze and the payload says unfitted."""
    from tradehub.engines.weather import ErrorModel, fit_error_model
    if kind == "rain":
        return ErrorModel(0.0, KERNEL_SIGMA), 0
    _lat, _lon, days = inputs.station(sid, today)
    hind = inputs.hindcast(sid, today)
    dated = []
    for day, hv in hind.items():
        if day >= today:
            continue
        actual = (days.get(day) or {}).get(kind)
        if actual is not None and hv.get(kind) is not None:
            dated.append((day, hv[kind], actual))
    dated.sort()
    pairs = [(fc, actual) for _day, fc, actual in dated[-FIT_WINDOW_DAYS:]]
    return fit_error_model(pairs, min_pairs=FIT_MIN_PAIRS,
                           fallback=ErrorModel(0.0, KERNEL_SIGMA)), len(pairs)


class WeatherEnsembleV2(_WeatherBase):
    """ens-v2 (phase-3 §3.2): ens-v1's member-share machinery with (step 1) a
    fitted per-station bias and kernel width instead of the fixed
    pre-results 2.0F kernel and no correction, and (step 2) a wider shelf
    (GEFS 0.25 + ECMWF IFS + ICON EPS) weighted equally per MODEL rather
    than pooled by headcount. Freezes beside ens-v1 under its own version;
    the fitted parameters and pair count ride in the payload, and a station
    under the pair floor freezes with v1's parameters and fitted=false.
    Rain's bias/kernel treatment is §3.2's later step (per-city rework)."""

    version = "ens-v2"

    def __init__(self, kind, live, fetch, inputs):
        super().__init__(kind, live, fetch, inputs)
        self.name = self.family

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        sid = station_for(lm.market)
        from tradehub.data.ensemble import MODELS_V2, day_members_by_model
        by_model = day_members_by_model(self._inputs.members_v2(sid, now.date()),
                                        lm.market.close_time, self.kind)
        values = [v for vs in by_model.values() for v in vs]
        if not values:
            return None
        mkt = lm.market
        error, n_pairs = fit_station_error(self._inputs, sid, self.kind, now.date())
        fitted = n_pairs >= FIT_MIN_PAIRS and self.kind != "rain"
        prob = ensemble_prob_by_model(mkt, self.kind, by_model,
                                      sigma=error.sigma if fitted else KERNEL_SIGMA,
                                      bias=error.bias if fitted else 0.0)
        return Forecast(self.name, self.version, entry.target, prob,
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "station": sid, "n_members": len(values),
                                 "ensemble_mean": round(statistics.fmean(values), 3),
                                 "models": list(MODELS_V2), "weighting": "equal_per_model",
                                 "members_by_model": {m: len(vs) for m, vs in by_model.items()},
                                 "kernel_sigma": error.sigma if fitted else KERNEL_SIGMA,
                                 "bias": error.bias if fitted else 0.0,
                                 "fit_pairs": n_pairs, "fitted": fitted,
                                 "fit_source": "ecmwf previous-runs vs ACIS actuals",
                                 "strike_type": mkt.strike_type,
                                 "floor_strike": mkt.floor_strike,
                                 "cap_strike": mkt.cap_strike,
                                 "yes_sub_title": mkt.yes_sub_title,
                                 "no_sub_title": mkt.no_sub_title})


class WeatherClimatology(_WeatherBase):
    version = "v1"

    def __init__(self, kind, live, fetch, inputs):
        super().__init__(kind, live, fetch, inputs)
        self.name = baseline_name(CLIMATOLOGY, self.family)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        sid = station_for(lm.market)
        _lat, _lon, days = self._inputs.station(sid, now.date())
        prob = climatology_prob(lm.market, self.kind, days, target_day(lm.market))
        if prob is None:
            return None
        mkt = lm.market
        return Forecast(self.name, self.version, entry.target, prob, market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "station": sid, "years": CLIMATOLOGY_YEARS,
                                 "window_days": CLIMATOLOGY_WINDOW,
                                 "strike_type": mkt.strike_type,
                                 "floor_strike": mkt.floor_strike,
                                 "cap_strike": mkt.cap_strike,
                                 "yes_sub_title": mkt.yes_sub_title,
                                 "no_sub_title": mkt.no_sub_title})


def build_weather(live, fetch: Callable[[str], Any] = fetch_market, inputs: WeatherInputs | None = None) -> list:
    inputs = inputs or WeatherInputs()
    out: list = []
    for kind in KINDS:
        out += [WeatherEnsemble(kind, live, fetch, inputs),
                WeatherEnsembleV2(kind, live, fetch, inputs),
                KalshiImplied(f"weather_{kind}", series_for(kind), "daily", live, fetch,
                              keep=lambda lm: station_for(lm.market) is not None),
                WeatherClimatology(kind, live, fetch, inputs)]
    return out
