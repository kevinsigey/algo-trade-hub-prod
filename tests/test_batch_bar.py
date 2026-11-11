"""A3 (Claude review, 2026-11-10): an idea generated as one trial of a wider
search was judged as if it were the only trial -- its page said "Variations
tried on this idea: 1" while it was trial 54 of a 500-trial lab search. Ideas
now carry their search (batch_id + batch_trial, migration
20261111000002_ideas_batch), the shuffle bar is raised by the trials in the
batch (bar = 0.05 / max(own variations, batch size)), each run is stamped
with its batch, and the list and idea page show "Trial N of M in <batch>".

Scope note (as proposed to Kevin, 2026-11-11): for walk-forward-judged runs
the verdict still also turns on the A2 p <= 0.01 leg; the batch raises the
shuffle bar itself. Gen 2 survivors carry no trial number in their record,
so their batch_trial stays null and their position falls back to creation
order -- a number is never invented for them.
"""
import pytest
from fastapi.testclient import TestClient

from tradehub.api import admin, main
from tradehub.api.dependencies import get_supabase
from tradehub.workshop import store
from workshop_fake import DB

SPEC = {"title": "Gold when rates rise", "hold": ["GLD"], "otherwise": "SPY", "claim": "beats_benchmark_when",
        "when": {"source": "fred", "series": "DGS10", "measure": "change", "op": ">", "threshold": 0.25}}
EVENT = {"kind": "event", "title": "XOM drifts up after beats", "tickers": ["XOM"], "event": "earnings",
         "when": "beat", "window": "drift_1_5", "direction": "up"}
RESULT = {"verdict": "PASS", "headline": "Did what it claims.", "data_end": "2026-10-29",
          "shuffle": {"p": 0.001, "bar": 0.05, "beats_pct": 99.9, "permutations": 1000, "seed": 1},
          "walk_forward": {"held": 4, "of": 4, "folds": []}}


# ── the store: batch identity, positions, auto-assignment ───────────────────

def test_batch_info_counts_siblings_and_positions():
    db = DB()
    store.create_idea(db, "One idea", "x", batch_id="spec-x", batch_trial=1)
    two = store.create_idea(db, "Two idea", "x", batch_id="spec-x", batch_trial=2)
    store.create_idea(db, "Three idea", "x", batch_id="spec-x", batch_trial=3)
    store.create_idea(db, "Solo idea", "x")
    assert store.batch_info(db, two) == {"id": "spec-x", "trial": 2, "size": 3, "position": 2}
    assert store.batch_info(db, {"id": 99, "batch_id": None, "batch_trial": None}) is None


def test_batch_info_positions_unrecorded_trials_by_creation_order():
    db = DB()
    rows = db.db.setdefault("ideas", [])
    for n in range(3):  # the Gen 2 shape: batch named, no trial numbers recorded
        rows.append({"id": n + 1, "title": f"Idea {n}", "batch_id": "gen-2", "batch_trial": None})
    info = store.batch_info(db, rows[1])
    assert info == {"id": "gen-2", "trial": None, "size": 3, "position": 2}


def test_create_idea_auto_assigns_the_next_trial():
    db = DB()
    assert store.create_idea(db, "One idea", "x", batch_id="lab")["batch_trial"] == 1
    assert store.create_idea(db, "Two idea", "x", batch_id="lab")["batch_trial"] == 2
    store.create_idea(db, "Nine idea", "x", batch_id="lab", batch_trial=9)
    assert store.create_idea(db, "Ten idea", "x", batch_id="lab")["batch_trial"] == 10
    solo = store.create_idea(db, "Solo idea", "x")
    assert "batch_id" not in solo and "batch_trial" not in solo


# ── the API: creation, the raised bar, the stamp, the surfaces ──────────────

