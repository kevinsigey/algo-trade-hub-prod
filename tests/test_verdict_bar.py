"""A2 (Claude review, 2026-11-10): a stored verdict was judged under the bar of
its day. The Workshop surfaces must say what the verdict is worth under the
CURRENT bar (p <= 0.01 and the claim held in 3 of 4 walk-forward folds,
Kevin 2026-11-03) and which bar each run was actually judged under. The stored
verdict itself is history and never changes."""
import pytest
from fastapi.testclient import TestClient

from tradehub.api import admin, main
from tradehub.api.dependencies import get_supabase
from tradehub.workshop import registry, store
from workshop_fake import DB


def _run(verdict="PASS", p=0.005, wf=None, battery=None, bar=0.01):
    result = {"verdict": verdict, "shuffle": {"p": p, "bar": bar, "beats_pct": 99.0,
                                              "permutations": 1000, "seed": 1},
              "headline": "h", "data_end": "2026-10-29"}
    if wf is not None:
        result["walk_forward"] = wf
    if battery is not None:
        result["battery"] = battery
    return {"verdict": verdict, "result": result}


WF_OK = {"held": 3, "of": 4, "folds": []}
WF_SHORT = {"held": 2, "of": 4, "folds": []}


def test_pass_at_the_old_bar_fails_the_current_one():
    now = registry.run_verdict_now(_run(p=0.029, wf=WF_OK, bar=0.05))
    assert now["verdict_now"] == "FAIL" and now["p_ok"] is False and now["wf_ok"] is True
    assert now["p"] == 0.029


def test_pass_under_the_current_bar_stands():
    now = registry.run_verdict_now(_run(p=0.009, wf=WF_OK))
    assert now["verdict_now"] == "PASS" and now["p_ok"] is True and now["wf_ok"] is True


def test_pass_short_on_folds_fails():
    now = registry.run_verdict_now(_run(p=0.001, wf=WF_SHORT))
    assert now["verdict_now"] == "FAIL" and now["wf_ok"] is False and now["p_ok"] is True


def test_pass_never_fold_judged_stands_with_the_leg_unjudged():
    # Pre-walk-forward runs were never fold-tested; history says so instead of
    # failing a leg that was never run. (The LATEST-run standing in
    # registry.adjusted stays stricter: unverifiable durability fails there.)
    now = registry.run_verdict_now(_run(p=0.001, wf=None))
    assert now["verdict_now"] == "PASS" and now["wf_ok"] is None


def test_fail_and_ned_stand_as_stored():
    assert registry.run_verdict_now(_run(verdict="FAIL", p=0.5, wf=WF_SHORT))["verdict_now"] == "FAIL"
    assert registry.run_verdict_now(_run(verdict="NOT ENOUGH DATA", p=None))["verdict_now"] == "NOT ENOUGH DATA"


def test_event_battery_p_is_the_runs_p():
    bat = {"type": "event", "p": 0.02, "verdict": "PASS"}
    now = registry.run_verdict_now(_run(p=0.001, wf=WF_OK, battery=bat))
    assert now["p"] == 0.02 and now["verdict_now"] == "FAIL"


def test_basket_battery_verdict_stands_as_stored():
    bat = {"type": "basket", "verdict": "PASS"}
    now = registry.run_verdict_now(_run(battery=bat))
    assert now["verdict_now"] == "PASS" and now["p_ok"] is None and now["battery"] == "basket"


def test_adjusted_still_demotes_a_latest_pass_with_no_folds():
    # adjusted() semantics are the go-live gate's; A2 must not soften them.
    out = registry.adjusted({7: _run(p=0.001, wf=None)})
    assert out[7]["verdict_now"] == "FAIL" and out[7]["wf_ok"] is None


def test_insert_run_stamps_the_bar_it_was_judged_under():
    db = DB()
    row = store.insert_run(db, 1, 1, {"hold": ["GLD"]}, None,
                           {"verdict": "PASS", "data_end": "2026-10-29",
                            "shuffle": {"p": 0.001, "bar": 0.05}})
    bar = row["result"]["bar"]
    assert bar["p_max"] == 0.01 and bar["wf_min_share"] == 0.75 and bar["shuffle_bar"] == 0.05


# ── API surfaces ─────────────────────────────────────────────────────────────

SPEC = {"title": "Gold when rates rise", "hold": ["GLD"], "otherwise": "SPY", "claim": "beats_benchmark_when",
        "when": {"source": "fred", "series": "DGS10", "measure": "change", "op": ">", "threshold": 0.25}}
LEGACY_PASS = {"verdict": "PASS", "headline": "Did what it claims.", "data_end": "2026-10-29",
               "shuffle": {"p": 0.029, "bar": 0.05}, "walk_forward": {"held": 4, "of": 4, "folds": []}}


@pytest.fixture
def api(monkeypatch):
    db = DB()
    main.app.dependency_overrides[get_supabase] = lambda: db
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: ("closes", tuple(tickers)))
    monkeypatch.setattr(main, "workshop_fred", lambda series, start: "series")
    monkeypatch.setattr(main, "run_test", lambda spec, closes, fred, **kw: LEGACY_PASS)
    yield TestClient(main.app), db
    main.app.dependency_overrides.clear()


def _idea_with_saved_run(c):
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "gold when rates rise"}).json()
    r = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC})
    assert r.status_code == 200
    c.post(f"/api/workshop/ideas/{idea['id']}/runs/{r.json()['id']}/save")
    return idea


def test_idea_page_run_carries_its_current_bar_verdict(api):
    c, _ = api
    idea = _idea_with_saved_run(c)
    got = c.get(f"/api/workshop/ideas/{idea['id']}").json()
    run = got["runs"][0]
    assert run["verdict"] == "PASS"               # as run: history, unchanged
    assert run["verdict_now"] == "FAIL"           # under the current bar
    assert run["p_ok"] is False and run["wf_ok"] is True
    assert run["result"]["bar"]["shuffle_bar"] == 0.05  # the bar it was judged under


def test_idea_list_carries_verdict_now(api):
    c, _ = api
    _idea_with_saved_run(c)
    listed = c.get("/api/workshop/ideas").json()
    assert listed[0]["latest_verdict"] == "PASS" and listed[0]["verdict_now"] == "FAIL"


def test_summary_counts_verdicts_under_the_current_bar(api):
    c, _ = api
    _idea_with_saved_run(c)
    body = c.get("/api/workshop/dashboard").json()
    counts = body["runs"]["latest_verdicts"]
    assert counts.get("PASS", 0) == 0 and counts.get("FAIL", 0) == 1
    assert body["runs"]["latest_verdicts_as_run"].get("PASS") == 1
