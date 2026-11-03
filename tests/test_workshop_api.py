from datetime import date

import pytest
from fastapi.testclient import TestClient

from tradehub.api import admin, main
from tradehub.api.dependencies import get_supabase
from tradehub.workshop.data import UnknownSymbol
from workshop_fake import DB


SPEC = {"title": "Gold when rates rise", "hold": ["GLD"], "otherwise": "SPY", "claim": "beats_benchmark_when",
        "when": {"source": "fred", "series": "DGS10", "measure": "change", "op": ">", "threshold": 0.25}}
RESULT = {"verdict": "FAIL", "headline": "Did not do what it claims.", "data_end": "2026-10-29",
          "shuffle": {"p": 0.001, "bar": 0.05}, "walk_forward": {"held": 4, "of": 4, "folds": []}}


@pytest.fixture
def api(monkeypatch):
    db = DB()
    main.app.dependency_overrides[get_supabase] = lambda: db
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    calls = []
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: ("closes", tuple(tickers)))
    monkeypatch.setattr(main, "workshop_fred", lambda series, start: "series")

    def fake_run(spec, closes, fred, *, variations, seed, div_yields=None):
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
    r = c.post("/api/workshop/draft", json={"text": "my cat likes the sunshine"})  # no play fits, no key
    assert r.status_code == 424
    body = r.json()
    assert body["reason"] == "no_key" and body["template"]["claim"] == "beats_benchmark"


def test_draft_ok(api, monkeypatch):
    c, _, _ = api
    from tradehub.workshop.spec import IdeaSpec
    monkeypatch.setattr(main, "draft_spec", lambda text: (IdeaSpec.model_validate(SPEC), "x/y:free", [], []))
    monkeypatch.setattr(main, "playbook_draft", lambda text: None)  # no play fits: the free-form draft writes it
    r = c.post("/api/workshop/draft", json={"text": "gold"})
    assert r.status_code == 200 and r.json()["spec"]["hold"] == ["GLD"] and r.json()["model"] == "x/y:free"
    assert r.json()["play"] is None


def test_draft_matches_a_play_first(api, monkeypatch):
    c, _, _ = api
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(main, "draft_spec", lambda text: 1 / 0)
    r = c.post("/api/workshop/draft", json={"text": "Oil as a ballast against the fall of the S&P or general index"})
    body = r.json()
    assert r.status_code == 200 and body["model"] == "playbook" and body["spec"]["hold"] == ["USO"]
    assert body["play"]["id"] == "hedge_when_market_falls" and body["play"]["why"]
    assert {a["id"] for a in body["alternatives"]} == {"ballast_basket", "commodity_trend"}
    assert all(a["spec"]["title"] for a in body["alternatives"])


def test_two_runs_are_variations_1_and_2(api):
    c, db, calls = api
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "gold when rates rise"}).json()
    r1 = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC, "draft_model": "claude-opus-5-5"})
    r2 = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC})
    assert r1.status_code == 200 and r2.status_code == 200
    assert [r1.json()["variation"], r2.json()["variation"]] == [1, 2]
    assert [x["variations"] for x in calls] == [1, 2] and calls[1]["seed"] == idea["id"] * 1000 + 2
    assert calls[0]["fred"] == {"DGS10": "series"}
    # The Workshop list reads saved runs only: two previews leave the idea unrun there.
    listed = c.get("/api/workshop/ideas").json()
    assert listed[0]["runs"] == 0 and listed[0]["latest_verdict"] is None
    c.post(f"/api/workshop/ideas/{idea['id']}/runs/{r1.json()['id']}/save")
    c.post(f"/api/workshop/ideas/{idea['id']}/runs/{r2.json()['id']}/save")
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


PASS_RESULT = {"verdict": "PASS", "headline": "Did what it claims on the years it hadn't seen.", "data_end": "2026-10-29",
               "shuffle": {"p": 0.001, "bar": 0.05}, "walk_forward": {"held": 4, "of": 4, "folds": []}}


