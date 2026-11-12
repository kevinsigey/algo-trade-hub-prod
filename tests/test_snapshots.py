"""Snapshot store + hourly precompute + snapshot-first endpoints (step 5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tradehub import precompute, snapshots
from tradehub.api import main
from tradehub.api.dependencies import get_supabase
from tests.workshop_fake import DB

NOW = datetime(2026, 11, 12, 17, 0, tzinfo=timezone.utc)


# -- the store -------------------------------------------------------------------

def test_roundtrip_and_freshness(tmp_path):
    snapshots.write_snapshot("health", {"status": "ok"}, now=NOW, dir=tmp_path)
    env = snapshots.read_snapshot("health", max_age_seconds=5400, now=NOW, dir=tmp_path)
    assert env["payload"] == {"status": "ok"}
    assert env["built_at"] == NOW.isoformat()
    stale = snapshots.read_snapshot(
        "health", max_age_seconds=5400, now=NOW + timedelta(seconds=5401), dir=tmp_path)
    assert stale is None


def test_missing_and_corrupt_read_as_none(tmp_path):
    assert snapshots.read_snapshot("nope", max_age_seconds=60, now=NOW, dir=tmp_path) is None
    (tmp_path / "bad.json").write_text("{not json")
    assert snapshots.read_snapshot("bad", max_age_seconds=60, now=NOW, dir=tmp_path) is None


def test_write_is_atomic_no_tmp_left(tmp_path):
    snapshots.write_snapshot("macro", {"cards": []}, now=NOW, dir=tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["macro.json"]


# -- write_all -------------------------------------------------------------------

def test_write_all_writes_health_from_empty_db(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEHUB_SNAPSHOT_DIR", str(tmp_path))
    statuses = precompute.write_all(DB(), NOW)
    assert statuses["health"] == "written"
    env = snapshots.read_snapshot("health", max_age_seconds=60, now=NOW, dir=tmp_path)
    assert env is not None and "status" in env["payload"]


def test_write_all_isolates_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEHUB_SNAPSHOT_DIR", str(tmp_path))
    import tradehub.weather_page as wp

    def boom(supa):
        raise RuntimeError("journal read down")

    monkeypatch.setattr(wp, "build_weather", boom)
    statuses = precompute.write_all(DB(), NOW)
    assert statuses["weather"].startswith("failed:")
    assert statuses["health"] == "written"  # the failure did not block the rest


def test_degraded_macro_is_not_snapshotted(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEHUB_SNAPSHOT_DIR", str(tmp_path))
    import tradehub.macro as macro_mod

    monkeypatch.setattr(macro_mod, "compose_macro",
                        lambda supa: ({"cards": []}, True))
    statuses = precompute.write_all(DB(), NOW)
    assert statuses["macro"] == "degraded, not snapshotted"
    assert snapshots.read_snapshot("macro", max_age_seconds=60, now=NOW,
                                   dir=tmp_path) is None


# -- endpoints serve snapshots -----------------------------------------------------

def _client():
    app = main.app
    app.dependency_overrides[get_supabase] = lambda: DB()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    main.app.dependency_overrides.clear()


def test_health_endpoint_serves_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEHUB_SNAPSHOT_DIR", str(tmp_path))
    built = datetime.now(timezone.utc)
    report = {"status": "ok", "generated_at": built.isoformat(),
              "problems": [], "timers": {}, "families": {}}
    snapshots.write_snapshot("health", report, now=built, dir=tmp_path)
    monkeypatch.setattr(main, "collect_health",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live build called")))
    body = _client().get("/api/health").json()
    assert body["report"]["generated_at"] == built.isoformat()


def test_health_endpoint_falls_back_when_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEHUB_SNAPSHOT_DIR", str(tmp_path))
    # Stale against the REAL clock (the endpoint reads with real now):
    # three hours old is past the 90-minute freshness bound.
    real_now = datetime.now(timezone.utc)
    snapshots.write_snapshot("health", {"status": "ok"}, now=real_now - timedelta(hours=3),
                             dir=tmp_path)
    live = {"status": "ok", "generated_at": "live", "problems": []}
    monkeypatch.setattr(main, "collect_health", lambda *a, **k: live)
    monkeypatch.setattr(main, "public_health_report", lambda r: r)
    body = _client().get("/api/health").json()
    assert body["report"]["generated_at"] == "live"


def test_macro_endpoint_serves_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEHUB_SNAPSHOT_DIR", str(tmp_path))
    snapshots.write_snapshot("macro", {"as_of": "snap", "cards": []},
                             now=datetime.now(timezone.utc), dir=tmp_path)
    monkeypatch.setattr("tradehub.macro.compose_macro",
                        lambda supa: (_ for _ in ()).throw(AssertionError("live build called")))
    body = _client().get("/api/macro").json()
    assert body["as_of"] == "snap"


def test_weather_endpoint_serves_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEHUB_SNAPSHOT_DIR", str(tmp_path))
    payload = {"as_of": "snap", "today": [], "settled": []}
    snapshots.write_snapshot("weather", payload, now=datetime.now(timezone.utc), dir=tmp_path)
    body = _client().get("/api/weather").json()
    assert body["as_of"] == "snap"
