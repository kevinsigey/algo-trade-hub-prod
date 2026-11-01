"""Phase-3 §5: the sniper re-grade's population rule and snapshot assembly."""

from datetime import date

import pandas as pd

from tradehub.scripts import shadow_performance as sp
from tradehub.scripts.sniper_regrade import build_verdict, grading_population


def _row(status, asset="BTC", prob=0.6, payload=None, at="2026-04-09T01:00:13+00:00"):
    return {"asset": asset, "created_at": at, "source_market_ticker": "KXBTC15M-X",
            "desired_side": "YES", "status": status, "model_probability_yes": prob,
            "payload": payload or {}}


def test_population_keeps_the_evaluators_rule():
    rows = [
        _row("signal_detected"),
        _row("inference_heartbeat", asset="ETH"),
        _row("execution_skip"),                                  # outcome row, not a signal
        _row("blocked"),
        _row("signal_detected", asset="SOL"),                    # not a graded asset
        _row("signal_detected", prob=None),                      # no probability
        _row("signal_detected", payload={"manual_test": True}),  # manual test
    ]
    pop = grading_population(rows)
    assert [r["status"] for r in pop] == ["signal_detected", "inference_heartbeat"]


def _signal(asset, prob, realized_yes, correct):
    base = pd.Timestamp("2026-04-09 00:00", tz="UTC")
    return sp.EvaluatedSignal(
        asset=asset, created_at=base + pd.Timedelta(hours=1), source_market_ticker="KX",
        desired_side="YES" if correct == (realized_yes == 1) else "NO",
        probability_yes=prob, base_hour=base, realized_hour=base + pd.Timedelta(hours=1),
        current_close=100.0, next_close=101.0 if realized_yes else 99.0,
        realized_yes=realized_yes, correct=correct,
        virtual_return_pct=1.0 if correct else -1.0,
    )


def test_verdict_assembly_matches_the_evaluators_summary_shape():
    evaluated = [_signal("BTC", 0.6, 1, True), _signal("BTC", 0.6, 0, False),
                 _signal("ETH", 0.4, 0, True)]
    verdict = build_verdict(
        by_status={"signal_detected": 2, "inference_heartbeat": 1, "execution_skip": 2},
        first_row="2026-04-08T21:39:32+00:00", last_row="2026-06-02T02:58:47+00:00",
        population=[{}, {}, {}],
        evaluated=evaluated,
        consideration={"evaluated_count": 3, "considered_count": 2, "dead_zone_count": 1},
        thresholds=sp.default_thresholds(),
        price_source="BTC: coinbase, ETH: coinbase",
        graded_on=date(2026, 11, 1),
    )
    assert verdict["record"] == "sniper_closed_record"
    assert verdict["graded_on"] == "2026-11-01"
    assert verdict["population"]["archived_rows"] == 5
    assert verdict["population"]["dead_zone_share"] == 1 / 3
    assert verdict["population"]["graded"] == 3
    assert verdict["overall"]["hit_rate"] == 2 / 3
    assert verdict["by_asset"]["BTC"]["count"] == 2
    assert verdict["by_asset"]["ETH"]["hit_rate"] == 1.0
    assert set(verdict["buckets"]) == {">=0.60", "<=0.45"}


def test_verdict_with_nothing_graded_stays_honest():
    verdict = build_verdict(
        by_status={}, first_row=None, last_row=None, population=[], evaluated=[],
        consideration={"evaluated_count": 0, "considered_count": 0, "dead_zone_count": 0},
        thresholds=sp.default_thresholds(), price_source="", graded_on=date(2026, 11, 1),
    )
    assert verdict["overall"]["hit_rate"] is None
    assert verdict["population"]["dead_zone_share"] is None


def test_verdict_endpoint_serves_the_snapshot_and_503s_when_missing(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from tradehub.api import main

    snap = tmp_path / "verdict.json"
    snap.write_text(json.dumps({"record": "sniper_closed_record", "graded_on": "2026-11-01"}))
    monkeypatch.setenv("TRADEHUB_SNIPER_VERDICT", str(snap))
    client = TestClient(main.app)
    ok = client.get("/api/crypto/sniper-verdict")
    assert ok.status_code == 200
    assert ok.json()["graded_on"] == "2026-11-01"

    monkeypatch.setenv("TRADEHUB_SNIPER_VERDICT", str(tmp_path / "absent.json"))
    missing = client.get("/api/crypto/sniper-verdict")
    assert missing.status_code == 503
    assert "sniper_regrade" in missing.json()["detail"]


def test_board_endpoint_delegates_to_the_board_builder(monkeypatch):
    from fastapi.testclient import TestClient

    import tradehub.crypto_board as board_mod
    from tradehub.api import main

    monkeypatch.setattr(board_mod, "live_board", lambda: {"generated_at": "x", "hourly": {}, "quarter": {}, "spots": {}})
    client = TestClient(main.app)
    resp = client.get("/api/crypto/board")
    assert resp.status_code == 200
    assert resp.json()["generated_at"] == "x"