@pytest.fixture
def passed(api, monkeypatch):
    """An idea whose only run PASSed; the gate's answer is set per test through `gate`."""
    c, db, _ = api
    monkeypatch.setattr(main, "run_test", lambda *a, **k: PASS_RESULT)
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "x"}).json()
    run = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC}).json()
    c.post(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/save")  # a recorded run, not a preview
    gate = {"status": "ready", "new_days": 70, "needed": 63, "claim": {"holds": True}, "size_ok": True, "reasons": []}
    seen = []
    monkeypatch.setattr(main, "workshop_daily_frame", lambda spec, closes, fred, div_yields=None: "frame")

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


def test_preview_counts_nowhere_until_saved(api, monkeypatch):
    """Save-by-choice (2026-11-02): a fresh run is a preview -- the gate, tracking and
    the public record all ignore it -- until the save endpoint stamps it. Saving is
    idempotent, and a run of another idea 404s."""
    c, _, _ = api
    monkeypatch.setattr(main, "run_test", lambda *a, **k: PASS_RESULT)
    monkeypatch.setattr(main, "workshop_daily_frame", lambda spec, closes, fred, div_yields=None: "frame")
    monkeypatch.setattr(main, "gate_check", lambda spec, frame, data_end, size_pct: {
        "status": "ready", "new_days": 70, "needed": 63, "claim": {"holds": True}, "size_ok": True, "reasons": []})
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "x"}).json()
    other = c.post("/api/workshop/ideas", json={"title": "Other", "plain_words": "y"}).json()
    run = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC}).json()
    assert run["saved_at"] is None
    gate = c.get(f"/api/workshop/ideas/{idea['id']}/gate").json()
    assert gate["status"] == "fails" and "no saved run yet" in gate["reasons"][0]
    assert c.post(f"/api/workshop/ideas/{idea['id']}/track", json={}).status_code == 409
    assert c.post(f"/api/workshop/ideas/{idea['id']}/track", json={"run_id": run["id"]}).status_code == 409
    assert c.post(f"/api/workshop/ideas/{other['id']}/runs/{run['id']}/save").status_code == 404
    saved = c.post(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/save")
    assert saved.status_code == 200 and saved.json()["saved_at"]
    assert c.post(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/save").status_code == 200  # idempotent
    assert c.get(f"/api/workshop/ideas/{idea['id']}/gate").json()["status"] == "ready"
    assert c.post(f"/api/workshop/ideas/{idea['id']}/track", json={}).status_code == 200


def test_gate_reads_the_latest_pass(passed):
    c, _, i, _, seen = passed
    r = c.get(f"/api/workshop/ideas/{i}/gate", params={"size_pct": 20})
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert seen == [("frame", "2026-10-29", 20.0)]
    assert c.get("/api/workshop/ideas/99/gate").status_code == 404


def test_gate_fails_when_latest_run_did_not_pass(api):
    c, _, _ = api
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "x"}).json()
    run = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC}).json()  # RESULT is a FAIL
    c.post(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/save")
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


def test_go_live_override_covers_the_day_wait_only(passed):
    # Kevin's deliberate override (2026-11-02): the 63-new-day wait can be
    # bypassed on his explicit call, and the bypass is recorded on the idea.
    c, db, i, gate, _ = passed
    gate.update({"status": "waiting", "new_days": 3, "claim": None})
    assert c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 20}).status_code == 409
    r = c.post(f"/api/workshop/ideas/{i}/live",
               json={"size_pct": 20, "override": True, "override_note": "Kevin's call 2026-11-02"})
    assert r.status_code == 200 and r.json()["live_at"]
    stored = db.db["ideas"][0]["gate"]
    assert stored["status"] == "overridden" and stored["override"]["by"] == "Kevin Sigey"
    assert stored["override"]["note"] == "Kevin's call 2026-11-02" and stored["override"]["gate_status_was"] == "waiting"


