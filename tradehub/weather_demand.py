"""Degree-day demand panel (phase-2 §5.3, Oct 12 plan module B): weather turned
into gas demand, served as a panel inside the Weather page.

The chain it feeds is the one the engines already trade on: degree-day surprise ->
EIA storage surprise -> Henry Hub. This module computes the first link and nothing
more: per Census division, the last 7 completed days' heating/cooling degree days
(base 65F, the EIA standard) against the same calendar window's 10-year normal,
plus the national population-weighted index -- weather multiplied by people, which
is what makes it a demand signal rather than a temperature map.

Shape of the build: a weekly script (scripts/degree_days.py) fetches Open-Meteo
archive daily mean temperatures for each division's representative cities (one
request per city for the full 10+ years, cached), computes the panel through the
pure functions here, and writes a snapshot JSON. The API serves the file; it never
computes. A missing snapshot is a 503 with the reason, never invented zeros.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

BASE_F = 65.0
WEEK_DAYS = 7
NORMAL_YEARS = 10

SNAPSHOT_ENV = "TRADEHUB_DEGREE_DAYS_FILE"
DEFAULT_SNAPSHOT = "/cache/degree-days.json"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Census divisions: representative cities (the population centres that carry the
# division's demand) and 2020 Census population shares. Shares are normalised in
# the weighting, so rounding here does not bias the index.
REGIONS: dict[str, dict[str, Any]] = {
    "New England": {"share": 4.53, "cities": [("Boston", 42.36, -71.06), ("Hartford", 41.76, -72.67)]},
    "Middle Atlantic": {"share": 12.48, "cities": [("New York", 40.71, -74.01), ("Philadelphia", 39.95, -75.17),
                                                   ("Pittsburgh", 40.44, -79.99)]},
    "East North Central": {"share": 14.13, "cities": [("Chicago", 41.88, -87.63), ("Detroit", 42.33, -83.05),
                                                      ("Columbus", 39.96, -82.99)]},
    "West North Central": {"share": 6.42, "cities": [("Minneapolis", 44.98, -93.27), ("Kansas City", 39.10, -94.58),
                                                     ("Omaha", 41.26, -95.93)]},
    "South Atlantic": {"share": 19.68, "cities": [("Atlanta", 33.75, -84.39), ("Charlotte", 35.23, -80.84),
                                                  ("Jacksonville", 30.33, -81.66)]},
    "East South Central": {"share": 5.77, "cities": [("Nashville", 36.16, -86.78), ("Birmingham", 33.52, -86.80),
                                                     ("Louisville", 38.25, -85.76)]},
    "West South Central": {"share": 12.25, "cities": [("Dallas", 32.78, -96.80), ("Houston", 29.76, -95.37),
                                                      ("Oklahoma City", 35.47, -97.52)]},
    "Mountain": {"share": 7.47, "cities": [("Denver", 39.74, -104.99), ("Phoenix", 33.45, -112.07),
                                           ("Salt Lake City", 40.76, -111.89)]},
    "Pacific": {"share": 15.93, "cities": [("Los Angeles", 34.05, -118.24), ("Seattle", 47.61, -122.33),
                                           ("Portland", 45.52, -122.68)]},
}


def hdd_cdd(tavg_f: float) -> tuple[float, float]:
    """One day's heating and cooling degree days at the 65F base."""
    return max(0.0, BASE_F - tavg_f), max(0.0, tavg_f - BASE_F)


def _window(series: pd.Series, end: date, days: int = WEEK_DAYS) -> pd.Series:
    return series[(series.index > pd.Timestamp(end - timedelta(days=days))) & (series.index <= pd.Timestamp(end))]


