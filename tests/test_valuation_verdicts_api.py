"""API tests for the Phase 1 verdict surface: the feed shape (latest rendered
verdict per ticker + authority summary + watch flags + pending triggers),
the history endpoint (voids included), and the on-demand run's synchronous
declines (no sheet / no bands / stale / budget spent) plus its happy path."""
import threading
from datetime import datetime, timedelta, timezone

import pandas as pd
from fastapi.testclient import TestClient

from tradehub.api import admin, main
from tests.test_valuation_verdicts import FakeClient, _chat, _sheet_row


def _now_iso(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _verdict_row(**over):
    row = {
        "ticker": "AMGN", "rendered_at": _now_iso(hours=-2),
        "trigger": "on_demand", "status": "rendered", "void_reason": None,
        "judge": "free-ai-proposer", "proposer_model": "qwen-fake",
        "fact_sheet_id": 41, "fact_sheet_computed_at": "2026-11-08T04:00:00Z",
        "price": 460.42, "price_as_of": "2026-11-06",
        "bands": {"bear": 272.18, "base": 310.17, "bull": 317.92},
        "band_basis": "eps", "baseline_verdict": "short_zone_strong",
        "verdict": {"choice_id": "act_at_band_mid", "direction": "short",
                    "probability": 0.62, "rationale": "rich"},
        "proposer_pick": {"choice_id": "act_at_band_mid",
                          "direction": "short", "probability": 0.62},
        "choices": [], "rubric_weights": {}, "digest": "d",
        "bull_case": "b", "bear_case": "c",
        "options_inputs": {"expression": "debit_put_spread"},
        "frozen_peers": {"group": "biotechnology", "members": []},
        "falsifier": "Falsified if AMGN ...", "entry_price": 460.42,
        "target_price": 272.18, "debate_run_id": None,
    }
    row.update(over)
    return row


def _client(supa):
    from tradehub.api.dependencies import get_supabase as real_get_supabase

    main.app.dependency_overrides[admin.require_admin] = (
        lambda: {"email": "k@example.com", "is_admin": True})
    main.app.dependency_overrides[real_get_supabase] = lambda: supa
    return TestClient(main.app)


def _seeded():
    supa = FakeClient()
    supa.tables["valuation_verdicts"] = [
        _verdict_row(),
        _verdict_row(ticker="GILD", baseline_verdict="buy_zone",
                     verdict={"choice_id": "watch", "direction": "none",
                              "probability": None, "rationale": ""}),
        _verdict_row(ticker="VOIDCO", status="void", verdict=None,
                     void_reason="invented price"),
    ]
    # ids arrive via insert in production; the fake's seeded rows need them
    for i, row in enumerate(supa.tables["valuation_verdicts"], start=1):
        row["id"] = i
    supa.tables["valuation_verdict_grades"] = [{
        "id": 1, "verdict_id": 1, "horizon": 20,
        "verdict_relative_pass": True, "verdict_brier": 0.1444,
        "baseline_relative_pass": True, "baseline_brier": None,
        "proposer_relative_pass": True, "proposer_brier": 0.1444,
        "peer_excess_pct": 6.0, "index_excess_pct": 4.0,
        "mfe_pct": 21.0, "mae_pct": -8.0, "time_to_target_days": 15}]
    supa.tables["valuation_watch_state"] = [{
        "key": "held:big:AMGN", "kind": "held", "ticker": "AMGN",
        "state": {"flag": "potential_sell", "detail": "above_bull",
                  "book": "big", "symbol": "AMGN", "underlying": "AMGN",
                  "price": 460.42,
                  "bands": {"bear": 272.18, "base": 310.17, "bull": 317.92}}}]
    supa.tables["valuation_triggers"] = [{
        "id": 9, "ticker": "GILD", "kind": "new_guidance", "priority": 2,
        "state": "pending", "created_at": _now_iso(), "detail": {}}]
    return supa


def test_feed_shape_authority_flags_and_triggers():
    body = _client(_seeded()).get("/api/valuation-verdicts").json()
    assert body["authority"]["gate"] == 40
    assert body["authority"]["graded_verdicts"] == 1
    assert body["authority"]["relative_passes"] == 1
    assert body["authority"]["status"] == "display_only"
    tickers = [v["ticker"] for v in body["verdicts"]]
    assert tickers == ["AMGN", "GILD"]  # the void row is not a verdict card
    amgn = body["verdicts"][0]
    assert amgn["judge"] == "free-ai-proposer"
    assert amgn["zone"] == "short_zone_strong"
    assert amgn["grades"]["20"]["relative_pass"] is True
    assert amgn["grades"]["60"] == "pending"
    [flag] = body["watch"]["flags"]
    assert flag["flag"] == "potential_sell" and flag["book"] == "big"
    [trig] = body["watch"]["pending_triggers"]
    assert trig["ticker"] == "GILD" and trig["kind"] == "new_guidance"


def test_history_includes_voids():
    rows = _client(_seeded()).get("/api/valuation-verdicts/VOIDCO").json()
    assert len(rows) == 1 and rows[0]["status"] == "void"


class _SyncThread:
    def __init__(self, target=None, daemon=None, name=None, **_kw):
        self._target = target

    def start(self):
        self._target()


class _DS:
    def prices(self, tickers, years=1):
        idx = pd.bdate_range("2026-11-02", periods=5)
        return pd.DataFrame({t: [100.0, 101.0, 102.0, 103.0, 460.42]
                             for t in tickers}, index=idx)

    def implied_move(self, _ticker):
        return 9.0


def _run_client(monkeypatch, supa):
    from tradehub.screening import sources
    from tradehub.valuation import llm as val_llm
    from tradehub.valuation import run as val_run

    monkeypatch.setattr(threading, "Thread", _SyncThread)
    monkeypatch.setattr(sources, "DataStore", lambda *a, **k: _DS())
    monkeypatch.setattr(val_run, "compute", lambda *a, **k: [])
    monkeypatch.setattr(val_llm, "chat", _chat)
    return _client(supa)


def test_run_happy_path_lands_a_verdict(monkeypatch):
    supa = FakeClient()
    supa.tables["valuation_fact_sheets"] = [_sheet_row()]
    client = _run_client(monkeypatch, supa)
    r = client.post("/api/valuation-verdicts/run", json={"ticker": "AMGN"})
    assert r.status_code == 202 and r.json() == {"started": "AMGN"}
    [row] = supa.tables["valuation_verdicts"]
    assert row["status"] == "rendered" and row["judge"] == "free-ai-proposer"
    # a second run inside the reuse window returns the standing verdict
    r2 = client.post("/api/valuation-verdicts/run", json={"ticker": "AMGN"})
    assert r2.status_code == 200 and "reused" in r2.json()


def test_run_declines_are_422_with_reasons(monkeypatch):
    supa = FakeClient()
    client = _run_client(monkeypatch, supa)
    r = client.post("/api/valuation-verdicts/run", json={"ticker": "ZZZZ"})
    assert r.status_code == 422 and "no fact sheet" in r.json()["detail"]

    supa.tables["valuation_fact_sheets"] = [_sheet_row(stale=True)]
    r = client.post("/api/valuation-verdicts/run", json={"ticker": "AMGN"})
    assert r.status_code == 422 and "stale" in r.json()["detail"]

    supa.tables["valuation_fact_sheets"] = [
        _sheet_row(status="no_full_year_guide", bands=None,
                   baseline_verdict="no_bands", stale=False)]
    r = client.post("/api/valuation-verdicts/run", json={"ticker": "AMGN"})
    assert r.status_code == 422 and "no bands" in r.json()["detail"]
