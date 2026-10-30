from datetime import date

import pytest
from fastapi.testclient import TestClient

from tradehub.api import admin, main
from tradehub.api.dependencies import get_supabase
from tradehub.workshop import draft as draft_mod
from tradehub.workshop.data import UnknownSymbol


class Q:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.sort, self.row = db, table, [], None, None

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def order(self, col, desc=False):
        self.sort = (col, desc)
        return self

    def insert(self, row):
        self.row = row
        return self

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        if self.row is not None:
            row = {"id": len(rows) + 1, "created_at": f"2026-10-30T0{len(rows)}:00:00Z", **self.row}
            rows.append(row)
            return type("R", (), {"data": [row]})()
        out = [r for r in rows if all(r.get(c) == v for c, v in self.filters)]
        if self.sort:
            out.sort(key=lambda r: r[self.sort[0]], reverse=self.sort[1])
        return type("R", (), {"data": out})()


class DB:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return Q(self.db, name)


SPEC = {"title": "Gold when rates rise", "hold": ["GLD"], "otherwise": "SPY", "claim": "beats_benchmark_when",
        "when": {"source": "fred", "series": "DGS10", "measure": "change", "op": ">", "threshold": 0.25}}
RESULT = {"verdict": "FAIL", "headline": "Did not do what it claims.", "data_end": "2026-10-29"}


@pytest.fixture
def api(monkeypatch):
    db = DB()
    main.app.dependency_overrides[get_supabase] = lambda: db
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    calls = []
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: ("closes", tuple(tickers)))
    monkeypatch.setattr(main, "workshop_fred", lambda series, start: "series")

    def fake_run(spec, closes, fred, *, variations, seed):
        calls.append({"variations": variations, "seed": seed, "fred": fred})
        return RESULT
    monkeypatch.setattr(main, "run_test", fake_run)
    yield TestClient(main.app), db, calls
    main.app.dependency_overrides.clear()


def test_every_route_needs_admin():
    c = TestClient(main.app)
    for method, path in [("post", "/api/workshop/draft"), ("post", "/api/workshop/ideas"), ("get", "/api/workshop/ideas"),
                         ("get", "/api/workshop/ideas/1"), ("post", "/api/workshop/ideas/1/runs")]:
        assert c.request(method.upper(), path, json={}).status_code == 401, path


def test_draft_without_key_is_424_with_template(api, monkeypatch):
    c, _, _ = api
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = c.post("/api/workshop/draft", json={"text": "gold beats stocks when rates rise"})
    assert r.status_code == 424
    body = r.json()
    assert body["reason"] == "no_key" and body["template"]["claim"] == "beats_benchmark"


def test_draft_ok(api, monkeypatch):
    c, _, _ = api
    from tradehub.workshop.spec import IdeaSpec
    monkeypatch.setattr(main, "draft_spec", lambda text: IdeaSpec.model_validate(SPEC))
    r = c.post("/api/workshop/draft", json={"text": "gold"})
    assert r.status_code == 200 and r.json()["spec"]["hold"] == ["GLD"] and r.json()["model"] == draft_mod.MODEL


def test_two_runs_are_variations_1_and_2(api):
    c, db, calls = api
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "gold when rates rise"}).json()
    r1 = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC, "draft_model": "claude-opus-5-5"})
    r2 = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC})
    assert r1.status_code == 200 and r2.status_code == 200
    assert [r1.json()["variation"], r2.json()["variation"]] == [1, 2]
    assert [x["variations"] for x in calls] == [1, 2] and calls[1]["seed"] == idea["id"] * 1000 + 2
    assert calls[0]["fred"] == {"DGS10": "series"}
    listed = c.get("/api/workshop/ideas").json()
    assert listed[0]["runs"] == 2 and listed[0]["latest_verdict"] == "FAIL"
    got = c.get(f"/api/workshop/ideas/{idea['id']}").json()
    assert [r["variation"] for r in got["runs"]] == [1, 2]


def test_bad_spec_is_422(api):
    c, _, _ = api
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "x"}).json()
    r = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": {**SPEC, "leverage": 3}})
    assert r.status_code == 422


def test_unknown_symbol_is_422_naming_it(api, monkeypatch):
    c, _, _ = api
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "x"}).json()

    def boom(tickers, start):
        raise UnknownSymbol("no daily prices for ZZZZ")
    monkeypatch.setattr(main, "workshop_closes", boom)
    r = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC})
    assert r.status_code == 422 and "ZZZZ" in r.json()["detail"]


def test_missing_idea_is_404(api):
    c, _, _ = api
    assert c.get("/api/workshop/ideas/99").status_code == 404
    assert c.post("/api/workshop/ideas/99/runs", json={"spec": SPEC}).status_code == 404


def test_fred_start_reaches_back_for_the_lookback(api):
    from tradehub.api.main import _fred_start
    assert _fred_start(date(2006, 1, 3)) <= date(2003, 1, 3)


def test_fred_start_survives_feb_29():
    from tradehub.api.main import _fred_start
    assert _fred_start(date(2008, 2, 29)) < date(2005, 3, 1)
