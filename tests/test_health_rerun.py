"""The Health re-run trigger (phase-2 §4.3): a file the host watcher claims, carrying
who asked and when; one pending request per job; a failed write is an error, not a
request that silently never happened."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tradehub import health_rerun

NOW = datetime(2026, 11, 1, 17, 30, tzinfo=UTC)


def test_request_writes_the_trigger_with_who_and_when(tmp_path):
    out = health_rerun.request_rerun("scan", requested_by="k@example.com", now=NOW, directory=tmp_path)
    assert out == {"status": "pending", "job": "scan", "requested_by": "k@example.com",
                   "requested_at": NOW.isoformat()}
    on_disk = json.loads((tmp_path / "scan.json").read_text())
    assert on_disk == {"job": "scan", "requested_by": "k@example.com", "requested_at": NOW.isoformat()}
    assert health_rerun.pending(tmp_path) == {"scan": on_disk}


def test_a_second_ask_returns_the_waiting_request_unchanged(tmp_path):
    health_rerun.request_rerun("settle", requested_by="k@example.com", now=NOW, directory=tmp_path)
    again = health_rerun.request_rerun("settle", requested_by="other@example.com",
                                       now=datetime(2026, 11, 1, 18, 0, tzinfo=UTC), directory=tmp_path)
    assert again["status"] == "already_pending"
    assert again["requested_by"] == "k@example.com" and again["requested_at"] == NOW.isoformat()


def test_only_scan_and_settle_can_be_re_run(tmp_path):
    for job in ("journal", "orderbooks", "scan; rm -rf", ""):
        with pytest.raises(ValueError):
            health_rerun.request_rerun(job, requested_by="k@example.com", now=NOW, directory=tmp_path)
    assert list(tmp_path.iterdir()) == []  # a refused job writes nothing


def test_an_unwritable_trigger_dir_is_an_error_not_a_silent_request(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    with pytest.raises(health_rerun.RerunUnavailable):
        health_rerun.request_rerun("scan", requested_by="k@example.com", now=NOW,
                                   directory=blocker / "rerun")


def test_pending_ignores_corrupt_and_foreign_files(tmp_path):
    (tmp_path / "scan.json").write_text("not json")
    (tmp_path / "other.json").write_text("{}")
    assert health_rerun.pending(tmp_path) == {}


def test_api_round_trip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from tradehub.api import admin, main
    monkeypatch.setenv("TRADEHUB_RERUN_DIR", str(tmp_path))
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "k@example.com", "is_admin": True}
    client = TestClient(main.app)
    placed = client.post("/api/health/rerun", json={"job": "scan"})
    assert placed.status_code == 200 and placed.json()["status"] == "pending"
    assert placed.json()["requested_by"] == "k@example.com"
    assert client.post("/api/health/rerun", json={"job": "scan"}).json()["status"] == "already_pending"
    assert client.post("/api/health/rerun", json={"job": "journal"}).status_code == 400
    body = client.get("/api/health/rerun").json()
    assert body["pending"]["scan"]["requested_by"] == "k@example.com"
    assert Path(tmp_path / "scan.json").exists()
