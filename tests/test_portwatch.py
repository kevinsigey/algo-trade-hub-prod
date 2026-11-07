"""IMF PortWatch ship flow (handover item 5, 2026-11-03): the chokepoint
monitor's own AIS gate count sits at a zero median and cannot signal.
PortWatch publishes daily transit calls per chokepoint (tankers and
tonnage) back to 2019 -- the real flow series. Its endpoint is flaky
(intermittent 400 'Invalid URL'), the data lags about a week and updates
weekly, and counts are AIS-visible transits: a floor, stated wherever
the numbers show.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from tradehub.geo.portwatch import (PortWatchError, fetch_series, flow_summary,
                                    load_flow, parse_features, probe_inventory)

EPOCH_MS = 1767225600000  # 2026-01-01 00:00 UTC


def _body(rows, exceeded=False):
    return {"features": [{"attributes": r} for r in rows], "exceededTransferLimit": exceeded}


def test_parse_handles_both_date_formats_and_sorts():
    rows = parse_features(_body([
        {"date": "2026-01-03", "n_tanker": 12, "n_total": 40, "capacity_tanker": 900.0},
        {"date": EPOCH_MS, "n_tanker": 9, "n_total": 31, "capacity_tanker": 700.0},
        {"date": None, "n_tanker": 5, "n_total": 5},
    ]))
    assert [r["date"] for r in rows] == ["2026-01-01", "2026-01-03"]
    assert rows[0]["n_tanker"] == 9 and rows[1]["capacity_tanker"] == 900.0


def test_parse_error_body_is_empty_not_a_crash():
    assert parse_features({"error": {"code": 400, "message": "Invalid URL"}}) == []


def test_fetch_pages_and_retries():
    pages = {0: _body([{"date": "2026-01-01", "n_tanker": 1, "n_total": 2}], exceeded=True),
             2000: _body([{"date": "2026-01-02", "n_tanker": 3, "n_total": 4}])}
    calls = {"n": 0}

    def flaky(params):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"error": {"code": 400, "message": "Invalid URL"}}
        return pages[params["resultOffset"]]

    rows = fetch_series("chokepoint6", get=flaky, sleep=lambda s: None)
    assert [r["n_tanker"] for r in rows] == [1, 3]


def test_probe_inventory_skips_empty_ids_and_names_the_rest():
    def get(params):
        if params.get("returnCountOnly"):
            pid = params["where"].split("'")[1]
            return {"count": 100 if pid in ("chokepoint6", "chokepoint9") else 0}
        return {"features": [{"attributes": {"portname": "Bab el-Mandeb"}}]}

    found = probe_inventory(get=get, sleep=lambda s: None, candidates=range(5, 11))
    assert found == {"chokepoint6": "Bab el-Mandeb", "chokepoint9": "Bab el-Mandeb"}


def test_fetch_gives_up_loudly_after_tries():
    with pytest.raises(PortWatchError):
        fetch_series("chokepoint6", get=lambda p: {"error": {"code": 400}}, tries=2,
                     sleep=lambda s: None)


def _series(tanker_values, start=date(2026, 8, 1)):
    return [{"date": (start + timedelta(days=i)).isoformat(), "n_tanker": v,
             "n_total": v * 3, "capacity_tanker": v * 100.0}
            for i, v in enumerate(tanker_values)]


def test_flow_summary_against_its_own_baseline():
    rows = _series([10] * 53 + [20] * 7)  # latest day = start + 59
    out = flow_summary(rows, today=date(2026, 10, 7))
    assert out["as_of"] == "2026-09-29" and out["lag_days"] == 8
    assert out["n_tanker_latest"] == 20 and out["n_tanker_7d"] == 20.0
    assert out["tanker_baseline_30d"] == 10.0 and out["tanker_delta_pct"] == 100.0
    assert len(out["recent"]) == 14


def test_flow_summary_year_ago_baseline():
    # 400-day series: first ~365 days at 40/day, last 60 at 1/day
    # as_of = 2026-08-10 + 399 = 2027-09-13 (but we use today=2027-09-20)
    # Year-ago window: [as_of - 394, as_of - 365] -> [2026-08-11, 2026-09-09] -> 30 days of 40/day
    start = date(2026, 8, 10)
    tanker_vals = [40] * 335 + [1] * 65  # 400 days total
    rows = _series(tanker_vals, start)
    # as_of = 2026-08-10 + 399 = 2027-09-13
    out = flow_summary(rows, today=date(2027, 9, 20))
    # Year-ago window: 2026-08-11 to 2026-09-09 (30 days, all 40)
    assert out["tanker_year_ago"] == 40.0
    # 7-day avg is 1, year-ago is 40 -> delta = (1/40 - 1) * 100 = -97.5
    assert out["tanker_year_ago_delta_pct"] == -97.5


def test_flow_summary_insufficient_data_for_year_ago():
    # Only 30 days of data - not enough for year-ago (need 394 days)
    rows = _series([5] * 30)
    out = flow_summary(rows, today=date(2026, 8, 30))
    assert out["tanker_year_ago"] is None
    assert out["tanker_year_ago_delta_pct"] is None


def test_flow_summary_names_a_missing_baseline():
    out = flow_summary(_series([5] * 10), today=date(2026, 8, 20))
    assert out["tanker_baseline_30d"] is None and out["tanker_delta_pct"] is None
    assert flow_summary([], today=date(2026, 8, 20)) is None


def test_load_flow_maps_the_region_and_fails_soft(tmp_path, monkeypatch):
    import json

    rows = _series([10] * 40)
    path = tmp_path / "portwatch.json"
    path.write_text(json.dumps({"pulled_at": "2026-10-06T00:00:00Z",
                                "series": {"chokepoint6": {"name": "Strait of Hormuz", "rows": rows}}}))
    monkeypatch.setenv("GEO_PORTWATCH", str(path))
    out = load_flow("hormuz", today=date(2026, 9, 15))
    assert out is not None and out["source"] == "IMF PortWatch"
    assert load_flow("nope", today=date(2026, 9, 15)) is None
    monkeypatch.setenv("GEO_PORTWATCH", str(tmp_path / "absent.json"))
    assert load_flow("hormuz", today=date(2026, 9, 15)) is None
