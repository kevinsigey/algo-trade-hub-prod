"""The degree-day demand panel (phase-2 §5.3): HDD/CDD at the 65F base, the
10-year same-window normal, population weighting, and the missing-data honesty
(a region without its week is omitted and named, never zero-filled)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from tradehub.weather_demand import REGIONS, compute_panel, hdd_cdd, weekly_stats

END = date(2026, 1, 14)  # a Wednesday in heating season


def _series(daily_temp: float, years: int = 11, end: date = END) -> pd.Series:
    days = pd.date_range(end=end, periods=365 * years, freq="D")
    return pd.Series([daily_temp] * len(days), index=days, name="tavg")


def test_hdd_cdd_at_the_65f_base():
    assert hdd_cdd(45.0) == (20.0, 0.0)
    assert hdd_cdd(85.0) == (0.0, 20.0)
    assert hdd_cdd(65.0) == (0.0, 0.0)


def test_weekly_stats_read_a_cold_week_against_its_normal():
    warm_history = _series(50.0)                       # every prior day: HDD 15/day
    cold_week = warm_history.copy()
    cold_week[cold_week.index > pd.Timestamp(END - timedelta(days=7))] = 30.0  # HDD 35/day
    stats = weekly_stats(cold_week, END)
    assert stats is not None
    assert stats["hdd"] == pytest.approx(35.0 * 7)
    assert stats["hdd_normal"] == pytest.approx(15.0 * 7)
    assert stats["hdd_anomaly"] == pytest.approx(20.0 * 7)
    assert stats["hdd_z"] is None  # identical years -> zero spread -> no z, not inf
    assert stats["cdd"] == 0.0 and stats["normal_years"] == 10


def test_weekly_stats_refuses_a_partial_week():
    short = _series(50.0).iloc[-4:]
    assert weekly_stats(short, END) is None


def test_the_panel_weights_by_population_and_names_missing_regions():
    city_series = {}
    for region in REGIONS.values():
        for name, *_ in region["cities"]:
            city_series[name] = _series(50.0)
    panel = compute_panel(city_series, END)
    assert panel["missing_regions"] == []
    assert panel["national"]["hdd"] == pytest.approx(15.0 * 7)
    assert panel["national"]["hdd_anomaly"] == pytest.approx(0.0)
    assert panel["national"]["population_covered_pct"] == 100.0

    del city_series["Boston"], city_series["Hartford"]  # all of New England's cities gone
    panel = compute_panel(city_series, END)
    assert panel["missing_regions"] == ["New England"]
    assert "New England" not in panel["regions"]
    assert panel["national"]["population_covered_pct"] < 100.0


def test_fetch_parses_the_archive_payload(monkeypatch):
    from tradehub.weather_demand import fetch_city_temps
    payload = {"daily": {"time": ["2026-01-12", "2026-01-13", "2026-01-14"],
                         "temperature_2m_mean": [40.0, None, 44.0]}}
    series = fetch_city_temps("Boston", 42.36, -71.06, date(2026, 1, 1), date(2026, 1, 31),
                              get_json=lambda url: payload)
    assert series.tolist() == [40.0, 44.0]  # the null day is dropped, not zero-filled
    assert list(series.index) == list(pd.to_datetime(["2026-01-12", "2026-01-14"]))
