"""Previous-runs hindcasts (Open-Meteo): what a model forecast for past days,
as it forecast them at the time -- the fitting signal for ens-v2's per-station
bias/kernel (phase-3 §3.2).

Only ECMWF IFS 0.25 previous runs are actually served (the GFS member of the
endpoint answers with nulls, verified 2026-11-01), so the pairs are
(ECMWF day value, station actual). That is an approximation of the pooled
ensemble's bias -- station exposure/siting effects dominate model-family
differences -- and ens-v2's payload says so; the paired grades judge whether
the transfer helps. Days are GMT calendar days on both sides of the pair
(the ACIS climate day and the GMT day differ by hours; the fitted bias
absorbs the systematic part of that window shift).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from tradehub.backtest.http import default_get_json

HISTORY_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
MODEL = "ecmwf_ifs025"
PAST_DAYS = 45


def fetch_hindcast(lat: float, lon: float, get_json: Callable[..., Any] = default_get_json,
                   past_days: int = PAST_DAYS) -> dict[str, Any]:
    return get_json(HISTORY_URL, {"latitude": lat, "longitude": lon, "hourly": "temperature_2m",
                                  "models": MODEL, "temperature_unit": "fahrenheit",
                                  "timezone": "GMT", "past_days": past_days, "forecast_days": 1})


def parse_day_values(payload: dict[str, Any]) -> dict[date, dict[str, float]]:
    """{GMT day: {"high": max, "low": min}} from the hourly previous-run series."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get(f"temperature_2m_{MODEL}") or []
    days: dict[date, dict[str, float]] = {}
    for t, v in zip(times, temps, strict=False):
        if v is None:
            continue
        day = date.fromisoformat(str(t)[:10])
        cur = days.setdefault(day, {"high": v, "low": v})
        cur["high"] = max(cur["high"], v)
        cur["low"] = min(cur["low"], v)
    return days
