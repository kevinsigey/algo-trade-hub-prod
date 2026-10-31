from datetime import date

import pytest
from fastapi.testclient import TestClient

from tradehub.api import admin, main
from tradehub.api.dependencies import get_supabase
from tradehub.workshop.data import UnknownSymbol
from workshop_fake import DB


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
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = c.post("/api/workshop/draft", json={"text": "gold beats stocks when rates rise"})
    assert r.status_code == 424
    body = r.json()
    assert body["reason"] == "no_key" and body["template"]["claim"] == "beats_benchmark"


def test_draft_ok(api, monkeypatch):
    c, _, _ = api
    from tradehub.workshop.spec import IdeaSpec
    monkeypatch.setattr(main, "draft_spec", lambda text: (IdeaSpec.model_validate(SPEC), "x/y:free"))
    r = c.post("/api/workshop/draft", json={"text": "gold"})
    assert r.status_code == 200 and r.json()["spec"]["hold"] == ["GLD"] and r.json()["model"] == "x/y:free"


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


PASS_RESULT = {"verdict": "PASS", "headline": "Did what it claims on the years it hadn't seen.", "data_end": "2026-10-29"}


@pytest.fixture
def passed(api, monkeypatch):
    """An idea whose only run PASSed; the gate's answer is set per test through `gate`."""
    c, db, _ = api
    monkeypatch.setattr(main, "run_test", lambda *a, **k: PASS_RESULT)
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "x"}).json()
    c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC})
    gate = {"status": "ready", "new_days": 70, "needed": 63, "claim": {"holds": True}, "size_ok": True, "reasons": []}
    seen = []
    monkeypatch.setattr(main, "workshop_daily_frame", lambda spec, closes, fred: "frame")

    def fake_gate(spec, frame, data_end, size_pct):
        seen.append((frame, str(data_end), size_pct))
        return {**gate, "size_ok": None if size_pct is None else gate["size_ok"]}
    monkeypatch.setattr(main, "gate_check", fake_gate)
    return c, db, idea["id"], gate, seen


def test_lifecycle_routes_need_admin():
    c = TestClient(main.app)
    for method, path in [("get", "/api/workshop/ideas/1/gate"), ("post", "/api/workshop/ideas/1/publish"),
                         ("post", "/api/workshop/ideas/1/live"), ("post", "/api/workshop/ideas/1/kill"),
                         ("post", "/api/workshop/labels")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_gate_reads_the_latest_pass(passed):
    c, _, i, _, seen = passed
    r = c.get(f"/api/workshop/ideas/{i}/gate", params={"size_pct": 20})
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert seen == [("frame", "2026-10-29", 20.0)]
    assert c.get("/api/workshop/ideas/99/gate").status_code == 404


def test_gate_fails_when_latest_run_did_not_pass(api):
    c, _, _ = api
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "x"}).json()
    c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC})  # RESULT is a FAIL
    out = c.get(f"/api/workshop/ideas/{idea['id']}/gate").json()
    assert out["status"] == "fails" and out["reasons"] == ["the latest run did not PASS"]


def test_go_live_once_and_only_when_ready(passed):
    c, db, i, gate, _ = passed
    gate["status"] = "waiting"
    assert c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 20}).status_code == 409
    gate["status"] = "ready"
    r = c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 20})
    assert r.status_code == 200 and r.json()["live_at"] and r.json()["live_run_id"] == 1
    first = db.db["ideas"][0]["live_at"]
    assert c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 10}).status_code == 409
    assert db.db["ideas"][0]["live_at"] == first and db.db["ideas"][0]["size_pct"] == 20
    assert c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 0}).status_code == 422


def test_publish_and_kill_are_once(passed):
    c, _, i, _, _ = passed
    assert c.post(f"/api/workshop/ideas/{i}/kill").status_code == 409  # not live yet
    assert c.post(f"/api/workshop/ideas/{i}/publish").status_code == 200
    assert c.post(f"/api/workshop/ideas/{i}/publish").status_code == 409
    c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 20})
    assert c.post(f"/api/workshop/ideas/{i}/kill").status_code == 200
    assert c.post(f"/api/workshop/ideas/{i}/kill").status_code == 409
    assert c.post("/api/workshop/ideas/99/publish").status_code == 404


