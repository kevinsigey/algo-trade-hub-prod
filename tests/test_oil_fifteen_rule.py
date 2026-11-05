from tradehub import oil_fifteen_rule as rule


def test_buys_the_side_whose_edge_over_its_ask_clears_ten_points():
    assert rule.pick(0.60, yes_ask=0.48, yes_bid=0.46) == ("yes", 0.48)
    assert rule.pick(0.30, yes_ask=0.43, yes_bid=0.41) == ("no", 0.59)
    assert rule.pick(0.55, yes_ask=0.48, yes_bid=0.46) is None  # 7 points: no trade
    assert rule.pick(0.60, yes_ask=None, yes_bid=0.46) is None  # no quote, no trade
    assert rule.pick(0.99, yes_ask=0.985, yes_bid=0.98) is None  # outside the tradeable band


def test_pnl_is_per_contract_after_the_taker_fee():
    assert rule.pnl("yes", 0.48, 1) == round(1 - 0.48 - 0.07 * 0.48 * 0.52, 4)
    assert rule.pnl("no", 0.59, 1) == round(-0.59 - 0.07 * 0.59 * 0.41, 4)


def test_summary_splits_replayed_trades_from_forward_ones():
    trades = [{"pnl": 0.5, "frozen_at": "2026-11-05T10:00:00+00:00"},
              {"pnl": -0.4, "frozen_at": "2026-11-07T10:00:00+00:00"},
              {"pnl": 0.3, "frozen_at": "2026-11-07T11:00:00+00:00"}]
    out = rule.summarize(trades)
    assert out["replay"]["n"] == 1 and out["forward"]["n"] == 2
    assert out["forward"]["net_per_contract"] == -0.05
    assert out["forward"]["ready"] is False


class FakeSupa:
    """Only what record() reads, through the journal store's helpers."""


def test_record_joins_forecasts_to_settlements(monkeypatch):
    rows = {("oil_wti_15m", "wti-15m-v2"): [
        {"target": "a", "probability": 0.62, "payload": {"yes_ask": 0.50, "yes_bid": 0.48}, "frozen_at": "2026-11-07T10:05:00+00:00"},
        {"target": "b", "probability": 0.52, "payload": {"yes_ask": 0.50, "yes_bid": 0.48}, "frozen_at": "2026-11-07T10:20:00+00:00"},
        {"target": "c", "probability": 0.70, "payload": {"yes_ask": 0.50, "yes_bid": 0.48}, "frozen_at": "2026-11-07T10:35:00+00:00"},
    ]}
    monkeypatch.setattr(rule.store, "fetch_forecasts", lambda supa, f, v: rows.get((f, v), []))
    monkeypatch.setattr(rule.store, "fetch_settlements", lambda supa, targets: {"a": 1, "b": 0})
    out = rule.record(FakeSupa())
    assert out["forward"]["n"] == 1  # b is under the edge, c has not settled
    assert out["recent"][0]["series"] == "WTI" and out["recent"][0]["side"] == "yes"
    assert out["pending"] == 1


def test_the_route_serves_an_empty_record_when_the_journal_is_unreadable(monkeypatch):
    from fastapi.testclient import TestClient

    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    def boom(*_a, **_k):
        raise RuntimeError("journal down")

    monkeypatch.setattr(rule.store, "fetch_forecasts", boom)
    main.app.dependency_overrides[get_supabase] = lambda: None
    try:
        body = TestClient(main.app).get("/api/oil/fifteen-rule").json()
    finally:
        main.app.dependency_overrides.clear()
    assert body["unavailable"] is True and body["forward"]["n"] == 0 and body["rule"] == rule.RULE
