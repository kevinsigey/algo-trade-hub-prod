"""AIS coverage reaches the geo2 stress engine (Kevin's Hormuz fix,
2026-11-14): the snapshot stores the coverage counts the frontend already
computes from the vessel picture (seen / typed / in-gate), and the stress
read excludes the gate-flow and anchoring signals when the gate zone is
blind -- a blind zero is UNAVAILABLE, never a calm zero diluting the mean.
When coverage is good, an observed zero still speaks. Batches written
before the coverage metrics existed carry no coverage rows, and the read
keeps its legacy behavior for them.
"""
from datetime import UTC, datetime

import pytest

from tradehub.geo import feeds, snapshot
from tradehub.geo.ais_state import AisState
from tradehub.geo.regions import HORMUZ
from tradehub.geo.stress import ais_coverage, sensitive_stress
from workshop_fake import DB

NOW = datetime(2026, 11, 14, 21, 30, tzinfo=UTC)

BASE = {("ais", "tankers_gate_entries_1h"): 10.0, ("ais", "anchored_tankers"): 2.0,
        ("adsb_jamming", "jamming_intraday"): 0.04, ("gpsjam", "jamming_daily"): 0.03,
        ("adsb", "mil_total"): 2.0, ("adsb", "mil_isr"): 1.0, ("adsb", "mil_tanker"): 1.0,
        ("firms", "frp_terminals"): 0.0}

# A hot day on the non-AIS signals: jamming and military at full stress,
# no terminal fires. Speaking weight without the AIS signals is 6 of 11,
# so the read still lands: (3*1 + 2*1 + 1*0) / 6.
HOT = {("adsb_jamming", "jamming_intraday"): 0.12, ("gpsjam", "jamming_daily"): 0.09,
       ("adsb", "mil_total"): 6.0}


def _current(overrides=None, coverage=None):
    values = {**BASE, **(overrides or {})}
    rows = [{"feed": f, "metric": m, "value": v, "health": "live"} for (f, m), v in values.items()]
    if coverage is not None:
        seen, typed, in_gate = coverage
        rows += [{"feed": "ais", "metric": "vessels_in_region", "value": seen, "health": "live"},
                 {"feed": "ais", "metric": "vessels_typed", "value": typed, "health": "live"},
                 {"feed": "ais", "metric": "vessels_in_gate", "value": in_gate, "health": "live"}]
    return rows


def _history(n=30):
    return [{"feed": f, "metric": m, "value": v} for (f, m), v in BASE.items() for _ in range(n)]


def _msg(mtype, mmsi, **body):
    return {"MessageType": mtype, "MetaData": {"MMSI": mmsi}, "Message": {mtype: body}}


def test_ais_metrics_carry_the_coverage_counts():
    s = AisState(HORMUZ)
    s.apply(_msg("ShipStaticData", 1, Type=80, Name="TANKER ONE"), NOW)
    s.apply(_msg("PositionReport", 1, Latitude=26.5, Longitude=56.4, Sog=12.0), NOW)  # in the gate
    s.apply(_msg("PositionReport", 2, Latitude=25.0, Longitude=55.05, Sog=3.0), NOW)  # untyped, Jebel Ali
    m = s.metrics(NOW)
    assert m["vessels_in_region"] == 2 and m["vessels_typed"] == 1 and m["vessels_in_gate"] == 1


def test_snapshot_writes_coverage_rows(tmp_path, monkeypatch):
    state = AisState(HORMUZ)
    state.apply(_msg("ShipStaticData", 1, Type=80, Name="TANKER ONE"), NOW)
    state.apply(_msg("PositionReport", 1, Latitude=26.5, Longitude=56.4, Sog=12.0), NOW)
    state.apply(_msg("PositionReport", 2, Latitude=25.0, Longitude=55.05, Sog=3.0), NOW)
    state.last_msg_at = NOW.isoformat()
    path = tmp_path / "ais.json"
    path.write_text(state.to_json())
    monkeypatch.setattr(snapshot.feeds, "mil_air",
                        lambda region: {"mil_total": 0, "mil_tanker": 0, "mil_isr": 0,
                                        "mil_other": 0, "aircraft": []})
    monkeypatch.setattr(snapshot.feeds, "jamming_intraday",
                        lambda region: {"jamming_intraday": 0.05, "nac_good": 19, "nac_bad": 1})
    monkeypatch.setattr(snapshot.feeds, "gpsjam",
                        lambda region, today: {"jamming_daily": 0.04, "hexes": 10,
                                               "nac_good": 90, "nac_bad": 4, "for_date": "2026-11-14"})
    monkeypatch.setattr(snapshot.feeds, "quakes", lambda region, since_iso: [])
    monkeypatch.setattr(snapshot.feeds, "firms",
                        lambda region, key: (_ for _ in ()).throw(feeds.FeedDown("no key")))
    db = DB()
    snapshot.run_snapshot(db, HORMUZ, now=NOW, ais_path=str(path), firms_key=None)
    rows = {(r["feed"], r["metric"]): r for r in db.db["geo_snapshots"]}
    assert rows[("ais", "vessels_in_region")]["value"] == 2
    assert rows[("ais", "vessels_typed")]["value"] == 1
    assert rows[("ais", "vessels_in_gate")]["value"] == 1