def _shift_year(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # Feb 29 -> Feb 28 in a non-leap year
        return day.replace(year=day.year - years, day=28)


def weekly_stats(series: pd.Series, end: date) -> dict[str, Any] | None:
    """HDD/CDD for the 7 days ending `end`, their 10-year same-window normals, the
    anomaly, and its z against the spread of those 10 years. None when the current
    window is incomplete -- a partial week is not a measurement."""
    now = _window(series, end)
    if len(now) < WEEK_DAYS:
        return None
    hdd_now = float(sum(hdd_cdd(v)[0] for v in now))
    cdd_now = float(sum(hdd_cdd(v)[1] for v in now))
    hdd_years, cdd_years = [], []
    for k in range(1, NORMAL_YEARS + 1):
        past = _window(series, _shift_year(end, k))
        if len(past) < WEEK_DAYS:
            continue
        hdd_years.append(float(sum(hdd_cdd(v)[0] for v in past)))
        cdd_years.append(float(sum(hdd_cdd(v)[1] for v in past)))
    if len(hdd_years) < 5:
        return {"hdd": hdd_now, "cdd": cdd_now, "hdd_normal": None, "cdd_normal": None,
                "hdd_anomaly": None, "cdd_anomaly": None, "hdd_z": None, "cdd_z": None,
                "normal_years": len(hdd_years)}

    def stats(value: float, years: list[float]) -> tuple[float, float, float | None]:
        s = pd.Series(years)
        normal, std = float(s.mean()), float(s.std(ddof=1))
        return normal, value - normal, ((value - normal) / std if std > 0 else None)

    hdd_normal, hdd_anom, hdd_z = stats(hdd_now, hdd_years)
    cdd_normal, cdd_anom, cdd_z = stats(cdd_now, cdd_years)
    return {"hdd": hdd_now, "cdd": cdd_now, "hdd_normal": hdd_normal, "cdd_normal": cdd_normal,
            "hdd_anomaly": hdd_anom, "cdd_anomaly": cdd_anom, "hdd_z": hdd_z, "cdd_z": cdd_z,
            "normal_years": len(hdd_years)}


def compute_panel(city_series: dict[str, pd.Series], end: date) -> dict[str, Any]:
    """The snapshot body from per-city daily mean temps. A region whose cities lack
    the current week is omitted (named in `missing`), never zero-filled; the
    national index weights the regions that ARE present and says how much of the
    country's population they cover."""
    regions: dict[str, Any] = {}
    missing: list[str] = []
    total_share = sum(r["share"] for r in REGIONS.values())
    covered, nat = 0.0, {"hdd": 0.0, "cdd": 0.0, "hdd_anomaly": 0.0, "cdd_anomaly": 0.0}
    anomalies_known = True
    for name, region in REGIONS.items():
        per_city = [weekly_stats(city_series[c[0]], end) for c in region["cities"] if c[0] in city_series]
        per_city = [s for s in per_city if s is not None]
        if not per_city:
            missing.append(name)
            continue

        def mean(key: str) -> float | None:
            vals = [s[key] for s in per_city if s[key] is not None]
            return float(sum(vals) / len(vals)) if vals else None

        row = {key: mean(key) for key in ("hdd", "cdd", "hdd_normal", "cdd_normal",
                                          "hdd_anomaly", "cdd_anomaly", "hdd_z", "cdd_z")}
        row["share"] = region["share"]
        regions[name] = row
        w = region["share"] / total_share
        covered += region["share"]
        nat["hdd"] += w * (row["hdd"] or 0.0)
        nat["cdd"] += w * (row["cdd"] or 0.0)
        if row["hdd_anomaly"] is None or row["cdd_anomaly"] is None:
            anomalies_known = False
        else:
            nat["hdd_anomaly"] += w * row["hdd_anomaly"]
            nat["cdd_anomaly"] += w * row["cdd_anomaly"]
    national = {"hdd": round(nat["hdd"], 1), "cdd": round(nat["cdd"], 1),
                "hdd_anomaly": round(nat["hdd_anomaly"], 1) if anomalies_known else None,
                "cdd_anomaly": round(nat["cdd_anomaly"], 1) if anomalies_known else None,
                "population_covered_pct": round(100 * covered / total_share, 1)}
    return {"week_end": end.isoformat(), "national": national, "regions": regions, "missing_regions": missing}


def fetch_city_temps(name: str, lat: float, lon: float, start: date, end: date,
                     *, get_json: Callable[[str], dict] | None = None) -> pd.Series:
    """Daily mean temperature (F) from the Open-Meteo archive -- the endpoint that
    serves history; the forecast endpoint only reaches ~3 months (the repo's own
    weather-model lesson, AGENTS.md 2026-10-04)."""
    url = (f"{ARCHIVE_URL}?latitude={lat}&longitude={lon}&start_date={start.isoformat()}"
           f"&end_date={end.isoformat()}&daily=temperature_2m_mean&temperature_unit=fahrenheit&timezone=UTC")
    if get_json is None:
        import requests
        payload = requests.get(url, timeout=120, headers={"User-Agent": "tradehub/1.0 (degree days)"}).json()
    else:
        payload = get_json(url)
    daily = payload.get("daily") or {}
    times, values = daily.get("time") or [], daily.get("temperature_2m_mean") or []
    series = pd.Series([float(v) for v in values if v is not None],
                       index=pd.to_datetime([t for t, v in zip(times, values) if v is not None]).normalize(),
                       name=name, dtype=float)
    return series.sort_index()


def build_snapshot(*, today: date | None = None, fetch: Callable[..., pd.Series] = fetch_city_temps,
                   cache_dir: Path | None = None) -> dict[str, Any]:
    """Fetch (or read back) every city's history and compute the panel for the last
    completed week. City histories are cached as CSVs under the degree-days cache:
    a weekly job refetches only the tail by simply re-pulling -- the archive is
    cheap at one request per city, and the cache makes a rerun free."""
    today = today or date.today()
    end = today - timedelta(days=1)  # the last COMPLETED day
    start = _shift_year(end, NORMAL_YEARS + 1)
    root = cache_dir if cache_dir is not None else Path(os.environ.get("TRADEHUB_DEGREE_DAYS_CACHE") or "/cache/degree-days")
    city_series: dict[str, pd.Series] = {}
    for region in REGIONS.values():
        for name, lat, lon in region["cities"]:
            cached = root / f"{name.replace(' ', '_')}.csv"
            series = None
            if cached.is_file() and date.fromtimestamp(cached.stat().st_mtime) >= end:
                series = pd.read_csv(cached, index_col=0, parse_dates=True)["tavg"]
            if series is None:
                series = fetch(name, lat, lon, start, end)
                try:
                    root.mkdir(parents=True, exist_ok=True)
                    series.rename("tavg").to_csv(cached)
                except OSError:
                    pass
            city_series[name] = series
    panel = compute_panel(city_series, end)
    panel["as_of"] = today.isoformat()
    panel["source"] = "open-meteo archive, daily mean temperature; base 65F; 2020 Census division shares"
    return panel


def snapshot_path() -> Path:
    return Path(os.environ.get(SNAPSHOT_ENV) or DEFAULT_SNAPSHOT)


def read_snapshot(path: Path | None = None) -> dict[str, Any] | None:
    try:
        return json.loads((path or snapshot_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
