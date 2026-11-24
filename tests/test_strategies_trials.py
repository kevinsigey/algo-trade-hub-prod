"""GET /api/strategies/trials: one row per non-15-minute shadow, built
from the existing evaluators, each fail-soft on its own."""
from fastapi.testclient import TestClient

from tradehub.api import main
from tradehub.api.dependencies import get_supabase

TABLES = {
    "journal_scores": [{"forecaster": "oil_wti_hourly", "forecaster_version": "wti-hourly-v7-rv-shadow",
                        "n_settled": 37}],
    "band_crossings": [{"action": "starter", "score_20": 0.5}, {"action": "add", "score_20": -0.1},
                       {"action": "none", "score_20": 9}],
    "watcher_family_state": [{"family": "a", "graded_count": 7, "demoted_at": None},
                             {"family": "b", "graded_count": 20, "demoted_at": "2026-11-20"}],
    "valuation_verdict_grades": [
        {"verdict_id": 1, "horizon": 20, "verdict_relative_pass": True, "verdict_brier": 0.2},
        {"verdict_id": 2, "horizon": 20, "verdict_relative_pass": False, "verdict_brier": 0.3}],
}


class _Q:
    def __init__(self, name):
        if name == "leaps_shadow_pairs":
            raise RuntimeError("relation does not exist")
        self.rows = list(TABLES.get(name, []))

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Supa:
    def table(self, name):
        return _Q(name)


def test_trials_rows_from_existing_evaluators():
    main.app.dependency_overrides[get_supabase] = lambda: _Supa()
    try:
        body = TestClient(main.app).get("/api/strategies/trials").json()
    finally:
        main.app.dependency_overrides.pop(get_supabase, None)
    rows = {r["id"]: r for r in body["trials"]}
    assert rows["oil-hourly-v7"]["n"] == 37 and rows["oil-hourly-v7"]["needed"] == 300
    assert rows["band-crossing"]["n"] == 2 and rows["band-crossing"]["status"] == "recording"
    assert rows["band-crossing"]["score"] == 0.2
    assert rows["level-watcher"]["n"] == 20 and "1 demoted" in rows["level-watcher"]["note"]
    assert rows["valuation-debates"]["n"] == 1 and rows["valuation-debates"]["needed"] == 40
    # A missing store reads as no public read, never a 500 and never a borrowed number.
    assert rows["leaps"]["status"] == "no_read" and rows["leaps"]["n"] is None
