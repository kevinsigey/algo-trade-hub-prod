"""Read side of the chokepoints monitor: the latest snapshot for a region
with every measure set against its trailing 30-day median. This is what
the Oil page (and its 2D map) renders -- server-side, so the page never
guesses a baseline.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tradehub.geo.baselines import feed_health, with_baselines
from tradehub.geo.regions import REGIONS

HISTORY_DAYS = 30
HISTORY_CAP = 5000


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
        return {"region": slug, "name": region.title, "at": None, "feeds": {},
                "metrics": [], "geometry": geometry}
    at = latest[0]["taken_at"]
    current = [r for r in latest if r["taken_at"] == at]
    since = (now - timedelta(days=HISTORY_DAYS)).isoformat()
    history = (supa.table("geo_snapshots")
               .select("feed,metric,value,taken_at")
               .eq("region", slug).gte("taken_at", since).lt("taken_at", at)
               .order("taken_at", desc=True).limit(HISTORY_CAP).execute().data)
    return {"region": slug, "name": region.title, "at": at,
            "feeds": feed_health(current),
            "metrics": with_baselines(current, history),
            "geometry": geometry}
