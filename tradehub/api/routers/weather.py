"""Weather routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from tradehub.api.dependencies import get_supabase


from tradehub.api.shared import (
    _snapshot,
    _missing_table_message, _table_fault,
    _ttl_by_client, _DEGRADED,
)

log = logging.getLogger(__name__)

router = APIRouter()


@_ttl_by_client(300)
def _macro_live(supabase=Depends(get_supabase)):
    from tradehub.macro import compose_macro

    payload, degraded = compose_macro(supabase)
    if degraded:  # a build with a failed source read is served once, never kept
        _DEGRADED.flag = True
    return payload


@router.get("/api/weather/map", tags=["Weather"])
def get_weather_map(supabase=Depends(get_supabase)):
    """Per-city weather summaries for the map page (phase-3 §3.1), composed
    from journal forecasts WITH their payloads -- the station and the
    ensemble mean live in the payload, which /api/weather strips. A failed
    read is a 503, never an empty map: an empty map would claim the ensemble
    forecasts nowhere.

    Served from the hourly snapshot while fresh (step 5); the live build
    below is the fallback."""
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    snap = _snapshot("weather_map")
    if snap is not None:
        return snap["payload"]
    return _weather_map_live(supabase)


@_ttl_by_client(300)
def _weather_map_live(supabase=Depends(get_supabase)):
    from tradehub.weather_map import compose_weather_map

    try:
        return compose_weather_map(supabase)
    except Exception as e:
        raise HTTPException(status_code=503, detail=_missing_table_message("journal_forecasts", e))


@router.get("/api/weather/degree-days", tags=["Weather"])
def get_degree_days():
    """The degree-day demand panel (§5.3): last completed week's HDD/CDD by Census
    division vs the 10-year normal, plus the population-weighted national index.
    Serves the weekly snapshot file as written; a missing snapshot is a 503 with
    the reason, never a panel of invented zeros."""
    from tradehub.weather_demand import read_snapshot, snapshot_path
    panel = read_snapshot()
    if panel is None:
        raise HTTPException(503, detail=f"no degree-day snapshot at {snapshot_path()} yet -- "
                                        "the weekly degree_days job has not written one")
    return panel


@router.get("/api/weather", tags=["Weather"])
def get_weather(supabase=Depends(get_supabase)):
    """Today's weather forecast vs Kalshi vs climatology, plus settled history.

    Read from journal tables. No new forecasting. The forecaster names are:
    - weather_high/low/rain: the ensemble model
    - baseline_climatology_weather_*: the climatology baseline
    - kalshi_implied_weather_*: the Kalshi market probability

    Served from the hourly snapshot while fresh (step 5); the composition
    itself lives in tradehub/weather_page.py and is the fallback.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    snap = _snapshot("weather")
    if snap is not None:
        return snap["payload"]
    from tradehub.weather_page import WeatherReadError, build_weather

    try:
        return build_weather(supabase)
    except WeatherReadError as exc:
        raise _table_fault(exc.table, exc.__cause__ or exc) from exc
