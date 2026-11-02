"""Chokepoints (Kevin, 2026-11-02): feed parsers, AIS state, and the snapshot
writer's health discipline -- a dead feed is UNKNOWN, never zero."""
from datetime import UTC, datetime

import pytest

from tradehub.geo import feeds, snapshot
from tradehub.geo.ais_state import AisState, is_tanker
from tradehub.geo.regions import HORMUZ
from workshop_fake import DB

NOW = datetime(2026, 11, 2, 22, 0, tzinfo=UTC)


def test_mil_classification_and_bbox():
    payload = {"ac": [
        {"lat": 26.5, "lon": 56.4, "t": "K35R", "flight": "PEARL21"},
        {"lat": 26.6, "lon": 56.5, "t": "R135", "flight": "JAKE11"},
        {"lat": 26.4, "lon": 56.3, "t": "F16", "flight": "VIPER1"},
        {"lat": 40.0, "lon": 56.4, "t": "K35R", "flight": "FARAWAY"},  # outside the bbox
    ]}
    out = feeds.parse_mil(payload, HORMUZ)
    assert (out["mil_tanker"], out["mil_isr"], out["mil_other"], out["mil_total"]) == (1, 1, 1, 3)


def test_mil_down_is_unknown_not_zero():
    with pytest.raises(feeds.FeedDown):
        feeds.parse_mil({}, HORMUZ)


def test_jamming_point_share():
    out = feeds.parse_jamming_point({"ac": [{"nac_p": 3}, {"nac_p": 9}, {"nac_p": 10}, {"nac_p": None}]})
    assert out["jamming_intraday"] == pytest.approx(1 / 3) and out["nac_bad"] == 1


def test_gpsjam_aggregates_region_hexes_only():
    hex_in = next(iter(HORMUZ.gpsjam_hexes))
    csv_text = ("hex,count_good_aircraft,count_bad_aircraft\n"
                f"{hex_in},90,10\n"
                "deadbeef,0,500\n")
    out = feeds.parse_gpsjam(csv_text, HORMUZ)
    assert out["jamming_daily"] == pytest.approx(0.1) and out["hexes"] == 1


def test_firms_terminal_assignment():
    csv_text = ("latitude,longitude,frp,acq_date,acq_time,satellite\n"
                "29.25,50.33,42.5,2026-11-02,0100,N20\n"     # inside Kharg Island's box
                "26.5,55.0,10.0,2026-11-02,0100,N20\n")      # open water: not a terminal
    out = feeds.parse_firms(csv_text, HORMUZ)
    assert out["frp_terminals"] == 42.5 and out["frp_other"] == 10.0
    assert out["terminal_detections"][0]["terminal"] == "Kharg Island"


def _msg(mtype, mmsi, **body):
    return {"MessageType": mtype, "MetaData": {"MMSI": mmsi}, "Message": {mtype: body}}


def test_ais_state_gate_entries_and_anchorages():
    s = AisState(HORMUZ)
    s.apply(_msg("ShipStaticData", 1, Type=80, Name="TANKER ONE"), NOW)
    s.apply(_msg("PositionReport", 1, Latitude=26.5, Longitude=55.0, Sog=12.0), NOW)   # outside gate
    assert s.metrics(NOW)["tankers_gate_entries_1h"] == 0
    s.apply(_msg("PositionReport", 1, Latitude=26.5, Longitude=56.4, Sog=12.0), NOW)   # enters gate
    m = s.metrics(NOW)
    assert m["tankers_gate_entries_1h"] == 1 and m["tankers_in_gate"] == 1
    s.apply(_msg("ShipStaticData", 2, Type=70, Name="CARGO"), NOW)  # not a tanker
    s.apply(_msg("PositionReport", 2, Latitude=25.17, Longitude=56.37, Sog=0.2), NOW)  # Fujairah anchorage
    m = s.metrics(NOW)
    assert m["anchored_tankers"] == 0 and m["vessels_in_region"] == 2  # cargo at anchor is not a tanker
    assert is_tanker(89) and not is_tanker(70)


def test_snapshot_dead_feeds_are_unknown_never_zero(tmp_path, monkeypatch):
    db = DB()
    monkeypatch.setattr(snapshot.feeds, "mil_air", lambda region: (_ for _ in ()).throw(feeds.FeedDown("boom")))
    monkeypatch.setattr(snapshot.feeds, "jamming_intraday", lambda region: {"jamming_intraday": 0.05, "nac_good": 19, "nac_bad": 1})
    monkeypatch.setattr(snapshot.feeds, "gpsjam", lambda region, today: (_ for _ in ()).throw(feeds.FeedDown("404")))
    monkeypatch.setattr(snapshot.feeds, "quakes", lambda region, since_iso: [])
    out = snapshot.run_snapshot(db, HORMUZ, now=NOW, ais_path=str(tmp_path / "missing.json"), firms_key=None)
    health = {(r["feed"], r["metric"]): r for r in db.db["geo_snapshots"]}
    assert health[("adsb", "health")]["health"] == "unknown" and health[("adsb", "health")]["value"] is None
    assert health[("usgs", "quakes_24h")]["value"] == 0  # a working feed's real zero
    assert health[("ais", "health")]["health"] == "unknown"  # no state file: unknown, not 0 ships
    assert health[("firms", "health")]["health"] == "unknown"  # no MAP_KEY yet
    assert out["feeds"]["adsb_jamming"] == "live"
