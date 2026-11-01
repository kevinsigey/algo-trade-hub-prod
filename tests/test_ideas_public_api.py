from datetime import date

import pytest
from fastapi.testclient import TestClient
from workshop_fake import DB

from tradehub.api import main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import service
from tradehub.workshop import store

SPEC = {"title": "Gold beats SPY", "hold": ["GLD"], "claim": "beats_benchmark"}


def run(db, idea_id, variation, verdict):
    db.table("idea_runs").insert({"idea_id": idea_id, "variation": variation, "spec": SPEC, "verdict": verdict,
                                  "result": {"headline": f"h{variation}", "shuffle": {"p": 0.01, "bar": 0.05}},
                                  "data_end": "2026-10-29"}).execute()


@pytest.fixture
def api(monkeypatch):
    db = DB()
    store.create_idea(db, "Gold beats SPY", "gold words")  # 1: published, live, killed
    store.create_idea(db, "Secret", "secret words")  # 2: private
    store.create_idea(db, "Bonds as ballast", "bond words")  # 3: published, backtest only
    run(db, 1, 1, "FAIL")
    run(db, 1, 2, "PASS")
    run(db, 2, 1, "PASS")
    run(db, 3, 1, "FAIL")
    db.db["ideas"][0].update({"published_at": "2026-11-01T00:00:00Z", "live_at": "2026-11-01T15:00:00+00:00",
                              "live_run_id": 2, "size_pct": 20, "killed_at": "2026-11-20T15:00:00+00:00"})
    db.db["ideas"][2]["published_at"] = "2026-11-02T00:00:00Z"
    store.append_shadow(db, 1, [{"day": "2026-11-02", "ret": 0.01, "on": True, "bench": 0.0, "spy": 0.0}])
    monkeypatch.setattr(service, "closed", lambda supa: {"state": "live", "trades": [
        {"symbol": "GLD", "idea": "Gold beats SPY", "pnl": 10.0}, {"symbol": "XLE", "idea": "Other", "pnl": 1.0}]})
    monkeypatch.setattr(main, "_today", lambda: date(2026, 11, 25))
    main.app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def test_list_shows_published_only_with_fails_and_kills(api):
    rows = api.get("/api/ideas").json()
    assert [r["title"] for r in rows] == ["Bonds as ballast", "Gold beats SPY"]
    bonds, gold = rows
    assert bonds["status"] == "backtest" and bonds["latest_verdict"] == "FAIL" and bonds["live"] is None
    assert gold["status"] == "killed" and gold["variations"] == 2 and gold["claim"] == "beats_benchmark"
    assert gold["live"]["return_pct"] == pytest.approx(1.0) and gold["live"]["state"] == "killed"
    assert "Secret" not in api.get("/api/ideas").text


def test_detail_and_identical_404s(api):
    got = api.get("/api/ideas/1").json()
    assert [r["verdict"] for r in got["runs"]] == ["FAIL", "PASS"] and got["runs"][1]["headline"] == "h2"
    assert got["killed_at"] and len(got["shadow"]["curve"]) == 1
    assert [t["symbol"] for t in got["trades"]] == ["GLD"]
    private, missing = api.get("/api/ideas/2"), api.get("/api/ideas/99")
    assert private.status_code == missing.status_code == 404 and private.json() == missing.json()


def test_live_idea_goes_stale(api):
    db = main.app.dependency_overrides[get_supabase]()
    db.db["ideas"][0]["killed_at"] = None
    gold = next(r for r in api.get("/api/ideas").json() if r["id"] == 1)
    assert gold["status"] == "live" and gold["live"]["state"] == "stale"