def test_idea_detail_has_tag_and_shadow(passed):
    c, db, i, _, _ = passed
    got = c.get(f"/api/workshop/ideas/{i}").json()
    assert got["tag"] == f"idea-{i}-" and got["shadow"] is None
    c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 20})
    got = c.get(f"/api/workshop/ideas/{i}").json()
    assert got["shadow"]["days"] == 0 and got["shadow"]["failing"] is False


def test_labels(api):
    c, db, _ = api
    c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "x"})
    assert c.post("/api/workshop/labels", json={"order_id": "o-1", "idea_id": 1}).status_code == 200
    assert c.post("/api/workshop/labels", json={"order_id": "o-1", "idea_id": None}).status_code == 200
    assert c.post("/api/workshop/labels", json={"order_id": "o-1", "idea_id": 42}).status_code == 422
    assert [(r["idea_id"], r["by"]) for r in db.db["order_labels"]] == [(1, "kevin@example.com"),
                                                                       (None, "kevin@example.com")]


def test_auto_switch(passed, monkeypatch):
    c, db, i, _, _ = passed
    assert c.post(f"/api/workshop/ideas/{i}/auto", json={"on": True}).status_code == 409  # not live yet
    c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 20})
    r = c.post(f"/api/workshop/ideas/{i}/auto", json={"on": True})
    assert r.status_code == 200 and r.json()["auto_orders"] is True
    assert db.db["order_switches"][-1]["by"] == "kevin@example.com"
    monkeypatch.delenv("TRADEHUB_PAPER_ORDERS", raising=False)
    got = c.get(f"/api/workshop/ideas/{i}").json()
    assert got["idea"]["auto_orders"] is True and got["orders_enabled"] is False and got["orders"] == []
    assert c.post(f"/api/workshop/ideas/{i}/auto", json={"on": False}).json()["auto_orders"] is False
    assert c.post("/api/workshop/ideas/99/auto", json={"on": True}).status_code == 404


def test_auto_route_needs_admin():
    assert TestClient(main.app).post("/api/workshop/ideas/1/auto", json={"on": True}).status_code == 401


def test_intraday_run_fetches_daily_bars(api, monkeypatch):
    c, _, _ = api
    seen = []

    def bars(tickers, start):
        seen.append(tuple(tickers))
        return {}
    monkeypatch.setattr(main, "workshop_bars", bars)
    monkeypatch.setattr(main, "with_rule_bars", lambda spec, prices, start, bars_fn: (bars_fn(["GLD"], start), prices)[1]
                        if spec.exits.mode == "intraday" else prices)
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "x"}).json()
    spec = {**SPEC, "otherwise": "CASH", "claim": "beats_benchmark", "when": None,
            "exits": {"stop_loss_pct": 5, "mode": "intraday"}}
    assert c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": spec}).status_code == 200
    assert seen == [("GLD",)]


def test_rule_with_two_fred_ids_fetches_both(api):
    c, _, calls = api
    two = {**{k: v for k, v in SPEC.items() if k != "when"},
           "rules": {"enter": {"mode": "any", "conditions": [
               SPEC["when"], {"source": "fred", "series": "T10Y2Y", "measure": "level", "op": "<", "threshold": 0}]}}}
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "gold"}).json()
    r = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": two})
    assert r.status_code == 200 and calls[0]["fred"] == {"DGS10": "series", "T10Y2Y": "series"}


def test_analyst_rule_on_an_etf_is_422(api, monkeypatch):
    def none(t):
        raise UnknownSymbol(f"no analyst data for {t} (ETFs and funds have none)")
    monkeypatch.setattr(main, "workshop_analyst", none)
    etf = {"title": "XLE on upgrades", "hold": ["XLE"], "claim": "beats_benchmark",
           "rules": {"enter": {"conditions": [{"source": "analyst", "series": "XLE", "measure": "net_upgrades",
                                               "lookback_days": 63, "op": ">", "threshold": 0}]}}}
    c, _, calls = api
    idea = c.post("/api/workshop/ideas", json={"title": "XLE", "plain_words": "xle"}).json()
    r = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": etf})
    assert r.status_code == 422 and "ETFs" in r.json()["detail"] and calls == []
