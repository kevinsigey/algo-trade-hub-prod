"""Ensemble weather forecasts from Open-Meteo (NOAA GEFS 0.5 and ECMWF IFS 0.25), keyless.

One request returns every member's hourly temperature and precipitation, in UTC. A member's value for a
Kalshi market is its max, min or total over the market's climate day, which is the 24 hours ending at the
market's close (Kalshi closes each daily weather market at midnight local standard time).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from tradehub.backtest.http import default_get_json

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
MODELS = ("gfs05", "ecmwf_ifs025")
# ens-v2's shelf (phase-3 §3.2 step 2): GEFS at 0.25° plus ICON EPS beside
# ECMWF. GEM answers with a single control run (verified 2026-11-01), which
# is not an ensemble, so it is not on the shelf. ens-v1 keeps MODELS -- its
# member pool is part of its frozen definition.
MODELS_V2 = ("gfs025", "ecmwf_ifs025", "icon_seamless")
CLIMATE_DAY = timedelta(hours=24)
Members = list[tuple[list[datetime], list[float | None], list[float | None]]]
TaggedMembers = list[tuple[str, list[datetime], list[float | None], list[float | None]]]


def fetch_ensemble(lat: float, lon: float, get_json: Callable[..., Any] = default_get_json,
                   models: tuple[str, ...] = MODELS) -> dict[str, Any]:
    return get_json(ENSEMBLE_URL, {"latitude": lat, "longitude": lon, "hourly": "temperature_2m,precipitation",
                                   "models": ",".join(models), "temperature_unit": "fahrenheit",
                                   "precipitation_unit": "inch", "timezone": "GMT", "forecast_days": 3})


def _model_tag(key: str) -> str:
    """The model family of a member column: temperature_2m_member01_ecmwf_ifs025_ensemble
    -> ecmwf_ifs025_ensemble; the control column carries no memberNN_ prefix."""
    s = key.removeprefix("temperature_2m_")
    if s.startswith("member"):
        s = s.split("_", 1)[1] if "_" in s else s
    return s


def parse_members_tagged(payload: dict[str, Any]) -> TaggedMembers:
    """[(model, hours, temperatures, precipitation)] per member, control runs included."""
    hourly = payload.get("hourly") or {}
    times = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in hourly.get("time") or []]
    out = []
    for key in hourly:
        if key.startswith("temperature_2m_"):
            rain = hourly.get("precipitation_" + key.removeprefix("temperature_2m_")) or [None] * len(times)
            out.append((_model_tag(key), times, hourly[key], rain))
    return out


def parse_members(payload: dict[str, Any]) -> Members:
    """[(hours, temperatures, precipitation)] per member, control runs included."""
    return [(times, temps, rain) for _model, times, temps, rain in parse_members_tagged(payload)]


def day_members_by_model(members: TaggedMembers, close: datetime, kind: str) -> dict[str, list[float]]:
    """day_members, grouped by model family -- the input to ens-v2's
    equal-per-model weighting (a 51-member model must not outvote a
    31-member one just by headcount)."""
    out: dict[str, list[float]] = {}
    for model, times, temps, rains in members:
        series = rains if kind == "rain" else temps
        start = close - CLIMATE_DAY
        values = [v for t, v in zip(times, series, strict=True) if start < t <= close and v is not None]
        if not values:
            continue
        out.setdefault(model, []).append(
            sum(values) if kind == "rain" else max(values) if kind == "high" else min(values))
    return out


def day_members(members: Members, close: datetime, kind: str) -> list[float]:
    """Each member's high, low or rain total over (close - 24h, close]; members with no data drop out."""
    start = close - CLIMATE_DAY
    out = []
    for times, temps, rains in members:
        series = rains if kind == "rain" else temps
        values = [v for t, v in zip(times, series, strict=True) if start < t <= close and v is not None]
        if not values:
            continue
        out.append(sum(values) if kind == "rain" else max(values) if kind == "high" else min(values))
    return out
