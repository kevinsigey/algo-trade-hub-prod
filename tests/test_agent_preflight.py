"""The ledger pre-flight: before a new idea is drafted, what the record already says."""
from workshop_fake import DB

from tradehub.agent.preflight import preflight, title_of
from tradehub.workshop import store

DRAFT = {"thesis": "Chips keep beating the market through the cycle", "universe": ["MU", "TXN"],
         "entry": {"rule": "manual"}, "stops": {"kind": "none"}, "exits": {}, "scoring": {"benchmark": "SPY"}}


def _run(rid, iid, hold, verdict="PASS", p=0.001, held=4, value=3.0, claim="beats_benchmark", variation=1):
    return {"id": rid, "idea_id": iid, "verdict": verdict, "variation": variation,
            "spec": {"hold": hold, "claim": claim},
            "result": {"shuffle": {"p": p}, "walk_forward": {"held": held, "of": 4},
                       "claim": {"unseen": {"value": value}}}}


def _db(*ideas):
    db = DB()
    for title, killed in ideas:
        row = store.create_idea(db, title, "words")
        if killed:
            db.db["ideas"][row["id"] - 1]["killed_at"] = killed
    return db


def test_family_attempts_and_best_prior_come_from_the_record():
    db = _db(("MU idea", None), ("TXN+TSM idea", None), ("Gold", None))
    latest = {1: _run(1, 1, ["MU"], value=2.0, variation=3), 2: _run(2, 2, ["TXN", "TSM"], value=5.0),
              3: _run(3, 3, ["GLD"], value=9.0)}
    out = preflight(db, DRAFT, latest)
    assert out["family"]["size"] == 2 and set(out["family"]["tickers"]) == {"MU", "TXN", "TSM"}
    assert out["prior_attempts"] == 4  # gold is a different bet
    assert out["best_prior"] is None  # nothing held exactly these names
    assert out["expressible"] is True and out["killed"] == []
    assert out["bar"]["ideas_tested"] == 3


def test_best_prior_is_the_best_result_on_the_same_names():
    db = _db(("A", None), ("B", None))
    latest = {1: _run(1, 1, ["MU", "TXN"], value=2.0), 2: _run(2, 2, ["TXN", "MU"], value=5.0, held=1)}
    best = preflight(db, DRAFT, latest)["best_prior"]
    assert best["idea_id"] == 2 and best["value"] == 5.0 and best["verdict_now"] == "FAIL"


def test_an_exact_duplicate_of_a_killed_idea_is_named_with_its_reason():
    db = _db(("Same chips", "2026-11-03T00:00:00+00:00"))
    db.table(store.SWITCHES).insert({"idea_id": 1, "on": False, "by": "kevin@example.com"}).execute()
    latest = {1: _run(1, 1, ["TXN", "MU"])}
    out = preflight(db, DRAFT, latest)
    assert out["duplicate_of_killed"] == 1
    assert out["killed"][0]["exact"] is True and out["killed"][0]["reason"] == "killed on 2026-11-03"


def test_a_killed_idea_demoted_by_the_current_bar_says_so_first():
    db = _db(("Same chips", "2026-11-03T00:00:00+00:00"))
    latest = {1: _run(1, 1, ["TXN", "MU"], held=1)}
    out = preflight(db, DRAFT, latest)
    assert "walk-forward" in out["killed"][0]["reason"]


def test_same_names_with_a_different_rule_is_near_not_exact():
    db = _db(("Chips when hot", "2026-11-03T00:00:00+00:00"))
    run = _run(1, 1, ["MU", "TXN"], claim="beats_benchmark_when")
    out = preflight(db, DRAFT, {1: run})
    assert out["duplicate_of_killed"] is None and out["killed"][0]["exact"] is False


def test_an_event_strategy_compares_on_its_universe_and_claims_no_exactness():
    db = _db(("Same chips", "2026-11-03T00:00:00+00:00"))
    draft = {**DRAFT, "entry": {"rule": "event"}}
    out = preflight(db, draft, {1: _run(1, 1, ["MU", "TXN"])})
    assert out["expressible"] is False and out["duplicate_of_killed"] is None
    assert out["family"]["size"] == 1


def test_a_new_bet_has_an_empty_ledger():
    out = preflight(DB(), DRAFT, {})
    assert out["prior_attempts"] == 0 and out["best_prior"] is None and out["family"]["size"] == 0


def test_a_different_benchmark_is_a_different_idea():
    db = _db(("Same chips", "2026-11-03T00:00:00+00:00"))
    draft = {**DRAFT, "scoring": {"benchmark": "QQQ"}}
    run = _run(1, 1, ["MU", "TXN"])
    run["spec"]["benchmark"] = "SPY"
    assert preflight(db, draft, {1: run})["duplicate_of_killed"] is None


def test_best_prior_only_compares_the_same_claim():
    db = _db(("Other claim", None))
    run = _run(1, 1, ["MU", "TXN"], claim="beats_benchmark_when", value=50.0)
    assert preflight(db, DRAFT, {1: run})["best_prior"] is None


def test_title_is_short():
    assert len(title_of({"thesis": "x" * 200})) <= 80


def test_route_withholds_a_duplicate_and_survives_a_broken_check(monkeypatch):
    from fastapi.testclient import TestClient

    from tradehub.api import admin, main
    from tradehub.api.dependencies import get_supabase

    db = _db(("Same chips", "2026-11-03T00:00:00+00:00"))
    monkeypatch.setattr("tradehub.agent.interpret.interpret", lambda text, ctx: (DRAFT, ["size?"], "m"))
    monkeypatch.setattr(main, "_latest_saved_map", lambda supa: {1: _run(1, 1, ["MU", "TXN"])})
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "k"}
    main.app.dependency_overrides[get_supabase] = lambda: db
    try:
        client = TestClient(main.app)
        body = client.post("/api/agent/interpret", json={"text": "chips"}).json()
        assert body["spec"] is None and "killed" in body["questions"][0] and body["questions"][1] == "size?"

        def boom(supa):
            raise RuntimeError("no table")
        monkeypatch.setattr(main, "_latest_saved_map", boom)
        body = client.post("/api/agent/interpret", json={"text": "chips"}).json()
        assert body["spec"] == DRAFT and "no table" in body["preflight"]["error"]
    finally:
        main.app.dependency_overrides.clear()
