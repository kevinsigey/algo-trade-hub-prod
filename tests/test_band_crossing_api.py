"""Read-API tests for /api/band-crossings (Spec C, log-only): the mode is
stated up front, the falsifier counter rides along, crossings pass through
verbatim."""
from fastapi.testclient import TestClient

from tradehub.api import admin, main

TABLES = {
    "band_crossing_controls": [
        {"scope": "global", "orders_enabled": False, "note": "log-only"}],
    "band_crossings": [
        {"id": 2, "ticker": "CVS", "book": "main", "action": "starter",
         "zone": "base", "score_20": None, "mode": "log_only",
         "pc_outcome": "would_pass"},
        {"id": 1, "ticker": "CEG", "book": "big", "action": "none",
         "zone": "above_bull", "score_20": None, "mode": "log_only",
         "suppress_reason": "no_t1_classification"}],
    "band_crossing_scans": [
        {"id": 1, "kind": "baseline", "mode": "log_only",
         "banded_names": 21, "crossings_written": 0}],
}


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def order(self, col, desc=False):
        self._rows = sorted(self._rows, key=lambda r: r.get(col) or 0,
                            reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _Resp(self._rows)


class _Supa:
    def table(self, name):
        return _Query(list(TABLES.get(name, [])))


def _client():
    from tradehub.api.dependencies import get_supabase as real_get_supabase
    main.app.dependency_overrides[admin.require_admin] = (
        lambda: {"email": "k@example.com", "is_admin": True})
    main.app.dependency_overrides[real_get_supabase] = lambda: _Supa()
    return TestClient(main.app)


def test_surface_states_log_only_and_the_record():
    r = _client().get("/api/band-crossings")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "log_only" and body["orders_enabled"] is False
    assert body["falsifier"] == {"gate": 20, "graded": 0,
                                 "mean_score": None, "status": "accruing"}
    assert [c["ticker"] for c in body["crossings"]] == ["CVS", "CEG"]
    assert body["scans"][0]["kind"] == "baseline"