def test_coverage_verdict_mirrors_the_frontend_rule():
    # Nov 14 2026 live: 18 vessels off Dubai, 10 typed, none in the gate.
    cov = ais_coverage(_current(coverage=(18, 10, 0)))
    assert cov == {"seen": 18.0, "typed": 10.0, "in_gate": 0.0,
                   "gate_gap": True, "region_gap": False}
    cov = ais_coverage(_current(coverage=(18, 12, 3)))
    assert cov["gate_gap"] is False and cov["region_gap"] is False
    cov = ais_coverage(_current(coverage=(18, 3, 2)))   # typing too thin to trust tanker counts
    assert cov["gate_gap"] is True and cov["region_gap"] is True
    assert ais_coverage(_current()) is None            # pre-coverage batch: no verdict


def test_blind_coverage_excludes_gate_flow_and_anchoring():
    blind = sensitive_stress(
        _current({**HOT, ("ais", "tankers_gate_entries_1h"): 0.0, ("ais", "anchored_tankers"): 0.0},
                 coverage=(18, 10, 0)), _history())
    absent_rows = [r for r in _current(HOT)
                   if r["metric"] not in ("tankers_gate_entries_1h", "anchored_tankers")]
    absent = sensitive_stress(absent_rows, _history())
    # A blind zero reads exactly like the signals being absent -- it does
    # not dilute the mean the way a speaking zero would.
    assert blind[0] == absent[0] == pytest.approx(5 / 6)
    assert blind[2]["gate_flow"] == "unavailable" and blind[2]["anchoring"] == "unavailable"
    assert blind[3] is True  # partial


def test_covered_zeros_still_speak():
    stress, k, contrib, partial = sensitive_stress(
        _current({**HOT, ("ais", "tankers_gate_entries_1h"): 0.0, ("ais", "anchored_tankers"): 0.0},
                 coverage=(18, 12, 3)), _history())
    # The observed empty gate is the collapse signal at full stress; the
    # observed empty anchorages are a calm zero. Both count.
    assert contrib["gate_flow"] == 1.0 and contrib["anchoring"] == 0.0
    assert stress == pytest.approx(8 / 11) and partial is False


def test_no_coverage_rows_keeps_legacy_behavior():
    stress, k, contrib, partial = sensitive_stress(
        _current({("ais", "tankers_gate_entries_1h"): 0.0}), _history())
    assert contrib["gate_flow"] == 1.0 and contrib["anchoring"] == 0.0 and partial is False


def test_stale_coverage_rows_give_no_verdict_and_legacy_scoring():
    # The same numbers that read as a blind gate when live (18/10/0), but
    # the coverage rows are stale: a stale picture is no verdict at all --
    # the snapshot marks every AIS row with the feed's health, so stale
    # coverage rows are the last-known picture, not a live observation.
    # With no verdict, the coverage exclusion does not apply and the read
    # falls back to the per-signal rules, where the live zero gate counts
    # speak as observed values. (In a real stale batch the AIS signal rows
    # are stale too and drop out on their own health; this pins the
    # coverage contract in isolation.)
    rows = _current({**HOT, ("ais", "tankers_gate_entries_1h"): 0.0,
                     ("ais", "anchored_tankers"): 0.0}, coverage=(18, 10, 0))
    for r in rows:
        if r["metric"] in ("vessels_in_region", "vessels_typed", "vessels_in_gate"):
            r["health"] = "stale"
    assert ais_coverage(rows) is None
    stress, k, contrib, partial = sensitive_stress(rows, _history())
    assert "ais_coverage" not in contrib
    assert contrib["gate_flow"] == 1.0 and contrib["anchoring"] == 0.0
    assert stress == pytest.approx(8 / 11) and partial is False
