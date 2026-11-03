"""AIS consumer state for one region: the rolling picture the snapshot reads.

The consumer (ais_consumer.py) feeds AISStream messages in; this module holds
the pure state logic so it tests without a socket. State persists as JSON on
the cache volume: vessel table (last position, ship type from static data),
gate-entry events for tankers (24h), and connection accounting, so the
snapshot can tell a quiet strait from a dead feed -- the plan's core rule.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

STALE_AFTER_S = 20 * 60        # a state file older than this reads as stale
ENTRY_KEEP_H = 24


def is_tanker(ship_type: int | None) -> bool:
    return ship_type is not None and 80 <= ship_type <= 89


class AisState:
    def __init__(self, region):
        self.region = region
        self.vessels: dict[str, dict] = {}
        self.entries: list[dict] = []          # {"ts": iso, "mmsi": str}
        self.connected_s: float = 0.0          # within the current hour bucket
        self.hour_bucket: str | None = None
        self.last_msg_at: str | None = None
        self.msgs: int = 0

    # -- ingest ---------------------------------------------------------------
    def apply(self, message: dict, now: datetime) -> None:
        meta = message.get("MetaData") or {}
        mmsi = str(meta.get("MMSI") or "")
        if not mmsi:
            return
        self.msgs += 1
        self.last_msg_at = now.isoformat()
        mtype = message.get("MessageType")
        body = message.get("Message") or {}
        v = self.vessels.setdefault(mmsi, {"mmsi": mmsi})
        if mtype == "ShipStaticData":
            ship = body.get("ShipStaticData") or {}
            if ship.get("Type"):
                v["ship_type"] = int(ship["Type"])
            if ship.get("Name"):
                v["name"] = str(ship["Name"]).strip()
            return
        if mtype != "PositionReport":
            return
        pos = body.get("PositionReport") or {}
        lat, lon = pos.get("Latitude"), pos.get("Longitude")
        if lat is None or lon is None:
            return
        from tradehub.geo.regions import inside

        was_in_gate = bool(v.get("in_gate"))
        v.update({"lat": float(lat), "lon": float(lon), "sog": float(pos.get("Sog") or 0),
                  "in_gate": inside(self.region.gate, float(lat), float(lon)),
                  "last_seen": now.isoformat()})
        if v["in_gate"] and not was_in_gate and is_tanker(v.get("ship_type")):
            self.entries.append({"ts": now.isoformat(), "mmsi": mmsi})
        cutoff = (now - timedelta(hours=ENTRY_KEEP_H)).isoformat()
        self.entries = [e for e in self.entries if e["ts"] >= cutoff]
        # A vessel silent for 6h is not "currently" anywhere.
        stale = (now - timedelta(hours=6)).isoformat()
        self.vessels = {m: x for m, x in self.vessels.items()
                        if x.get("last_seen", "") >= stale or m == mmsi}

    def note_connected(self, now: datetime, seconds: float) -> None:
        bucket = now.strftime("%Y-%m-%dT%H")
        if bucket != self.hour_bucket:
            self.hour_bucket, self.connected_s = bucket, 0.0
        self.connected_s += seconds

    # -- the snapshot's read ----------------------------------------------------
    def metrics(self, now: datetime) -> dict:
        from tradehub.geo.regions import inside

        hour_ago = (now - timedelta(hours=1)).isoformat()
        tankers = [v for v in self.vessels.values() if is_tanker(v.get("ship_type"))]
        anchored: dict[str, int] = {}
        for name, box in self.region.anchorages.items():
            anchored[name] = sum(1 for v in tankers
                                 if inside(box, v.get("lat") or 0, v.get("lon") or 0)
                                 and (v.get("sog") or 0) < 1.0)
        return {
            "tankers_gate_entries_1h": sum(1 for e in self.entries if e["ts"] >= hour_ago),
            "tankers_in_gate": sum(1 for v in tankers if v.get("in_gate")),
            "anchored_tankers": sum(anchored.values()),
            "anchored_by_place": anchored,
            "tankers_in_region": len(tankers),
            "vessels_in_region": len(self.vessels),
            "connected_s_this_hour": round(self.connected_s),
            "msgs_total": self.msgs,
            "last_msg_at": self.last_msg_at,
            # The freshest vessel position in the table: when the feed is
            # silent this is the "as of" of the last-known picture.
            "vessels_as_of": max((v["last_seen"] for v in self.vessels.values()
                                  if v.get("last_seen")), default=None),
        }

    # -- persistence ------------------------------------------------------------
    def to_json(self) -> str:
        return json.dumps({"vessels": self.vessels, "entries": self.entries,
                           "connected_s": self.connected_s, "hour_bucket": self.hour_bucket,
                           "last_msg_at": self.last_msg_at, "msgs": self.msgs})

    @classmethod
    def from_json(cls, region, text: str) -> "AisState":
        s = cls(region)
        d = json.loads(text)
        s.vessels, s.entries = d.get("vessels") or {}, d.get("entries") or []
        s.connected_s, s.hour_bucket = d.get("connected_s") or 0.0, d.get("hour_bucket")
        s.last_msg_at, s.msgs = d.get("last_msg_at"), d.get("msgs") or 0
        return s


def read_state_file(path: str, region, now: datetime) -> tuple[dict | None, str]:
    """(metrics, health): health is 'live' when the file is fresh and the feed
    was connected for most of the recent window, 'stale' when the file is old,
    'unknown' when there is no file at all. Empty NEVER reads as zero ships."""
    import os

    if not os.path.exists(path):
        return None, "unknown"
    age = now.timestamp() - os.path.getmtime(path)
    try:
        state = AisState.from_json(region, open(path).read())
    except (ValueError, OSError):
        return None, "unknown"
    if age > STALE_AFTER_S:
        return state.metrics(now), "stale"
    metrics = state.metrics(now)
    # Connected-but-silent is never "live with zero ships" (the chokepoints
    # plan's core rule; verified live Nov 2 2026: AISStream's Gulf boxes
    # stream nothing on the free tier while Singapore flows). What it reads
    # as instead is Kevin's call (2026-11-03): when the state holds vessels
    # with known positions, serve that last-known picture flagged STALE --
    # old but real, never presented as live. Only a state with no
    # positioned vessel at all (we have simply never had coverage) stays
    # UNKNOWN.
    silent = state.last_msg_at is None
    if not silent:
        try:
            silent = (now - datetime.fromisoformat(state.last_msg_at)).total_seconds() > STALE_AFTER_S
        except ValueError:
            silent = True
    if silent:
        positioned = any(v.get("lat") is not None for v in state.vessels.values())
        return metrics, "stale" if positioned else "unknown"
    return metrics, "live"
