"""Saved screens + promotion (Part A2): a screen saves its spec and last run,
re-runs, and promotes ONCE into a published, tracking Workshop idea whose spec
is the fixed survivor basket. The data layer and the backtest engine are
stubbed; the store runs against an in-memory Supabase fake."""

import pytest
from fastapi.testclient import TestClient

from tradehub.api import main
from tradehub.api.dependencies import get_supabase

SPEC = {"name": "demo", "universe": {"type": "list", "tickers": ["AAA", "BBB"]},
        "filters": [{"fn": "pe_ratio", "op": "lt", "value": 15}]}
RUN = {"footer": {"run_at": "2026-11-02T00:00:00Z", "survivors": 2},
       "columns": ["ticker", "pe_ratio"], "survivors": ["AAA", "BBB"]}


class FakeQuery:
    def __init__(self, store, table):
        self.store, self.table, self.filters = store, table, []

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def is_(self, col, val):
        self.filters.append((col, None if val == "null" else val))
        return self

    def order(self, col, desc=False):
        self.col, self.desc = col, desc
        return self

    def insert(self, row):
        rows = self.store.setdefault(self.table, [])
        row = {**row, "id": max([r.get("id", 0) for r in rows], default=0) + 1}
        rows.append(row)
        self.inserted = [row]
        return self

    def update(self, values):
        self.updates = values
        return self

    def delete(self):
        self.deleting = True
        return self

    def execute(self):
        rows = [r for r in self.store.get(self.table, [])
                if all(r.get(c) == v for c, v in self.filters)]
        if getattr(self, "inserted", None) is not None and hasattr(self, "inserted"):
            return type("R", (), {"data": self.inserted})()
        if getattr(self, "updates", None):
            for r in rows:
                r.update(self.updates)
        if getattr(self, "deleting", False):
            self.store[self.table] = [r for r in self.store.get(self.table, [])
                                      if r not in rows]
            return type("R", (), {"data": []})()
        if getattr(self, "col", None):
            rows.sort(key=lambda r: r.get(self.col) or 0, reverse=getattr(self, "desc", False))
        return type("R", (), {"data": rows})()


class FakeSupabase:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return FakeQuery(self.store, name)


@pytest.fixture
def client(monkeypatch):
    fake = FakeSupabase()
    main.app.dependency_overrides[main.admin.require_admin] = lambda: {"email": "k@example.com"}
    main.app.dependency_overrides[get_supabase] = lambda: fake
    yield TestClient(main.app), fake
    main.app.dependency_overrides.pop(main.admin.require_admin, None)
    main.app.dependency_overrides.pop(get_supabase, None)


def test_screen_crud_and_validation(client):
    c, _ = client
    bad = c.post("/api/screening/screens", json={"spec": {**SPEC, "filters": [{"fn": "nope", "op": "lt", "value": 1}]}})
    assert bad.status_code == 422 and "nope" in bad.json()["detail"]
    made = c.post("/api/screening/screens", json={"spec": SPEC, "last_run": RUN})
    assert made.status_code == 201
    screen = made.json()
    assert screen["name"] == "demo" and screen["last_run"]["survivors"] == ["AAA", "BBB"]
    listed = c.get("/api/screening/screens").json()
    assert listed[0]["last_run"] == {"run_at": "2026-11-02T00:00:00Z", "survivors": 2,
                                     "data_as_of": None, "sources": []}
    assert c.delete(f"/api/screening/screens/{screen['id']}").status_code == 200
    assert c.get(f"/api/screening/screens/{screen['id']}").status_code == 404


def test_promote_guards(client):
    c, _ = client
    screen = c.post("/api/screening/screens", json={"spec": SPEC}).json()
    r = c.post(f"/api/screening/screens/{screen['id']}/promote")
    assert r.status_code == 409 and "run the screen first" in r.json()["detail"]


def test_promote_builds_a_tracking_basket_idea(client, monkeypatch):
    c, fake = client
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: object())
    monkeypatch.setattr(main, "with_rule_bars", lambda spec, closes, start, bars_fn=None: closes)
    monkeypatch.setattr(main, "rule_series", lambda spec, start, fred=None, analyst_fn=None: {})
    monkeypatch.setattr(main, "workshop_div_yields", lambda spec, prices: {})
    monkeypatch.setattr(main, "run_test", lambda spec, prices, fred, variations, seed, div_yields=None:
                        {"verdict": "PASS", "data_end": "2026-10-29"})
    screen = c.post("/api/screening/screens", json={"spec": SPEC, "last_run": RUN}).json()
    r = c.post(f"/api/screening/screens/{screen['id']}/promote")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "PASS" and body["survivors"] == ["AAA", "BBB"]
    idea = fake.store["ideas"][0]
    assert idea["title"] == "Screen basket: demo"
    assert "AAA, BBB" in idea["plain_words"] and '"pe_ratio"' in idea["plain_words"]
    assert idea["published_at"] and idea["tracked_at"] and idea["tracked_run_id"] == body["run_id"]
    run = fake.store["idea_runs"][0]
    assert run["spec"]["hold"] == ["AAA", "BBB"] and run["spec"]["claim"] == "beats_benchmark"
    assert fake.store["idea_run_saves"]  # the promoted run is a saved run
    assert fake.store["screens"][0]["promoted_idea_id"] == body["idea_id"]
    again = c.post(f"/api/screening/screens/{screen['id']}/promote")
    assert again.status_code == 409  # set-once
