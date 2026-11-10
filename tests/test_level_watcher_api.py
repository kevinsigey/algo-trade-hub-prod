"""Read-API tests for /api/level-watcher (Spec D, Stage 1): the stage
and rung cap are stated up front, the CPI blackout gap rides the
payload, watches/fires/alerts pass through, and a governor group with
unset numbers says so in plain words."""
from fastapi.testclient import TestClient

from tradehub.api import admin, main

TABLES = {
    "level_watches": [
        {"id": 1, "name": "TEST — harness watch", "family": "test-family",
         "kind": "level", "instrument": "SPY", "trigger_type": "cross_up",
         "level": 100.0, "intent": "long", "rung": 3, "enabled": True,
         "governor_group": None}],
    "watcher_fires": [
        {"id": 1, "watch_id": 1, "family": "test-family",
         "instrument": "SPY", "session_date": "2026-11-09",
         "rung_effective": 1, "trigger_price": 100.60}],
    "watcher_alerts": [
        {"id": 1, "kind": "trigger", "watch_id": 1, "status": "pending",
         "title": "Level watcher: SPY fired (Rung 1 alert)",
         "body": "SPY cross_up through 100.0"}],
    "watcher_heartbeats": [
        {"id": 1, "at": "2999-01-01T00:00:00+00:00",
         "session_date": "2999-01-01"}],
    "watcher_governor_groups": [
        {"name": "g1", "standard_unit_usd": None,
         "daily_profit_target_usd": None, "daily_loss_stop_usd": None}],
    "watcher_governor_state": [],
    "watcher_family_state": [],
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


def test_surface_states_stage_rung_cap_gap_and_record():
    r = _client().get("/api/level-watcher")
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == 1 and body["rung_cap"] == 1
    assert body["mode"] == "rung1_alerts_only"
    assert body["cpi_blackout_gap"] is True
    assert [w["name"] for w in body["watches"]] == ["TEST — harness watch"]
    assert body["fires"][0]["rung_effective"] == 1
    assert [a["kind"] for a in body["alerts_pending"]] == ["trigger"]
    gov = body["governors"][0]
    assert gov["name"] == "g1" and gov["numbers_set"] is False
    assert "not set" in gov["note"]