def test_override_refuses_a_failed_claim_or_oversize(passed):
    c, db, i, gate, _ = passed
    gate.update({"status": "fails", "claim": {"holds": False, "label": "fell on new data"}})
    assert c.post(f"/api/workshop/ideas/{i}/live",
                  json={"size_pct": 20, "override": True}).status_code == 409
    gate.update({"status": "waiting", "claim": None, "size_ok": False})
    assert c.post(f"/api/workshop/ideas/{i}/live",
                  json={"size_pct": 20, "override": True}).status_code == 409
    assert db.db["ideas"][0].get("live_at") is None


def test_publish_and_kill_are_once(passed):
    c, _, i, _, _ = passed
    assert c.post(f"/api/workshop/ideas/{i}/kill").status_code == 409  # not live yet
    assert c.post(f"/api/workshop/ideas/{i}/publish").status_code == 200
    assert c.post(f"/api/workshop/ideas/{i}/publish").status_code == 409
    c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 20})
    assert c.post(f"/api/workshop/ideas/{i}/kill").status_code == 200
    assert c.post(f"/api/workshop/ideas/{i}/kill").status_code == 409
    assert c.post("/api/workshop/ideas/99/publish").status_code == 404


def test_track_needs_a_pass_and_is_once(passed):
    c, db, i, _, _ = passed
    r = c.post(f"/api/workshop/ideas/{i}/track", json={})
    assert r.status_code == 200 and r.json()["tracked_at"] and r.json()["tracked_run_id"] == 1
    assert c.post(f"/api/workshop/ideas/{i}/track", json={}).status_code == 409
    got = c.get(f"/api/workshop/ideas/{i}").json()
    assert got["shadow"] is not None and got["shadow"]["days"] == 0  # the record exists before go-live
    assert c.post("/api/workshop/ideas/99/track", json={}).status_code == 404


def test_track_refuses_a_fail_run(api):
    c, _, _ = api
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "x"}).json()
    c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC})  # RESULT is a FAIL
    assert c.post(f"/api/workshop/ideas/{idea['id']}/track", json={}).status_code == 409


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


def _frame_and_prices():
    import numpy as np
    import pandas as pd
    idx = pd.bdate_range("2025-01-01", "2026-10-30")
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"ret": rng.normal(0, 0.01, len(idx)), "on": True, "bench": 0.0, "spy": 0.0, "exit": ""},
                         index=idx)
    prices = pd.DataFrame({t: 100.0 for t in ("GLD", "SPY", "QQQ", "IWM")}, index=idx)
    return frame, prices


