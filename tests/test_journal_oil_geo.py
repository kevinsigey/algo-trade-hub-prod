"""The geo shadow variant of the hourly WTI model: stress scoring is pure
and conservative (a silent feed never widens), and the forecast differs
from v1 only by the widened sigma."""
from datetime import timedelta

from tests.test_journal_oil_hourly import NOW, FakeLive, _lm
from tradehub.backtest.pit import Observation
from tradehub.journal.forecasters.oil_geo import (
    OilWtiHourlyGeoShadow,
    k_for_score,
    stress_from_rows,
)
from tradehub.journal.forecasters.oil_hourly import HourlyInputs, OilWtiHourly


def _rows(gate=10, jam=0.05, mil=1, health="live"):
    return [
        {"feed": "ais", "metric": "tankers_gate_entries_1h", "value": gate, "health": health},
        {"feed": "adsb_jamming", "metric": "jamming_intraday", "value": jam, "health": health},
        {"feed": "adsb", "metric": "mil_total", "value": mil, "health": health},
    ]


def _history():
    rows = []
    for v in (9, 10, 11, 10, 12):
        rows.append({"feed": "ais", "metric": "tankers_gate_entries_1h", "value": v})
    for v in (0.02, 0.03, 0.04, 0.05, 0.06, 0.03, 0.04, 0.05, 0.02, 0.06, 0.04):
        rows.append({"feed": "adsb_jamming", "metric": "jamming_intraday", "value": v})
    for v in (1, 1, 2, 1, 0):
        rows.append({"feed": "adsb", "metric": "mil_total", "value": v})
    return rows


def test_stress_scoring_fires_and_stays_quiet():
    score, contrib, partial = stress_from_rows(_rows(gate=10, jam=0.03, mil=1), _history())
    assert score == 0 and partial is False
    score, contrib, partial = stress_from_rows(_rows(gate=4, jam=0.09, mil=4), _history())
    assert score == 3
    assert contrib["gate_entries_collapse"]["fired"] is True
    assert k_for_score(0) == 1.0 and k_for_score(1) == 1.25 and k_for_score(3) == 1.5


def test_silent_feed_contributes_zero_and_marks_partial():
    rows = _rows(gate=0, health="live")
    rows[0] = {"feed": "ais", "metric": "tankers_gate_entries_1h", "value": 0, "health": "unknown"}
    score, contrib, partial = stress_from_rows(rows, _history())
    assert contrib["gate_entries_collapse"] == "unavailable"
    assert partial is True


def _forecast(cls, provider=None, strike=102):
    live = FakeLive([_lm(strike)])
    obs = Observation("WTI:CL=F:last", 101.2, NOW - timedelta(minutes=2))
    inputs = HourlyInputs(live, price_fn=lambda: obs)
    f = (cls(live, lambda t: None, inputs, provider) if cls is OilWtiHourlyGeoShadow
         else cls(live, lambda t: None, inputs))
    return f.forecast(f.targets(NOW)[0], NOW)


def test_shadow_with_no_stress_matches_v1_probability():
    calm = lambda now: (_rows(), _history())  # noqa: E731
    v1 = _forecast(OilWtiHourly)
    shadow = _forecast(OilWtiHourlyGeoShadow, calm)
    assert shadow is not None and v1 is not None
    assert shadow.probability == v1.probability
    assert shadow.payload["geo_k"] == 1.0 and shadow.payload["geo_partial"] is False
    assert shadow.forecaster_version == "wti-hourly-v2-geo-shadow"


def test_shadow_under_stress_widens_toward_a_coin_flip():
    stressed = lambda now: (_rows(gate=2, jam=0.09, mil=5), _history())  # noqa: E731
    v1 = _forecast(OilWtiHourly, strike=101.5)
    shadow = _forecast(OilWtiHourlyGeoShadow, stressed, strike=101.5)
    assert shadow.payload["geo_k"] == 1.5
    assert abs(shadow.probability - 0.5) < abs(v1.probability - 0.5)


def test_provider_failure_degrades_to_v1_stamped():
    def boom(now):
        raise RuntimeError("geo table unreachable")

    v1 = _forecast(OilWtiHourly)
    shadow = _forecast(OilWtiHourlyGeoShadow, boom)
    assert shadow.probability == v1.probability
    assert shadow.payload["geo_partial"] is True
