"""Read side of the chokepoints monitor: the latest snapshot for a region
with every measure set against its trailing 30-day median. This is what
the Oil page (and its 2D map) renders -- server-side, so the page never
guesses a baseline.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tradehub.geo.baselines import feed_health, with_baselines
from tradehub.geo.regions import REGIONS

HISTORY_DAYS = 30
HISTORY_CAP = 5000
MAX_VESSELS = 250

AIS_STATE_PATH = os.environ.get("GEO_AIS_STATE", "/cache/chokepoints/hormuz-state.json")


def _vessels(region) -> tuple[list[dict], str | None]:
    """The AIS consumer's positioned vessels, straight from its state file
    (the API runs in the same container). These are the last-known picture:
    the caller pairs them with the AIS health, and the map dims them when
    that health is stale -- never presented as live (Kevin, 2026-11-03).
    Fail-soft: any problem reads as no vessels, the panel is additive."""
    try:
        from tradehub.geo.ais_state import AisState, is_tanker

        state = AisState.from_json(region, Path(AIS_STATE_PATH).read_text(encoding="utf-8"))
        out = []
        for mmsi, v in state.vessels.items():
            if v.get("lat") is None or v.get("lon") is None:
                continue
            out.append({"mmsi": mmsi, "name": v.get("name"), "ship_type": v.get("ship_type"),
                        "tanker": is_tanker(v.get("ship_type")), "lat": v["lat"], "lon": v["lon"],
                        "sog": v.get("sog"), "in_gate": bool(v.get("in_gate")),
                        "last_seen": v.get("last_seen")})
        # Tankers first, then the freshest reports; the cap keeps the map readable.
        out.sort(key=lambda r: r["last_seen"] or "", reverse=True)
        out.sort(key=lambda r: not r["tanker"])  # stable: freshness kept within each group
        as_of = max((r["last_seen"] for r in out if r["last_seen"]), default=None)
        return out[:MAX_VESSELS], as_of
    except Exception:  # noqa: BLE001 -- a missing/corrupt state file is no vessels, not an error
        return [], None


def _flow(slug: str, now: datetime) -> dict | None:
    """IMF PortWatch daily transits for the region (portwatch.py): a daily,
    week-lagged series, so it rides beside the 15-minute snapshot metrics
    rather than inside them. Fail-soft None."""
    from tradehub.geo.portwatch import load_flow

    return load_flow(slug, today=now.date())


def _aircraft(current: list[dict]) -> list[dict]:
    """Military aircraft positions: the snapshot already stores them in the
    adsb rows' detail (callsign, type, kind, lat, lon) -- surface them."""
    for row in current:
        if row.get("feed") == "adsb":
            aircraft = (row.get("detail") or {}).get("aircraft")
            if isinstance(aircraft, list):
                return aircraft
    return []


def region_view(supa, slug: str, *, now: datetime | None = None) -> dict | None:
    region = REGIONS.get(slug)
    if region is None:
        return None
    now = now or datetime.now(UTC)
    latest = (supa.table("geo_snapshots")
              .select("feed,metric,value,health,detail,taken_at")
              .eq("region", slug).order("taken_at", desc=True).limit(60).execute().data)
    geometry = {"bbox": region.bbox, "gate": region.gate,
                "anchorages": region.anchorages, "terminals": region.terminals}
    if not latest:
        vessels, vessels_as_of = _vessels(region)
        return {"region": slug, "name": region.title, "at": None, "feeds": {},
                "metrics": [], "geometry": geometry,
                "vessels": vessels, "vessels_as_of": vessels_as_of, "aircraft": [],
                "flow": _flow(slug, now)}
    at = latest[0]["taken_at"]
    current = [r for r in latest if r["taken_at"] == at]
    since = (now - timedelta(days=HISTORY_DAYS)).isoformat()
    history = (supa.table("geo_snapshots")
               .select("feed,metric,value,taken_at")
               .eq("region", slug).gte("taken_at", since).lt("taken_at", at)
               .order("taken_at", desc=True).limit(HISTORY_CAP).execute().data)
    vessels, vessels_as_of = _vessels(region)
    return {"region": slug, "name": region.title, "at": at,
            "feeds": feed_health(current),
            "metrics": with_baselines(current, history),
            "geometry": geometry,
            "vessels": vessels, "vessels_as_of": vessels_as_of,
            "aircraft": _aircraft(current),
            "flow": _flow(slug, now)}
