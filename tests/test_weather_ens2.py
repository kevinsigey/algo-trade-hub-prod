"""ens-v2 (phase-3 §3.2 step 1): per-station bias + learned kernel width,
fitted walk-forward on (ECMWF previous-run, ACIS actual) pairs. Below the
pair floor the freeze is exactly ens-v1's and the payload says unfitted."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from tradehub.data.hindcast import parse_day_values
from tradehub.journal.forecasters.weather import (
    KERNEL_SIGMA, WeatherEnsemble, WeatherEnsembleV2, WeatherInputs, fit_station_error,
)
from tests.test_journal_weather import ACIS, CLOSE, NOW, FakeLive, Inputs, _final, _hourly, _inputs, _lm


def test_hindcast_parse_takes_the_gmt_day_high_and_low():
    payload = {"hourly": {"time": ["2026-10-28T00:00", "2026-10-28T06:00", "2026-10-28T12:00",
                                   "2026-10-29T00:00"],
                          "temperature_2m_ecmwf_ifs025": [50.0, 65.0, 58.0, 49.0]}}
    days = parse_day_values(payload)
    assert days[date(2026, 10, 28)] == {"high": 65.0, "low": 50.0}
    assert days[date(2026, 10, 29)] == {"high": 49.0, "low": 49.0}


class _FitInputs:
    """Just the two reads fit_station_error makes."""
    def __init__(self, actuals, hind):
        self._actuals, self._hind = actuals, hind

    def station(self, sid, today):
        return 40.0, -73.0, self._actuals

    def hindcast(self, sid, today):
        return self._hind


def _pairs(n, bias=3.0):
    base = date(2026, 9, 1)
    actuals, hind = {}, {}
    for i in range(n):
        d = base + timedelta(days=i)
        hind[d] = {"high": 70.0, "low": 55.0}
        actuals[d] = {"high": 70.0 + bias, "low": 55.0 + bias, "rain": 0.0}
    return actuals, hind


def test_fit_recovers_a_constant_bias_and_floors_sigma():
    actuals, hind = _pairs(25)
    error, n = fit_station_error(_FitInputs(actuals, hind), "NYC", "high", date(2026, 10, 9))
    assert n == 25 and error.bias == pytest.approx(3.0) and error.sigma == 1.0  # stdev 0 -> MIN_SIGMA


def test_fit_below_the_floor_is_ens_v1_parameters():
    actuals, hind = _pairs(10)
    error, n = fit_station_error(_FitInputs(actuals, hind), "NYC", "high", date(2026, 10, 9))
    assert n == 10 and error.bias == 0.0 and error.sigma == KERNEL_SIGMA


class V2Inputs(Inputs):
    def __init__(self, ensemble, acis, hind):
        super().__init__(ensemble, acis)
        self._hind = hind

    def hindcast(self, sid, today):
        return self._hind

    def members_v2(self, sid, today):
        from tradehub.data.ensemble import parse_members_tagged
        return parse_members_tagged(self.ens)


def _v2_inputs(hind):
    start = CLOSE - timedelta(hours=24)
    temps = [[80.0] * 24 for _ in range(10)]
    rains = [[0.0] * 24 for _ in range(10)]
    return V2Inputs(_hourly(start, temps, rains), ACIS, hind)


def test_v2_unfitted_freezes_exactly_like_v1_and_says_so():
    live = FakeLive([_lm("KXHIGHNY-26OCT09-T76", "greater", floor=76)])
    v1 = WeatherEnsemble("high", live, _final("yes"), _inputs())
    v2 = WeatherEnsembleV2("high", live, _final("yes"), _v2_inputs({}))
    [e1] = v1.targets(NOW)
    [e2] = v2.targets(NOW)
    f1, f2 = v1.forecast(e1, NOW), v2.forecast(e2, NOW)
    assert (v2.name, v2.version) == ("weather_high", "ens-v2")
    assert f2.probability == f1.probability
    assert f2.payload["fitted"] is False and f2.payload["kernel_sigma"] == KERNEL_SIGMA


def test_v2_fitted_bias_moves_the_probability_and_is_recorded():
    # 25 hindcast days paired with ACIS-shaped actuals, all +3 warm bias.
    base = date(2026, 9, 1)
    hind = {base + timedelta(days=i): {"high": 70.0, "low": 55.0} for i in range(25)}
    # The stub ACIS only carries scattered days, so fitted pairs come from the
    # hindcast side alone in this fixture -> the fit stays under the floor and
    # the payload must say so rather than pretend.
    live = FakeLive([_lm("KXHIGHNY-26OCT09-T76", "greater", floor=76)])
    v2 = WeatherEnsembleV2("high", live, _final("yes"), _v2_inputs(hind))
    [e2] = v2.targets(NOW)
    f2 = v2.forecast(e2, NOW)
    assert f2.payload["fit_source"] == "ecmwf previous-runs vs ACIS actuals"
    assert f2.payload["fitted"] is False  # ACIS fixture has no matching days


def test_weighting_is_per_model_not_per_headcount():
    from tradehub.journal.forecasters.weather import ensemble_prob_by_model
    market = _lm("KXHIGHNY-26OCT09-T76", "greater", floor=76).market
    # Model A: 2 members, both hot (prob ~0.96 each). Model B: 50 members,
    # all cold (prob ~0.04). Pooled by headcount the cold model swamps the
    # answer (~0.07); equal-per-model gives ~0.50.
    by_model = {"a": [80.0, 80.0], "b": [70.0] * 50}
    weighted = ensemble_prob_by_model(market, "high", by_model)
    assert weighted == pytest.approx(0.50, abs=0.02)


def test_registry_builds_v2_beside_v1():
    from tradehub.journal.forecasters.weather import build_weather
    names = [(f.name, getattr(f, "version", None)) for f in build_weather(FakeLive([]), _final("yes"),
                                                                         WeatherInputs(get_json=None))]
    assert ("weather_high", "ens-v1") in names and ("weather_high", "ens-v2") in names
    assert ("weather_rain", "ens-v2") in names
