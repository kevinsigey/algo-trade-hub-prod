"""Daily station observations from NOAA's Applied Climate Information System (ACIS), keyless.

Kalshi's daily weather markets name an NWS climate station (CLINYC, CLIAUS, ...) and settle on its reported
high, low or precipitation. ACIS serves the same station's daily record back decades, plus its coordinates.
Checked 2026-10-08 against 3,996 settled Kalshi markets (highs, lows, rain): ACIS reproduced every outcome,
with a trace of rain ("T") settling NO, so trace is read as 0.0.

ACIS stopped resolving the CLI-prefixed ids sometime after that check (verified 2026-11-01: CLINYC and
CLILAX return {"error": "no data available"} while the bare climate codes NYC / LAX return the same
stations), so fetch_station maps CLIxxx -> xxx before asking. An ACIS error payload raises instead of
flowing into parse_station, where it used to surface as an opaque KeyError: 'meta' that killed every
weather forecaster with targets due.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from tradehub.backtest.http import default_get_json

ACIS_URL = "https://data.rcc-acis.org/StnData"
FIELDS = ("high", "low", "rain")


def _value(raw: str) -> float | None:
    if raw == "T":
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):  # "M" (missing), "S"/"A" flags
        return None


def parse_station(payload: dict[str, Any]) -> tuple[float, float, dict[date, dict[str, float | None]]]:
    """(latitude, longitude, {day: {high, low, rain}}) from an ACIS StnData response."""
    lon, lat = payload["meta"]["ll"]
    days = {date.fromisoformat(row[0]): {f: _value(v) for f, v in zip(FIELDS, row[1:], strict=True)}
            for row in payload.get("data") or []}
    return lat, lon, days


def acis_sid(sid: str) -> str:
    """The sid ACIS resolves today: Kalshi's CLI-prefixed climate ids by their bare code (CLINYC -> NYC)."""
    if sid.startswith("CLI") and len(sid) == 6 and sid[3:].isalpha():
        return sid[3:]
    return sid


def fetch_station(sid: str, start: date, end: date, get_json: Callable[..., Any] = default_get_json) -> dict[str, Any]:
    payload = get_json(ACIS_URL, {"sid": acis_sid(sid), "sdate": start.isoformat(), "edate": end.isoformat(),
                                  "elems": "maxt,mint,pcpn", "output": "json"})
    if isinstance(payload, dict) and payload.get("error"):
        raise ValueError(f"ACIS returned an error for station {sid}: {payload['error']}")
    return payload
