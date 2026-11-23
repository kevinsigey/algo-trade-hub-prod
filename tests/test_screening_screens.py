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


def test_an_interrupted_promotion_resumes_the_same_idea(client, monkeypatch):
    # CodeRabbit on #575: if a write fails midway (here: tracking), a retry
    # must finish the original handoff, not create a second idea.
    from tradehub.workshop import store as workshop_store

    c, fake = client
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: object())
    monkeypatch.setattr(main, "with_rule_bars", lambda spec, closes, start, bars_fn=None: closes)
    monkeypatch.setattr(main, "rule_series", lambda spec, start, fred=None, analyst_fn=None: {})
    monkeypatch.setattr(main, "workshop_div_yields", lambda spec, prices: {})
    runs = []
    monkeypatch.setattr(main, "run_test", lambda *a, **k: runs.append(1) or {"verdict": "PASS", "data_end": "2026-10-29"})
    real_track = workshop_store.track

    def flaky_track(*a, **k):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(workshop_store, "track", flaky_track)
    screen = c.post("/api/screening/screens", json={"spec": SPEC, "last_run": RUN}).json()
    try:
        c.post(f"/api/screening/screens/{screen['id']}/promote")
    except RuntimeError:
        pass  # TestClient re-raises the server error
    assert len(fake.store["ideas"]) == 1 and not fake.store["ideas"][0].get("tracked_at")
    assert fake.store["screens"][0]["promoted_idea_id"] == fake.store["ideas"][0]["id"]

    monkeypatch.setattr(workshop_store, "track", real_track)
    r = c.post(f"/api/screening/screens/{screen['id']}/promote")
    assert r.status_code == 200, r.text
    assert len(fake.store["ideas"]) == 1                 # no second idea
    assert len(fake.store["idea_runs"]) == 1 and len(runs) == 1  # no second run
    assert fake.store["ideas"][0]["tracked_at"] and fake.store["ideas"][0]["published_at"]
    assert c.post(f"/api/screening/screens/{screen['id']}/promote").status_code == 409



def test_a_failed_marker_write_is_recovered_by_the_idea_key(client, monkeypatch):
    # CodeRabbit on #575: if the screen's marker write fails right after the
    # idea is created, the retry finds the idea by its durable key, links it
    # and finishes -- never a second idea.
    from tradehub.screening import store as screen_store

    c, fake = client
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: object())
    monkeypatch.setattr(main, "with_rule_bars", lambda spec, closes, start, bars_fn=None: closes)
    monkeypatch.setattr(main, "rule_series", lambda spec, start, fred=None, analyst_fn=None: {})
    monkeypatch.setattr(main, "workshop_div_yields", lambda spec, prices: {})
    monkeypatch.setattr(main, "run_test", lambda *a, **k: {"verdict": "PASS", "data_end": "2026-10-29"})
    real_set = screen_store.set_promoted

    def failing_set(*a, **k):
        raise RuntimeError("marker write failed")

    monkeypatch.setattr(screen_store, "set_promoted", failing_set)
    screen = c.post("/api/screening/screens", json={"spec": SPEC, "last_run": RUN}).json()
    try:
        c.post(f"/api/screening/screens/{screen['id']}/promote")
    except RuntimeError:
        pass
    assert len(fake.store["ideas"]) == 1 and not fake.store["screens"][0].get("promoted_idea_id")

    monkeypatch.setattr(screen_store, "set_promoted", real_set)
    r = c.post(f"/api/screening/screens/{screen['id']}/promote")
    assert r.status_code == 200, r.text
    assert len(fake.store["ideas"]) == 1
    assert fake.store["screens"][0]["promoted_idea_id"] == fake.store["ideas"][0]["id"]
    assert fake.store["ideas"][0]["tracked_at"]


def _stub_backtest(monkeypatch, run_test=None):
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: object())
    monkeypatch.setattr(main, "with_rule_bars", lambda spec, closes, start, bars_fn=None: closes)
    monkeypatch.setattr(main, "rule_series", lambda spec, start, fred=None, analyst_fn=None: {})
    monkeypatch.setattr(main, "workshop_div_yields", lambda spec, prices: {})
    monkeypatch.setattr(main, "run_test", run_test or
                        (lambda *a, **k: {"verdict": "PASS", "data_end": "2026-10-29"}))


def test_promotion_ignores_an_unrelated_idea_holding_the_key(client, monkeypatch):
    # CodeRabbit on #575: the promotion marker is metadata, not something to
    # hunt for in editable idea prose. A note that happens to mention the key
    # must never turn an unrelated idea into the screen's basket.
    from tradehub.workshop import store as workshop_store

    c, fake = client
    _stub_backtest(monkeypatch)
    screen = c.post("/api/screening/screens", json={"spec": SPEC, "last_run": RUN}).json()
    key = f"[screen-promotion:{screen['id']}]"
    decoy = workshop_store.create_idea(fake, "Unrelated", f"my notes mention {key} by accident")
    r = c.post(f"/api/screening/screens/{screen['id']}/promote")
    assert r.status_code == 200, r.text
    assert r.json()["idea_id"] != decoy["id"]
    assert fake.store["screens"][0]["promoted_idea_id"] != decoy["id"]
    basket = fake.store["ideas"][-1]
    assert key not in basket["plain_words"]  # marker lives in dedicated metadata


