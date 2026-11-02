"""NWS National Blend of Models (NBM) via Open-Meteo: the NWS's own
bias-corrected station blend, fetched as a graded reference for the weather
journal (the audit's lever 2: measure it here before blending anything).

Hourly temperature + precipitation probability in GMT, reduced to GMT
calendar days the way the hindcast module reduces previous runs -- the
climate-day window differs by hours and the row is a measurement, not a
dressed model, so no correction is applied or claimed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from tradehub.backtest.http import default_get_json

NBM_URL = "https://api.open-meteo.com/v1/forecast"
NBM_MODEL = "ncep_nbm_conus"


def fetch_nbm(lat: float, lon: float, get_json: Callable[..., Any] = default_get_json) -> dict[str, Any]:
    return get_json(NBM_URL, {"latitude": lat, "longitude": lon,
                              "hourly": "temperature_2m,precipitation_probability",
                              "models": NBM_MODEL, "temperature_unit": "fahrenheit",
                              "timezone": "GMT", "forecast_days": 7})


def parse_nbm_days(payload: dict[str, Any]) -> dict[date, dict[str, float]]:
    """{GMT day: {"high": max temp, "low": min temp, "pop": max PoP %}}."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    pops = hourly.get("precipitation_probability") or []
    days: dict[date, dict[str, float]] = {}
    for t, temp, pop in zip(times, temps, pops, strict=False):
        day = date.fromisoformat(str(t)[:10])
        cur = days.setdefault(day, {"high": temp if temp is not None else -1e9,
                                    "low": temp if temp is not None else 1e9,
                                    "pop": 0.0})
        if temp is not None:
            cur["high"] = max(cur["high"], temp)
            cur["low"] = min(cur["low"], temp)
        if pop is not None:
            cur["pop"] = max(cur["pop"], pop)
    return {d: v for d, v in days.items() if v["high"] > -1e8}