@pytest.fixture
def api(monkeypatch):
    db = DB()
    main.app.dependency_overrides[get_supabase] = lambda: db
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: ("closes", tuple(tickers)))
    monkeypatch.setattr(main, "workshop_fred", lambda series, start: "series")
    monkeypatch.setattr(main, "workshop_earnings", lambda t: f"earnings:{t}")
    captured = {}

    def fake_run_test(spec, closes, fred, **kw):
        captured["rule_variations"] = kw["variations"]
        return {**RESULT, "variations": kw["variations"],
                "shuffle": {**RESULT["shuffle"], "bar": 0.05 / kw["variations"]}}

    def fake_event_test(spec, closes, events, *, variations, seed):
        captured["event_variations"] = variations
        return {**RESULT, "kind": "event", "variations": variations,
                "shuffle": {**RESULT["shuffle"], "bar": 0.05 / variations}}

    monkeypatch.setattr(main, "run_test", fake_run_test)
    monkeypatch.setattr(main, "run_event_test", fake_event_test)
    yield TestClient(main.app), db, captured
    main.app.dependency_overrides.clear()


def _batch(c, n=3, batch_id="spec-x"):
    return [c.post("/api/workshop/ideas", json={"title": f"Idea {k}", "plain_words": "x",
                                                "batch_id": batch_id, "batch_trial": k}).json()
            for k in range(1, n + 1)]


def test_create_idea_accepts_a_batch(api):
    c, _, _ = api
    idea = c.post("/api/workshop/ideas", json={"title": "Batch member", "plain_words": "x",
                                               "batch_id": "spec-x", "batch_trial": 2}).json()
    assert idea["batch_id"] == "spec-x" and idea["batch_trial"] == 2
    auto = c.post("/api/workshop/ideas", json={"title": "Next member", "plain_words": "x",
                                               "batch_id": "spec-x"}).json()
    assert auto["batch_trial"] == 3


def test_a_batch_members_run_uses_the_batch_count_for_its_bar(api):
    c, _, captured = api
    ideas = _batch(c)
    r = c.post(f"/api/workshop/ideas/{ideas[1]['id']}/runs", json={"spec": SPEC})
    assert r.status_code == 200
    assert captured["rule_variations"] == 3  # max(own variation 1, batch size 3)
    run = r.json()
    assert run["result"]["batch"] == {"id": "spec-x", "trial": 2, "position": 2, "of": 3}
    assert run["result"]["bar"]["shuffle_bar"] == pytest.approx(0.05 / 3)


def test_an_unbatched_idea_keeps_its_own_count(api):
    c, _, captured = api
    idea = c.post("/api/workshop/ideas", json={"title": "Solo idea", "plain_words": "x"}).json()
    c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC})
    r = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC})
    assert captured["rule_variations"] == 2
    assert "batch" not in r.json()["result"]


def test_an_event_run_uses_the_batch_count_too(api):
    c, _, captured = api
    ideas = _batch(c, n=2, batch_id="lab-events")
    r = c.post(f"/api/workshop/ideas/{ideas[0]['id']}/event-runs", json={"spec": EVENT})
    assert r.status_code == 200
    assert captured["event_variations"] == 2
    assert r.json()["result"]["batch"] == {"id": "lab-events", "trial": 1, "position": 1, "of": 2}


def test_list_and_detail_carry_the_batch(api):
    c, _, _ = api
    ideas = _batch(c)
    listed = {r["id"]: r for r in c.get("/api/workshop/ideas").json()}
    assert listed[ideas[1]["id"]]["batch"] == {"id": "spec-x", "trial": 2, "size": 3, "position": 2}
    got = c.get(f"/api/workshop/ideas/{ideas[1]['id']}").json()
    assert got["batch"] == {"id": "spec-x", "trial": 2, "size": 3, "position": 2}
    solo = c.post("/api/workshop/ideas", json={"title": "Solo idea", "plain_words": "x"}).json()
    listed = {r["id"]: r for r in c.get("/api/workshop/ideas").json()}
    assert listed[solo["id"]]["batch"] is None
    assert c.get(f"/api/workshop/ideas/{solo['id']}").json()["batch"] is None