def test_screen_list_carries_the_promoted_ideas_tracked_state(client, monkeypatch):
    # CodeRabbit on #575: the page must keep the retry available while the
    # linked idea is not yet tracked, so it needs that state from the API.
    from tradehub.workshop import store as workshop_store

    c, _ = client
    _stub_backtest(monkeypatch)
    real_track = workshop_store.track
    monkeypatch.setattr(workshop_store, "track", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("tracking hiccup")))
    screen = c.post("/api/screening/screens", json={"spec": SPEC, "last_run": RUN}).json()
    try:
        c.post(f"/api/screening/screens/{screen['id']}/promote")
    except RuntimeError:
        pass
    row = [s for s in c.get("/api/screening/screens").json() if s["id"] == screen["id"]][0]
    assert row["promoted_idea_id"] is not None
    assert row["promoted_tracked_at"] is None  # linked but untracked: retry still offered
    monkeypatch.setattr(workshop_store, "track", real_track)
    assert c.post(f"/api/screening/screens/{screen['id']}/promote").status_code == 200
    row = [s for s in c.get("/api/screening/screens").json() if s["id"] == screen["id"]][0]
    assert row["promoted_tracked_at"] is not None  # finished: link reads "tracked"


def test_resume_reports_the_original_basket_after_a_rerun(client, monkeypatch):
    # CodeRabbit on #575: a re-screen between attempts replaces last_run; the
    # retry must resume AAA/BBB and report AAA/BBB, not the new survivors.
    from tradehub.screening import store as screen_store
    from tradehub.workshop import store as workshop_store

    c, fake = client
    _stub_backtest(monkeypatch)
    real_track = workshop_store.track
    monkeypatch.setattr(workshop_store, "track", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("tracking hiccup")))
    screen = c.post("/api/screening/screens", json={"spec": SPEC, "last_run": RUN}).json()
    try:
        c.post(f"/api/screening/screens/{screen['id']}/promote")
    except RuntimeError:
        pass
    assert fake.store["idea_runs"][0]["spec"]["hold"] == ["AAA", "BBB"]
    screen_store.record_run(fake, screen["id"], {"footer": {}, "columns": [],
                                                 "survivors": ["CCC", "DDD"]})
    monkeypatch.setattr(workshop_store, "track", real_track)
    r = c.post(f"/api/screening/screens/{screen['id']}/promote")
    assert r.status_code == 200, r.text
    assert r.json()["survivors"] == ["AAA", "BBB"]
    tracked_id = fake.store["ideas"][0]["tracked_run_id"]
    run = [x for x in fake.store["idea_runs"] if x["id"] == tracked_id][0]
    assert run["spec"]["hold"] == ["AAA", "BBB"]


def test_resume_keeps_the_original_input_when_the_backtest_failed(client, monkeypatch):
    # CodeRabbit on #575: before a run is saved the original survivors must be
    # persisted, or a re-run with no survivors blocks the retry with a 409.
    from tradehub.screening import store as screen_store

    c, _ = client
    calls = []

    def flaky_run_test(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("backtest hiccup")
        return {"verdict": "PASS", "data_end": "2026-10-29"}

    _stub_backtest(monkeypatch, flaky_run_test)
    screen = c.post("/api/screening/screens", json={"spec": SPEC, "last_run": RUN}).json()
    try:
        c.post(f"/api/screening/screens/{screen['id']}/promote")
    except RuntimeError:
        pass
    screen_store.record_run(client[1], screen["id"], {"footer": {}, "columns": [], "survivors": []})
    r = c.post(f"/api/screening/screens/{screen['id']}/promote")
    assert r.status_code == 200, r.text
    assert r.json()["survivors"] == ["AAA", "BBB"]


def test_resume_saves_the_unsaved_variation_one_run(client, monkeypatch):
    # CodeRabbit on #575: insert succeeded but save failed. The retry must save
    # that run and finish -- never backtest and insert a second variation 1.
    from tradehub.workshop import store as workshop_store

    c, fake = client
    calls = []
    _stub_backtest(monkeypatch, lambda *a, **k: calls.append(1) or
                   {"verdict": "PASS", "data_end": "2026-10-29"})
    real_save = workshop_store.save_run
    monkeypatch.setattr(workshop_store, "save_run", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("save hiccup")))
    screen = c.post("/api/screening/screens", json={"spec": SPEC, "last_run": RUN}).json()
    try:
        c.post(f"/api/screening/screens/{screen['id']}/promote")
    except RuntimeError:
        pass
    assert len(fake.store["idea_runs"]) == 1 and not fake.store.get("idea_run_saves")
    monkeypatch.setattr(workshop_store, "save_run", real_save)
    r = c.post(f"/api/screening/screens/{screen['id']}/promote")
    assert r.status_code == 200, r.text
    assert len(fake.store["idea_runs"]) == 1 and len(calls) == 1  # no second run
    assert len(fake.store.get("idea_run_saves", [])) == 1
    assert fake.store["ideas"][0]["tracked_at"]
