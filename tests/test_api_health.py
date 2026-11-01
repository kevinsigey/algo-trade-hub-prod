"""API tests for /api/health: it stays a 200 liveness check and carries a read-only report.

The report must degrade to `never`/`missing` (never a 500 and never a fabricated 0) when there is no
database or a table is missing -- an operator needs to SEE "no data", not an error page.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from tradehub.api import main
from tradehub.api.dependencies import get_supabase


class _Query:
    """A chainable no-op query that returns one canned row per table."""

    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def contains(self, *a, **k):
        return self

    def execute(self):
        table = self.rows_by_table.get(getattr(self, "_table", ""), [])
        return type("R", (), {"data": table})()


class _Supa:
    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table

    def table(self, name):
        q = _Query(self.rows_by_table)
        q._table = name
        return q


def test_health_is_200_and_carries_a_report_without_a_database(tmp_path, monkeypatch):
    # Point the order-book reader at an empty temp dir so a real /cache/orderbooks on the machine
    # running the suite cannot turn this into a different test.
    monkeypatch.setenv("TRADEHUB_ORDERBOOK_DIR", str(tmp_path))
    main.app.dependency_overrides[get_supabase] = lambda: None
    try:
        response = TestClient(main.app).get("/api/health")
    finally:
        main.app.dependency_overrides.clear()
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"  # liveness is unchanged
    assert body["report"] is not None
    # No database -> timers read `never` and order books `missing`; never a 0 and never a crash.
    assert body["report"]["timers"]["journal"]["status"] == "never"
    assert body["report"]["orderbook"]["status"] == "missing"


def test_health_report_counts_frozen_rows_by_family(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEHUB_ORDERBOOK_DIR", str(tmp_path))
    supa = _Supa({
        "journal_forecasts": [{"forecaster": "weather_high"}, {"forecaster": "weather_high"}],
    })
    main.app.dependency_overrides[get_supabase] = lambda: supa
    try:
        report = TestClient(main.app).get("/api/health").json()["report"]
    finally:
        main.app.dependency_overrides.clear()
    # The fake returned exactly two rows, both weather_high.
    assert report["families"]["weather_high"]["frozen_24h"] == 2


def test_a_healthy_system_reports_fresh_timers_over_the_endpoint(tmp_path, monkeypatch):
    """End to end through the real `collect_health`, not the pure builder.

    A journal scorecard written a minute ago, an order-book file just written, and a completed
    run row from each hourly job a minute ago: every timer reads `ok` and none adds a problem.
    """
    import time

    monkeypatch.setenv("TRADEHUB_ORDERBOOK_DIR", str(tmp_path))
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    fresh_file = tmp_path / "2026-10-17" / "book.jsonl.gz"
    fresh_file.parent.mkdir(parents=True)
    fresh_file.write_text("", encoding="utf-8")
    os.utime(fresh_file, (time.time(), time.time()))

    supa = _Supa({"journal_scores": [{"computed_at": recent.isoformat()}],
                   "scanner_runs": [
                       {"completed_at": recent.isoformat(), "status": "completed", "engines_run": ["scan"]},
                       {"completed_at": recent.isoformat(), "status": "completed", "engines_run": ["settle"]},
                   ]})
    main.app.dependency_overrides[get_supabase] = lambda: supa
    try:
        report = TestClient(main.app).get("/api/health").json()["report"]
    finally:
        main.app.dependency_overrides.clear()

    assert report["timers"]["journal"]["status"] == "ok"
    assert report["timers"]["orderbooks"]["status"] == "ok"
    # Both hourly jobs record their runs now, so nothing is untracked and every timer is read.
    assert report["untracked_timers"] == []
    assert report["timers"]["scan"]["status"] == "ok"
    assert report["timers"]["settle"]["status"] == "ok"
    assert report["tracked_timer_count"] == 4
    # No timer contributes a problem. (This fake returns no `journal_forecasts` rows, so every
    # registered daily family legitimately reads as silent; that is the families half of the report
    # and is covered by tests/test_health.py, so it is deliberately not asserted here.)
    assert [p for p in report["problems"] if p.startswith("timer ")] == []


def test_a_failed_scan_does_not_count_as_the_last_successful_scan(tmp_path, monkeypatch):
    """`complete_run` stamps `completed_at` on failed runs too. If Health read the newest row of
    any status, a scan that fails every hour would refresh its own timer forever and read `ok`
    while never once succeeding. The last COMPLETED scan here is five hours old, so the timer
    must read `stale` despite a failed attempt a minute ago."""
    monkeypatch.setenv("TRADEHUB_ORDERBOOK_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(minutes=1)).isoformat()
    stale = (now - timedelta(hours=5)).isoformat()
    supa = _Supa({"journal_scores": [{"computed_at": recent}],
                  "scanner_runs": [
                      {"completed_at": recent, "status": "failed", "engines_run": ["scan"]},
                      {"completed_at": stale, "status": "completed", "engines_run": ["scan"]},
                      {"completed_at": recent, "status": "completed", "engines_run": ["settle"]},
                  ]})
    main.app.dependency_overrides[get_supabase] = lambda: supa
    try:
        report = TestClient(main.app).get("/api/health").json()["report"]
    finally:
        main.app.dependency_overrides.clear()

    assert report["timers"]["scan"]["status"] == "stale"
    assert report["timers"]["settle"]["status"] == "ok"
    assert any("timer scan is stale" in p for p in report["problems"])


def test_the_route_is_registered_before_the_spa_catch_all():
    import os
    from pathlib import Path

    dist = Path(os.getenv("FRONTEND_DIST",
                           str(Path(main.__file__).resolve().parents[2] / "market_sentiment_tool" / "dist")))
    if not (dist / "index.html").is_file():
        return
    paths = [getattr(route, "path", None) for route in main.app.routes]
    assert "/api/health" in paths, paths
    assert paths.index("/api/health") < paths.index(""), "health is shadowed by the SPA catch-all"