def test_run_analysis_and_csv_stop_at_the_runs_data_end(api, monkeypatch):
    c, db, _ = api
    frame, prices = _frame_and_prices()
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: prices)
    monkeypatch.setattr(main, "workshop_daily_frame", lambda spec, p, fred, div_yields=None: frame)
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "gold"}).json()
    run = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC}).json()
    got = c.get(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/analysis").json()
    assert [y["year"] for y in got["years"]] == [2025, 2026] and got["data_end"] == "2026-10-29"
    assert got["rolling"][-1]["t"] == "2026-10-29"
    r = c.get(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/daily.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0] == "date,rule_on,held,idea_ret,bench_ret,spy_ret,exit,close_GLD,close_SPY"
    assert lines[-1].startswith("2026-10-29,1,")
    assert "attachment" in r.headers["content-disposition"]


def test_run_analysis_checks_the_run_belongs_to_the_idea(api):
    c, _, _ = api
    a = c.post("/api/workshop/ideas", json={"title": "Idea A", "plain_words": "a"}).json()
    b = c.post("/api/workshop/ideas", json={"title": "Idea B", "plain_words": "b"}).json()
    run = c.post(f"/api/workshop/ideas/{a['id']}/runs", json={"spec": SPEC}).json()
    assert c.get(f"/api/workshop/ideas/{b['id']}/runs/{run['id']}/analysis").status_code == 404
    assert c.get(f"/api/workshop/ideas/{a['id']}/runs/999/daily.csv").status_code == 404


def test_ticker_names(api, monkeypatch):
    c, _, _ = api
    names = {"GOLD": {"name": "Gold.com, Inc.", "kind": "stock"}, "GLD": {"name": "SPDR Gold Shares", "kind": "ETF"}}
    monkeypatch.setattr(main, "workshop_ticker_info", lambda t: names.get(t))
    r = c.get("/api/workshop/tickers", params={"symbols": "gold, GLD,NOPE"})
    assert r.json() == {"GOLD": names["GOLD"], "GLD": names["GLD"], "NOPE": None}
    assert c.get("/api/workshop/tickers", params={"symbols": ",".join(f"T{i}" for i in range(21))}).status_code == 422


def test_analysis_flags_drift_from_the_stored_verdict(api, monkeypatch):
    # Review: the recompute uses today's data; say when it no longer matches what the verdict judged.
    c, db, calls = api
    frame, prices = _frame_and_prices()
    frame["ret"] = 0.0
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: prices)
    monkeypatch.setattr(main, "workshop_daily_frame", lambda spec, p, fred, div_yields=None: frame)
    monkeypatch.setattr(main, "run_test", lambda *a, **k: {**RESULT, "curve": [{"t": "2025-01-01", "idea": 0.0, "benchmark": 0.0},
                                                                                {"t": "2026-10-29", "idea": 12.0, "benchmark": 0.0}]})
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "gold"}).json()
    run = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC}).json()
    got = c.get(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/analysis").json()
    assert got["drift_pts"] == pytest.approx(-12.0)
    header = c.get(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/daily.csv").text.splitlines()[0]
    assert header.startswith("date,rule_on,held,idea_ret,")


def test_draft_from_scratch_skips_the_playbook(api, monkeypatch):
    c, _, _ = api
    from tradehub.workshop.spec import IdeaSpec
    monkeypatch.setattr(main, "draft_spec", lambda text: (IdeaSpec.model_validate(SPEC), "x/y:free", [], []))
    r = c.post("/api/workshop/draft", json={"text": "Gold does better when stocks are down", "free": True})
    assert r.status_code == 200 and r.json()["play"] is None and r.json()["model"] == "x/y:free"


EVENT = {"kind": "event", "title": "XOM drifts up after beats", "tickers": ["XOM"], "event": "earnings", "when": "beat",
         "window": "drift_1_5", "direction": "up"}


def test_event_study_run_and_its_guards(api, monkeypatch):
    c, db, _ = api
    got = {}
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: ("closes", tuple(tickers)))
    monkeypatch.setattr(main, "workshop_earnings", lambda t: f"earnings:{t}")

    def fake_event_test(spec, closes, events, *, variations, seed):
        got.update(closes=closes, events=events, variations=variations)
        return {**RESULT, "kind": "event", "events": [{"date": "2026-10-30", "ticker": "XOM", "surprise": 4.9,
                                                       "ar0": 1.0, "car_1_3": 0.5, "car_1_5": 0.7, "car_1_10": 0.9,
                                                       "pre_5": -0.2}]}
    monkeypatch.setattr(main, "run_event_test", fake_event_test)
    idea = c.post("/api/workshop/ideas", json={"title": "XOM beats", "plain_words": "xom drifts up after beats"}).json()
    r = c.post(f"/api/workshop/ideas/{idea['id']}/event-runs", json={"spec": EVENT})
    assert r.status_code == 200 and r.json()["spec"]["kind"] == "event"
    assert got["closes"] == ("closes", ("XOM", "SPY")) and got["events"] == {"XOM": "earnings:XOM"} and got["variations"] == 1
    run = r.json()
    c.post(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/save")  # recorded: the gate reads saved runs
    # research only: the live gate refuses it, and the CSV is the event table
    gate = c.get(f"/api/workshop/ideas/{idea['id']}/gate").json()
    assert gate["status"] == "fails" and "research" in gate["reasons"][0]
    csv = c.get(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/daily.csv").text.splitlines()
    assert csv[0] == "date,ticker,surprise,ar0,car_1_3,car_1_5,car_1_10,pre_5" and csv[1].startswith("2026-10-30,XOM,4.9")
    assert c.get(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/analysis").status_code == 422


def test_macro_event_days_come_from_fred_releases(api, monkeypatch):
    c, _, _ = api
    got = {}
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: "closes")
    monkeypatch.setattr(main, "workshop_release_dates", lambda rid: f"release:{rid}")
    monkeypatch.setattr(main, "run_event_test", lambda spec, closes, events, **k: (got.update(events=events), RESULT)[1])
    idea = c.post("/api/workshop/ideas", json={"title": "Fed days", "plain_words": "spy on fed days"}).json()
    r = c.post(f"/api/workshop/ideas/{idea['id']}/event-runs",
               json={"spec": {**EVENT, "tickers": ["SPY", "QQQ"], "event": "fomc", "when": "all"}})
    assert r.status_code == 200 and got["events"] == {"*": "release:101"}


def test_event_study_on_an_etf_earnings_is_422(api, monkeypatch):
    c, _, _ = api
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: "closes")

    def none(t):
        raise UnknownSymbol(f"no earnings dates for {t} (ETFs and funds have none, or Yahoo unavailable)")
    monkeypatch.setattr(main, "workshop_earnings", none)
    idea = c.post("/api/workshop/ideas", json={"title": "XLE beats", "plain_words": "xle"}).json()
    r = c.post(f"/api/workshop/ideas/{idea['id']}/event-runs", json={"spec": {**EVENT, "tickers": ["XLE"]}})
    assert r.status_code == 422 and "XLE" in r.json()["detail"]


def test_public_pages_cope_with_a_published_event_study(api, monkeypatch):
    c, db, _ = api
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: "closes")
    monkeypatch.setattr(main, "workshop_earnings", lambda t: "e")
    monkeypatch.setattr(main, "run_event_test", lambda *a, **k: {**RESULT, "verdict": "PASS"})
    idea = c.post("/api/workshop/ideas", json={"title": "XOM beats", "plain_words": "xom"}).json()
    assert c.post(f"/api/workshop/ideas/{idea['id']}/event-runs", json={"spec": EVENT}).status_code == 200
    assert c.post(f"/api/workshop/ideas/{idea['id']}/publish").status_code == 200
    listed = TestClient(main.app).get("/api/ideas")
    assert listed.status_code == 200 and listed.json()[0]["claim"] is None
    record = TestClient(main.app).get(f"/api/ideas/{idea['id']}")
    assert record.status_code == 200
    assert all(r["claim"] is None for r in record.json()["runs"])


def test_ideas_summary_counts_every_ideas_latest_run(api, monkeypatch):
    # Critique L5: the public record shows the whole Workshop record, counts only.
    c, db, _ = api
    a = c.post("/api/workshop/ideas", json={"title": "Idea A", "plain_words": "a"}).json()
    b = c.post("/api/workshop/ideas", json={"title": "Idea B", "plain_words": "b"}).json()
    c.post("/api/workshop/ideas", json={"title": "Idea C", "plain_words": "c"})  # never run: not "tested"
    # The summary counts saved runs (save-by-choice): these are recorded runs.
    for idea_id, spec in ((a["id"], SPEC),):
        run = c.post(f"/api/workshop/ideas/{idea_id}/runs", json={"spec": spec}).json()  # FAIL (RESULT)
        c.post(f"/api/workshop/ideas/{idea_id}/runs/{run['id']}/save")
    monkeypatch.setattr(main, "run_test", lambda *x, **k: {**RESULT, "verdict": "PASS"})
    for idea_id in (a["id"], b["id"]):
        run = c.post(f"/api/workshop/ideas/{idea_id}/runs", json={"spec": SPEC}).json()  # PASS
        c.post(f"/api/workshop/ideas/{idea_id}/runs/{run['id']}/save")
    got = TestClient(main.app).get("/api/ideas/summary").json()
    assert got == {"tested": 2, "passed": 2, "failed": 0, "not_enough_data": 0, "published": 0}


def test_draft_dropped_ignores_the_benchmark_and_handles_event_studies(api, monkeypatch):
    # Review of #208: SPY named as "stocks" is the benchmark, not a dropped leg; an event-study draft has no hold list.
    c, _, _ = api
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = c.post("/api/workshop/draft", json={"text": "Gold does better when stocks are down"})
    assert r.status_code == 200 and r.json()["dropped"] == []
    r = c.post("/api/workshop/draft", json={"text": "XOM drifts up after earnings beats"})
    assert r.status_code == 200 and r.json()["spec"]["kind"] == "event" and r.json()["dropped"] == []
    r = c.post("/api/workshop/draft", json={"text": "hold RL, WSM, ABNB, DG, DLTR, BJ and MO as defensive ballast"})
    assert r.status_code == 200 and r.json()["spec"]["hold"] == ["RL", "WSM", "ABNB", "DG", "DLTR", "BJ", "MO"]
    assert r.json()["dropped"] == []


def test_go_live_on_the_big_book_writes_an_activation_not_the_idea_row(passed):
    # Kevin (2026-11-02): the books are independent -- going live on the $1M book
    # records an activation for that book and leaves the main book's state untouched.
    c, db, i, gate, _ = passed
    r = c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 5, "book": "big"})
    assert r.status_code == 200 and r.json()["live_at"] and r.json()["size_pct"] == 5
    assert db.db["ideas"][0].get("live_at") is None  # main book untouched
    assert db.db["book_activations"][0]["book"] == "big"
    # once per book: a second go-live on big refuses, main is still open
    assert c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 5, "book": "big"}).status_code == 409
    assert c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 20}).status_code == 200
    # auto + kill are per book too
    assert c.post(f"/api/workshop/ideas/{i}/auto", json={"on": True, "book": "big"}).status_code == 200
    assert db.db["book_activations"][0]["auto_orders"] is True
    assert c.post(f"/api/workshop/ideas/{i}/kill?book=big").status_code == 200
    assert db.db["book_activations"][0]["killed_at"]
    assert db.db["ideas"][0].get("killed_at") is None  # still live on main
    got = c.get(f"/api/workshop/ideas/{i}").json()
    assert got["books"]["big"]["live_at"] and got["books"]["big"]["killed_at"]
    assert got["books"]["main"]["live_at"] and got["books"]["main"]["size_pct"] == 20


