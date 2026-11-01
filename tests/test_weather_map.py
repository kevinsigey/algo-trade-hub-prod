"""The weather map composition (phase-3 §3.1): per-city summaries from
journal payloads -- latest unsettled freeze batch per kind, every source's
probability per bucket, and a per-station record paired on the same targets."""
from __future__ import annotations

from tradehub.weather_map import build_weather_map


def _f(forecaster, target, prob, station=None, day="2026-11-01", mean=None, floor=None):
    payload = {"station": station, "ensemble_mean": mean, "floor_strike": floor,
               "cap_strike": (floor + 1) if floor is not None else None,
               "yes_sub_title": f"{floor} to {floor + 1} degrees" if floor is not None else None}
    return {"forecaster": forecaster, "forecaster_version": "ens-v1", "target": target,
            "probability": prob, "frozen_at": f"{day}T06:00:00Z", "payload": payload}


FORECASTS = [
    # NYC highs, two buckets, frozen today (unsettled)
    _f("weather_high", "T72", 0.42, "NYC", mean=72.4, floor=72),
    _f("weather_high", "T73", 0.30, "NYC", mean=72.4, floor=73),
    _f("kalshi_implied_weather_high", "T72", 0.38),
    _f("baseline_climatology_weather_high", "T72", 0.20),
    # an older batch for the same station must not leak into the card
    _f("weather_high", "T99", 0.99, "NYC", day="2026-10-30", mean=60.0, floor=61),
    # NYC settled pair for the record
    _f("weather_high", "T50", 0.80, "NYC", day="2026-10-20"),
    _f("kalshi_implied_weather_high", "T50", 0.60),
    # Chicago rain, unsettled
    _f("weather_rain", "RAINCHI", 0.35, "ORD"),
    _f("kalshi_implied_weather_rain", "RAINCHI", 0.30),
]
SETTLEMENTS = {"T50": 1, "T99": 0}


def test_map_groups_latest_batch_buckets_with_all_three_sources():
    cities = {c["sid"]: c for c in build_weather_map(forecasts=FORECASTS, settlements=SETTLEMENTS)["cities"]}
    nyc = cities["NYC"]
    assert nyc["name"] == "New York" and nyc["lat"] == 40.779
    high = nyc["high"]
    assert high["day"] == "2026-11-01" and high["mean"] == 72.4 and high["version"] == "ens-v1"
    assert high["buckets"][0] == {"label": "72 to 73 degrees", "ours": 0.42, "market": 0.38, "clim": 0.20}
    assert len(high["buckets"]) == 2  # the settled Oct 30 batch (T99) is not a bucket


def test_station_record_pairs_ensemble_against_market_on_the_same_targets():
    cities = {c["sid"]: c for c in build_weather_map(forecasts=FORECASTS, settlements=SETTLEMENTS)["cities"]}
    rec = cities["NYC"]["record"]
    assert rec["n"] == 1
    assert abs(rec["brier_ours"] - 0.04) < 1e-9 and abs(rec["brier_market"] - 0.16) < 1e-9


def test_rain_only_city_appears_and_unforecast_stations_do_not():
    cities = {c["sid"]: c for c in build_weather_map(forecasts=FORECASTS, settlements=SETTLEMENTS)["cities"]}
    assert cities["ORD"]["rain"]["buckets"][0]["ours"] == 0.35
    assert "DEN" not in cities  # no forecasts, no record -> no marker
