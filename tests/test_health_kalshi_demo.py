"""Health canary for the Kalshi demo runner (2026-11-12): the runner logged
27 passes with 0 candidates while the rule made a gated gas buy. A gated buy
the runner never answered -- no order, no named skip row -- is a problem."""
from datetime import UTC, datetime, timedelta

from tests.workshop_fake import DB
from tradehub import health
from tradehub import kalshi_demo as kd

NOW = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)  # 15:00 ET


def day(buys, placed=0, skipped=0):
    return {"gated_buys": buys, "placed": placed, "skipped": skipped}


def test_canary_flags_unanswered_gated_buys():
    ok = health.kalshi_demo_canary({"today": day(3, placed=2, skipped=1), "yesterday": day(0)})
    assert ok["status"] == "ok" and ok["problems"] == []
    assert ok["summary"] == "Kalshi demo runner: placed 2 of 3 gated gas buys today (ET)"
    # One unanswered buy today may still be in flight; two is the runner not trading.
    assert health.kalshi_demo_canary({"today": day(1), "yesterday": day(0)})["status"] == "ok"
    silent = health.kalshi_demo_canary({"today": day(2), "yesterday": day(0)})
    assert silent["status"] == "silent" and "2 gated gas buys today" in silent["problems"][0]
    # A finished ET day with any unanswered buy is a problem.
    assert health.kalshi_demo_canary({"today": day(0), "yesterday": day(1)})["status"] == "silent"
    assert health.kalshi_demo_canary(None) is None  # unreadable is unknown, not 0


def test_canary_problem_degrades_the_report():
    report = health.build_health_report(
        timers={}, frozen_by_family={}, cadences={}, orderbook_age_seconds=None, now=NOW,
        kalshi_demo={"today": day(2), "yesterday": day(0)})
    assert report["kalshi_demo"]["status"] == "silent"
    assert any("Kalshi demo runner" in p for p in report["problems"])


def test_counts_read_per_et_day():
    db = DB()
    db.db[kd.DECISIONS] = [
        # today ET: two live-gate buys, one answered with an order
        {"series": kd.SERIES, "target": "kalshi:A", "action": "buy", "gate_version": "v1",
         "close_time": (NOW - timedelta(hours=1)).isoformat()},
        {"series": kd.SERIES, "target": "kalshi:B", "action": "buy", "gate_version": "v1",
         "close_time": (NOW - timedelta(hours=2)).isoformat()},
        # the blend shadow's row is never the runner's to trade
        {"series": kd.SERIES, "target": "kalshi:C", "action": "buy", "gate_version": "v2-blend",
         "close_time": (NOW - timedelta(hours=2)).isoformat()},
        # yesterday ET (Nov 11, 20:00 ET), skipped with a row
        {"series": kd.SERIES, "target": "kalshi:D", "action": "buy", "gate_version": "v1",
         "close_time": "2026-11-12T01:00:00+00:00"},
    ]
    db.db[kd.ORDERS] = [
        {"id": 1, "series": kd.SERIES, "target": "kalshi:A", "kalshi_order_id": "o1",
         "status": "settled", "window_close": (NOW - timedelta(hours=1)).isoformat()},
        {"id": 2, "series": kd.SERIES, "target": "kalshi:D", "kalshi_order_id": None,
         "status": "skipped_cap", "window_close": "2026-11-12T01:00:00+00:00"},
    ]
    counts = health._kalshi_demo_counts(db, NOW)
    assert counts == {"today": day(2, placed=1), "yesterday": day(1, skipped=1)}
