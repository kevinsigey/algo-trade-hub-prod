"""Batch 2 API surface: the candidate queue read, the compact verdict
chips, and the per-name decision view — all admin-gated, all read-only
except the candidate run trigger (which renders debates through the
existing daily budget, display-only)."""
from fastapi.testclient import TestClient

from tradehub.api import admin, main
from tests.test_debate_candidates import _seeded
from tests.test_name_decision import _verdict_row


def _client(supa):
    from tradehub.api.dependencies import get_supabase as real_get_supabase

    main.app.dependency_overrides[admin.require_admin] = (
        lambda: {"email": "k@example.com", "is_admin": True})
    main.app.dependency_overrides[real_get_supabase] = lambda: supa
    return TestClient(main.app)


def test_verdict_chips_endpoint():
    c = _seeded()
    c.tables["valuation_verdicts"] = [_verdict_row()]
    resp = _client(c).get("/api/verdict-chips")
    assert resp.status_code == 200
    body = resp.json()
    assert body["chips"]["GILD"]["confidence"] == 0.58
    assert body["chips"]["GILD"]["judge"] == "free-ai-proposer"
    assert "generated_at" in body


def test_debate_candidates_endpoint_reads_the_queue():
    c = _seeded()
    c.tables["debate_candidates"] = [{
        "id": 1, "ticker": "GILD", "snapshot_id": 3,
        "candidate_class": "conjunction", "priority": 10,
        "state": "pending", "sources": {"zone": "buy_zone_strong"},
        "computed_at": "2026-11-10T12:00:00+00:00", "verdict_id": None,
        "detail": None}]
    resp = _client(c).get("/api/debate-candidates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["snapshot"]["id"] == 3
    assert body["counts"]["conjunctions"] == 1
    assert body["candidates"][0]["ticker"] == "GILD"


def test_name_decision_endpoint_and_404():
    c = _seeded()
    c.tables["valuation_verdicts"] = [_verdict_row()]
    client = _client(c)
    resp = client.get("/api/name-decision/GILD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "GILD"
    assert body["judgment"]["verdict"]["snapshot_id"] == 3
    assert client.get("/api/name-decision/ZZZZ").status_code == 404