def test_big_book_auto_needs_a_big_book_activation(passed):
    c, db, i, gate, _ = passed
    assert c.post(f"/api/workshop/ideas/{i}/auto", json={"on": True, "book": "big"}).status_code == 409
    assert c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 5, "book": "huge"}).status_code == 400


def test_go_live_refuses_a_size_that_cannot_trade_the_tested_options(passed, monkeypatch):
    c, db, i, _, _ = passed
    db.db["idea_runs"][0]["spec"] = {**db.db["idea_runs"][0]["spec"], "options": [{"underlying": "GLD", "kind": "call", "side": "buy", "strike_pct": 105, "days_to_expiry": 30}]}
    monkeypatch.setattr(main, "_play_check", lambda *a, **k: {"available": True, "structure_problems": ["SPY call: live would trade 0."]})
    r = c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 10})
    assert r.status_code == 409 and "trade 0" in r.json()["detail"]
    assert not db.db["ideas"][0].get("live_at")


def test_go_live_with_options_refuses_when_the_book_cannot_be_read(passed, monkeypatch):
    c, db, i, _, _ = passed
    db.db["idea_runs"][0]["spec"] = {**db.db["idea_runs"][0]["spec"], "options": [
        {"underlying": "GLD", "kind": "call", "side": "buy", "strike_pct": 105, "days_to_expiry": 30}]}
    monkeypatch.setattr(main, "_play_check", lambda *a, **k: {"available": False, "note": "No paper account"})
    r = c.post(f"/api/workshop/ideas/{i}/live", json={"size_pct": 10})
    assert r.status_code == 409 and "No paper account" in r.json()["detail"]
    assert not db.db["ideas"][0].get("live_at")
