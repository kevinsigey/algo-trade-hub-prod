"""In-site agent phases 1-2 (Kevin, 2026-11-03): confirmed specs are stored
with their lifecycle state; the accuracy gate translates what is expressible
into a Workshop rule run and judges it with the Workshop's own verdict
machinery; promotions are one step at a time and need a PASS."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from workshop_fake import DB

from tradehub.agent import gate as agent_gate
from tradehub.agent import store as agent_store
from tradehub.api import admin, main
from tradehub.api.dependencies import get_supabase

MANUAL = {
    "thesis": "Energy majors are mispriced into the print and the complex rerates after.",
    "catalysts": ["earnings"], "invalidation": ["guide cut"],
    "universe": ["XLE", "XOM"],
    "entry": {"rule": "manual", "band_pct": None},
    "sizing": {"kind": "pct_of_equity", "value": 10, "per_name_cap_pct": 25},
    "stops": {"kind": "pct", "value": 8},
    "exits": {"take_profit_pct": 20, "time_stop_days": 30},
    "horizon": {"terminal_date": "2026-11-06"},
    "monitoring": ["price_cross"],
    "scoring": {"benchmark": "SPY", "review_at": "terminal_date"},
}

IDX = pd.bdate_range("2020-01-02", "2026-11-02")


def _frame(tickers, start):
    rng = np.random.default_rng(0)
    return pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0.0002, 0.01, len(IDX))) for t in tickers},
                        index=IDX)


DATA_FNS = {
    "closes": _frame,
    "bars": lambda t, start: None,
    "fred": lambda sid, start: pd.Series(dtype=float),
    "analyst": lambda t: pd.DataFrame(),
    "div_yields": lambda spec, prices: {},
}


def _result(verdict: str) -> dict:
    return {"verdict": verdict, "headline": f"{verdict} headline", "reason": None,
            "split_date": "2024-01-02", "data_start": "2020-01-02", "data_end": "2026-11-02",
            "claim": {"unseen": {"holds": verdict == "PASS"}}, "shuffle": {"p": 0.01},
            "walk_forward": {"folds": 4}, "notes": [], "curve": [1, 2, 3]}


# ── Translation ────────────────────────────────────────────────────────────────

def test_manual_entry_translates_with_exits():
    idea, note = agent_gate.to_idea_spec(MANUAL, "Energy rerates")
    assert idea["hold"] == ["XLE", "XOM"] and idea["claim"] == "beats_benchmark"
    assert idea["benchmark"] == "SPY" and idea["start"] == "2020-01-02"
    assert idea["exits"] == {"stop_loss_pct": 8.0, "take_profit_pct": 20.0, "max_days": 30}
    assert "full weight" in note


def test_level_and_event_entries_stay_research_only():
    for rule in ("close_below", "close_above", "event"):
        idea, note = agent_gate.to_idea_spec({**MANUAL, "entry": {"rule": rule}}, "T")
        assert idea is None and "research-only" in note


def test_price_stop_is_noted_not_translated():
    idea, note = agent_gate.to_idea_spec({**MANUAL, "stops": {"kind": "price", "value": 41.5}}, "T")
    assert "stop_loss_pct" not in (idea.get("exits") or {})
    assert "does not translate" in note


# ── Store ──────────────────────────────────────────────────────────────────────

def test_store_round_trip_and_edit_resets_the_gate():
    db = DB()
    row = agent_store.create_spec(db, "Energy", MANUAL, ["which print?"])
    assert row["state"] == "draft" and row["questions"] == ["which print?"]
    agent_store.set_state(db, row["id"], "draft", gate={"verdict": "PASS"})
    assert agent_store.get_spec(db, row["id"])["gate"]["verdict"] == "PASS"
    edited = agent_store.update_spec(db, row["id"], spec={**MANUAL, "universe": ["XLE"]})
    assert edited["state"] == "draft" and edited["gate"] is None
    assert agent_store.list_specs(db)[0]["id"] == row["id"]


# ── The gate ───────────────────────────────────────────────────────────────────

def test_gate_pass_stays_draft_and_records_the_verdict():
    db = DB()
    row = agent_store.create_spec(db, "Energy", MANUAL, [])
    out = agent_gate.run_gate(db, row, run_fn=lambda *a, **k: _result("PASS"), data_fns=DATA_FNS)
    assert out["state"] == "draft"
    assert out["gate"]["verdict"] == "PASS" and out["gate"]["expressible"] is True
    assert out["gate"]["shuffle_p"] == 0.01 and "curve" not in out["gate"]


def test_gate_fail_blocks_the_spec():
    db = DB()
    row = agent_store.create_spec(db, "Energy", MANUAL, [])
    out = agent_gate.run_gate(db, row, run_fn=lambda *a, **k: _result("FAIL"), data_fns=DATA_FNS)
    assert out["state"] == "blocked" and out["gate"]["verdict"] == "FAIL"


def test_gate_research_only_records_the_reason():
    db = DB()
    row = agent_store.create_spec(db, "Energy", {**MANUAL, "entry": {"rule": "event"}}, [])
    out = agent_gate.run_gate(db, row, data_fns=DATA_FNS)
    assert out["state"] == "draft" and out["gate"]["expressible"] is False


# ── Endpoints: lifecycle ───────────────────────────────────────────────────────

@pytest.fixture
def client():
    db = DB()
    main.app.dependency_overrides[get_supabase] = lambda: db
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "k@example.com"}
    yield TestClient(main.app), db
    main.app.dependency_overrides.clear()


def test_create_validates_and_lists(client):
    c, _ = client
    bad = c.post("/api/agent/specs", json={"spec": {**MANUAL, "universe": []}})
    assert bad.status_code == 422 and "universe" in bad.json()["detail"]
    ok = c.post("/api/agent/specs", json={"spec": MANUAL, "questions": ["which print?"]})
    assert ok.status_code == 201 and ok.json()["state"] == "draft"
    assert ok.json()["title"].startswith("Energy majors")
    assert c.get("/api/agent/specs").json()["specs"][0]["id"] == ok.json()["id"]


def test_promotions_need_a_pass_and_move_one_step(client, monkeypatch):
    c, db = client
    spec_id = c.post("/api/agent/specs", json={"spec": MANUAL}).json()["id"]
    # No gate yet: shadow is refused.
    r = c.post(f"/api/agent/specs/{spec_id}/state", json={"state": "shadow"})
    assert r.status_code == 409
    # A PASS on record (as the gate endpoint would store it)...
    agent_store.set_state(db, spec_id, "draft", gate={"verdict": "PASS", "expressible": True})
    # ...still cannot skip shadow on the way to paper-eligible.
    r = c.post(f"/api/agent/specs/{spec_id}/state", json={"state": "paper-eligible"})
    assert r.status_code == 409
    assert c.post(f"/api/agent/specs/{spec_id}/state", json={"state": "shadow"}).json()["state"] == "shadow"
    assert c.post(f"/api/agent/specs/{spec_id}/state", json={"state": "paper-eligible"}).json()["state"] == "paper-eligible"
    # Blocked from anywhere, and Kevin can send it back to draft.
    assert c.post(f"/api/agent/specs/{spec_id}/state", json={"state": "blocked"}).json()["state"] == "blocked"
    assert c.post(f"/api/agent/specs/{spec_id}/state", json={"state": "draft"}).json()["state"] == "draft"


# ── The ITM record endpoint wiring (regression: it called an undefined name
# and its fail-soft branch served zeroes forever) ─────────────────────────────

def test_itm_record_endpoint_passes_the_injected_client(monkeypatch):
    from tradehub import oil_itm

    seen = {}

    def fake_record(supa):
        seen["supa"] = supa
        return {"frozen": 3}

    monkeypatch.setattr(oil_itm, "record", fake_record)
    sentinel = object()
    main.app.dependency_overrides[get_supabase] = lambda: sentinel
    try:
        body = TestClient(main.app).get("/api/oil/itm-record").json()
    finally:
        main.app.dependency_overrides.clear()
    assert body == {"frozen": 3} and seen["supa"] is sentinel
