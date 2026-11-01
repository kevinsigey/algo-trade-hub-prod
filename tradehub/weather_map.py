"""Weather map composition (phase-3 §3.1).

Pure: groups the journal's weather forecasts by station into per-city
summaries for the map page -- the latest unsettled freeze batch per
(station, kind) with every bucket's ensemble / Kalshi / climatology
probability, plus the station's settled record paired against the market on
the same contracts. The journal payload is the only station source (the
public /api/weather strips payloads, which is why this reads the forecasts
directly). A station with a market but no ensemble freeze still appears,
with its kind marked ensemble-less -- coverage gaps stay visible.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# Station id -> (display name, lat, lon). The ids are the ACIS/airport codes
# the journal's weather forecasters freeze under (STATIONS / RAIN_STATION in
# tradehub/journal/forecasters/weather.py); coordinates are the stations'
# own (airport) positions, close enough for a national map.
STATION_INFO: dict[str, tuple[str, float, float]] = {
    "NYC": ("New York", 40.779, -73.969), "LAX": ("Los Angeles", 33.942, -118.243),
    "PHL": ("Philadelphia", 39.874, -75.242), "MSY": ("New Orleans", 30.042, -90.028),
    "AUS": ("Austin", 30.183, -97.680), "OKC": ("Oklahoma City", 35.393, -97.601),
    "ATL": ("Atlanta", 33.630, -84.442), "DEN": ("Denver", 39.856, -104.674),
    "EWR": ("Newark", 40.690, -74.169), "SDF": ("Louisville", 38.174, -85.736),
    "SAT": ("San Antonio", 29.534, -98.470), "MSP": ("Minneapolis", 44.882, -93.222),
    "LAS": ("Las Vegas", 36.084, -115.154), "DCA": ("Washington DC", 38.852, -77.037),
    "DFW": ("Dallas–Fort Worth", 32.898, -97.040), "ORD": ("Chicago (O'Hare)", 41.974, -87.907),
    # Coverage expansion stations (phase-3 §3.2 step 4).
    "MDW": ("Chicago (Midway)", 41.786, -87.752), "MIA": ("Miami", 25.795, -80.279),
    "BOS": ("Boston", 42.366, -71.010), "PHX": ("Phoenix", 33.437, -112.008),
    "SAN": ("San Diego", 32.734, -117.190), "SEA": ("Seattle", 47.450, -122.309),
    "SFO": ("San Francisco", 37.621, -122.379), "TTN": ("Trenton", 40.277, -74.813),
    "HOU": ("Houston", 29.645, -95.279),
}

ENSEMBLE = {f"weather_{k}": k for k in ("high", "low", "rain")}
MARKET = {f"kalshi_implied_weather_{k}": k for k in ("high", "low", "rain")}
CLIM = {f"baseline_climatology_weather_{k}": k for k in ("high", "low", "rain")}


def _bucket_label(payload: Mapping[str, Any]) -> str:
    sub = payload.get("yes_sub_title")
    if sub:
        return str(sub)
    floor, cap = payload.get("floor_strike"), payload.get("cap_strike")
    if floor is not None and cap is not None:
        return f"{floor:g}–{cap:g}"
    if floor is not None:
        return f"≥ {floor:g}"
    if cap is not None:
        return f"≤ {cap:g}"
    return "—"


def build_weather_map(*, forecasts: Sequence[Mapping[str, Any]],
                      settlements: Mapping[str, float]) -> dict[str, Any]:
    """The /api/weather/map body."""
    by_target: dict[str, dict[str, Mapping[str, Any]]] = {}
    for f in forecasts:
        by_target.setdefault(f.get("target"), {})[f.get("forecaster")] = f

    # Settled record per station: ensemble rows paired with the market's
    # freeze on the same target.
    record: dict[str, dict[str, float]] = {}
    for target, outcome in settlements.items():
        rows = by_target.get(target) or {}
        ens = next((r for n, r in rows.items() if n in ENSEMBLE), None)
        mkt = next((r for n, r in rows.items() if n in MARKET), None)
        if ens is None or mkt is None:
            continue
        sid = (ens.get("payload") or {}).get("station")
        if sid not in STATION_INFO:
            continue
        acc = record.setdefault(sid, {"n": 0, "ours": 0.0, "market": 0.0})
        acc["n"] += 1
        acc["ours"] += (ens["probability"] - outcome) ** 2
        acc["market"] += (mkt["probability"] - outcome) ** 2

    # Latest unsettled freeze batch per (station, kind): group ensemble rows
    # by their freeze day, keep the newest day, and lay every source's
    # probability for those targets alongside.
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for f in forecasts:
        kind = ENSEMBLE.get(f.get("forecaster"))
        if kind is None:
            continue
        sid = (f.get("payload") or {}).get("station")
        if sid not in STATION_INFO:
            continue
        if f.get("target") in settlements:
            continue
        day = (f.get("frozen_at") or "")[:10]
        key = (sid, kind)
        cur = groups.get(key)
        if cur is None or day > cur["day"]:
            groups[key] = {"day": day, "rows": [f]}
        elif day == cur["day"]:
            cur["rows"].append(f)

    cities: dict[str, dict[str, Any]] = {}
    for sid, (name, lat, lon) in STATION_INFO.items():
        cities[sid] = {"sid": sid, "name": name, "lat": lat, "lon": lon,
                       "high": None, "low": None, "rain": None,
                       "record": None}
    for (sid, kind), group in groups.items():
        rows = group["rows"]
        buckets = []
        for f in sorted(rows, key=lambda r: (r.get("payload") or {}).get("floor_strike") or 0):
            payload = f.get("payload") or {}
            peers = by_target.get(f.get("target")) or {}
            mkt = next((r for n, r in peers.items() if n in MARKET), None)
            clim = next((r for n, r in peers.items() if n in CLIM), None)
            buckets.append({"label": _bucket_label(payload), "ours": f.get("probability"),
                            "market": (mkt or {}).get("probability"),
                            "clim": (clim or {}).get("probability")})
        mean = next(((f.get("payload") or {}).get("ensemble_mean") for f in rows
                     if (f.get("payload") or {}).get("ensemble_mean") is not None), None)
        version = rows[0].get("forecaster_version")
        cities[sid][kind] = {"day": group["day"], "mean": mean, "version": version, "buckets": buckets}
    for sid, acc in record.items():
        if acc["n"]:
            cities[sid]["record"] = {"n": int(acc["n"]), "brier_ours": acc["ours"] / acc["n"],
                                     "brier_market": acc["market"] / acc["n"]}
    return {"cities": [c for c in cities.values()
                       if c["high"] or c["low"] or c["rain"] or c["record"]]}
