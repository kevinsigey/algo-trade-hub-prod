"""One Chokepoints snapshot: every feed for the region, written as rows.

Each feed is isolated: a failure writes ONE row (metric 'health', value NULL,
health 'unknown', the error in detail) and never takes the other feeds down
with it. A working feed's genuine zero (no quakes today) is a value, not a
health row. Snapshot rows are (region, feed, metric, value, detail, health);
events (quakes, terminal fire detections) go to geo_events, deduped on their
natural keys so a re-run inside the same window does not double-count.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from tradehub.geo import feeds
from tradehub.geo.ais_state import read_state_file
from tradehub.geo.regions import Region

AIS_STATE_PATH = os.environ.get("GEO_AIS_STATE", "/cache/chokepoints/hormuz-state.json")
FIRMS_KEY_FILE = os.environ.get("GEO_FIRMS_KEY_FILE", "/cache/chokepoints/firms-key.txt")


def _firms_key() -> str | None:
    """Env first, then the key file on the cache volume (the AISStream pattern:
    keys live only on the VPS, chmod 600, never in the repo or the chat)."""
    if os.environ.get("FIRMS_MAP_KEY"):
        return os.environ["FIRMS_MAP_KEY"]
    try:
        return open(FIRMS_KEY_FILE).read().strip() or None
    except OSError:
        return None


FIRMS_KEY = _firms_key()

# Metrics carried in a feed's result dict that are measures, not detail. The
# rest of the dict rides along as the first measure's detail.
AIS_METRICS = ("tankers_gate_entries_1h", "tankers_in_gate", "anchored_tankers",
               "tankers_in_region", "vessels_in_region")


def _row(region: str, feed: str, metric: str, value, health: str, detail: dict | None = None) -> dict:
    return {"region": region, "feed": feed, "metric": metric,
            "value": value, "health": health, "detail": detail or {}}


def _write(supa, rows: list[dict], events: list[dict]) -> None:
    if rows:
        supa.table("geo_snapshots").insert(rows).execute()
    for ev in events:  # events dedupe on (region, kind, dedupe_key)
        found = (supa.table("geo_events").select("id")
                 .eq("region", ev["region"]).eq("kind", ev["kind"])
                 .eq("dedupe_key", ev["dedupe_key"]).limit(1).execute().data)
        if not found:
            supa.table("geo_events").insert(ev).execute()


def run_snapshot(supa, region: Region, *, now: datetime | None = None,
                 ais_path: str = AIS_STATE_PATH, firms_key: str | None = FIRMS_KEY) -> dict:
    now = now or datetime.now(UTC)
    rows: list[dict] = []
    events: list[dict] = []
    summary: dict[str, str] = {}

    def ok(feed: str, metrics: dict, detail: dict) -> None:
        summary[feed] = "live"
        for metric, value in metrics.items():
            rows.append(_row(region.slug, feed, metric, value, "live", detail))

    def down(feed: str, exc: Exception) -> None:
        summary[feed] = "unknown"
        rows.append(_row(region.slug, feed, "health", None, "unknown",
                         {"error": f"{exc.__class__.__name__}: {exc}"[:300]}))

    # AIS: read the consumer's state file; its own health ladder applies.
    try:
        metrics, health = read_state_file(ais_path, region, now)
        if metrics is None:
            rows.append(_row(region.slug, "ais", "health", None, "unknown",
                             {"error": "no AIS state file: the consumer has not run"}))
            summary["ais"] = "unknown"
        else:
            summary["ais"] = health
            detail = {k: metrics[k] for k in ("anchored_by_place", "connected_s_this_hour",
                                              "msgs_total", "last_msg_at")}
            if health == "stale":
                # Kevin's last-known rule (2026-11-03): the counts above are
                # computed from stored positions, not the live feed -- say so
                # on every row, with the picture's own timestamp.
                detail.update({"last_known": True,
                               "vessels_as_of": metrics.get("vessels_as_of")})
            for metric in AIS_METRICS:
                rows.append(_row(region.slug, "ais", metric, metrics[metric], health, detail))
    except Exception as exc:  # noqa: BLE001 -- one feed never sinks the snapshot
        down("ais", exc)

    try:
        m = feeds.mil_air(region)
        ok("adsb", {"mil_total": m["mil_total"], "mil_tanker": m["mil_tanker"], "mil_isr": m["mil_isr"]},
           {"mil_other": m["mil_other"], "aircraft": m["aircraft"]})
    except Exception as exc:  # noqa: BLE001
        down("adsb", exc)

    try:
        j = feeds.jamming_intraday(region)
        ok("adsb_jamming", {"jamming_intraday": round(j["jamming_intraday"], 4)},
           {"nac_good": j["nac_good"], "nac_bad": j["nac_bad"]})
    except Exception as exc:  # noqa: BLE001
        down("adsb_jamming", exc)

    try:
        g = feeds.gpsjam(region, today=now.date())
        ok("gpsjam", {"jamming_daily": round(g["jamming_daily"], 4)},
           {"hexes": g["hexes"], "nac_good": g["nac_good"], "nac_bad": g["nac_bad"],
            "for_date": g["for_date"]})
    except Exception as exc:  # noqa: BLE001
        down("gpsjam", exc)

    try:
        since = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
        found = feeds.quakes(region, since_iso=since)
        ok("usgs", {"quakes_24h": len(found)}, {"window_h": 24})
        for q in found:
            events.append({"region": region.slug, "kind": "quake", "dedupe_key": str(q["id"]),
                           "title": f"M{q['mag']} — {q['place']}", "detail": q,
                           "occurred_at": datetime.fromtimestamp(q["time"] / 1000, UTC).isoformat()
                           if q.get("time") else None})
    except Exception as exc:  # noqa: BLE001
        down("usgs", exc)

    try:
        f = feeds.firms(region, key=firms_key)
        ok("firms", {"frp_terminals": f["frp_terminals"], "frp_region_other": f["frp_other"]},
           {"terminal_detections": len(f["terminal_detections"])})
        for d in f["terminal_detections"]:
            events.append({"region": region.slug, "kind": "fire",
                           "dedupe_key": f"{d['lat']:.4f},{d['lon']:.4f},{d.get('acq_date')},{d.get('acq_time')},{d.get('satellite')}",
                           "title": f"Fire detection at {d['terminal']} — FRP {d['frp']}",
                           "detail": d, "occurred_at": None})
    except Exception as exc:  # noqa: BLE001
        down("firms", exc)

    _write(supa, rows, events)
    return {"region": region.slug, "at": now.isoformat(), "feeds": summary,
            "rows": len(rows), "events": len(events)}
