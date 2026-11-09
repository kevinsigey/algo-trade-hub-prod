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


def test_no_trade_around_the_daily_futures_halt():
    # CME halts oil and gas futures 5-6 PM ET; the model's tape keeps trading, so its "edges" there are the gap
    # between two clocks. Replay Nov 4-5: 14 trades in 4:45-6:30 PM ET lost 1.5c each, 42 elsewhere made 9.1c.
    assert rule.in_halt("2026-11-05T22:05:00+00:00")       # 5:05 PM ET
    assert rule.in_halt("2026-11-05T21:50:00+00:00")       # 4:50 PM ET
    assert not rule.in_halt("2026-11-05T23:35:00+00:00")   # 6:35 PM ET
    assert not rule.in_halt("2026-11-05T15:05:00+00:00")   # 10:05 AM ET


def test_record_skips_halt_windows(monkeypatch):
    rows = {("oil_wti_15m", "wti-15m-v2"): [
        {"target": "h", "probability": 0.80, "payload": {"yes_ask": 0.50, "yes_bid": 0.48}, "frozen_at": "2026-11-07T22:05:00+00:00"},
        {"target": "d", "probability": 0.80, "payload": {"yes_ask": 0.50, "yes_bid": 0.48}, "frozen_at": "2026-11-07T15:05:00+00:00"},
    ]}
    monkeypatch.setattr(rule.store, "fetch_forecasts", lambda supa, f, v: rows.get((f, v), []))
    monkeypatch.setattr(rule.store, "fetch_settlements", lambda supa, targets: {t: 1 for t in targets})
    out = rule.record(FakeSupa())
    assert [t["target"] for t in out["recent"]] == ["d"]


def test_futures_open_matches_cme_hours():
    # November uses EST (UTC-5). Use UTC times that convert to the target ET times.
    assert rule.futures_open("2026-11-06T21:59:00+00:00") is True   # Fri 16:59 ET (21:59 UTC)
    assert rule.futures_open("2026-11-06T22:00:00+00:00") is False  # Fri 17:00 ET (22:00 UTC)
    assert rule.futures_open("2026-11-07T22:00:00+00:00") is False  # Sat noon ET (22:00 UTC)
    assert rule.futures_open("2026-11-08T22:59:00+00:00") is False  # Sun 17:59 ET (22:59 UTC)
    assert rule.futures_open("2026-11-08T23:00:00+00:00") is True   # Sun 18:00 ET (23:00 UTC)
    assert rule.futures_open("2026-11-04T22:30:00+00:00") is False  # Wed 17:30 ET (22:30 UTC)
    assert rule.futures_open("2026-11-04T23:00:00+00:00") is True   # Wed 18:00 ET (23:00 UTC)


def test_stats_counts_windows():
    trades = [
        {"pnl": 0.5, "frozen_at": "2026-11-07T10:05:00+00:00"},
        {"pnl": -0.4, "frozen_at": "2026-11-07T10:05:00+00:00"},  # same window
        {"pnl": 0.3, "frozen_at": "2026-11-07T10:20:00+00:00"},
    ]
    out = rule._stats(trades)
    assert out["windows"] == 2  # two distinct frozen_at values

    out_empty = rule._stats([])
    assert out_empty["windows"] == 0


def test_the_fee_is_the_records_own_cost_model():
    assert rule.fee(0.5) == 0.07 * 0.5 * 0.5
    assert rule.fee(0.51) == 0.07 * 0.51 * 0.49


def test_the_net_gate_refuses_a_gross_edge_the_fee_eats():
    # 10.5 points gross over the ask, but the taker fee at a 51c cost is ~1.75 points:
    # the old gate buys this, the net gate must not.
    assert rule.pick(0.615, yes_ask=0.51, yes_bid=0.49) == ("yes", 0.51)
    assert rule.pick_net(0.615, yes_ask=0.51, yes_bid=0.49) is None
    # 12 points gross leaves ~10.25 after the fee: still a buy, with the net edge reported.
    side, cost, edge = rule.pick_net(0.63, yes_ask=0.51, yes_bid=0.49)
    assert (side, cost) == ("yes", 0.51) and abs(edge - (0.12 - 0.07 * 0.51 * 0.49)) < 1e-9
    # The NO side nets its fee on the NO cost (1 - the YES bid), not on the YES price.
    assert rule.pick_net(0.30, yes_ask=0.43, yes_bid=0.41) is None  # 11 gross, ~9.3 net
    side, cost, edge = rule.pick_net(0.27, yes_ask=0.43, yes_bid=0.41)
    assert (side, cost) == ("no", 0.59) and abs(edge - (0.14 - 0.07 * 0.59 * 0.41)) < 1e-9
    assert rule.pick_net(0.60, yes_ask=None, yes_bid=0.46) is None  # no quote, no trade


def test_evaluate_names_why_a_window_was_skipped():
    buy = rule.evaluate(0.63, yes_ask=0.51, yes_bid=0.49,
                        frozen_at="2026-11-07T15:05:00+00:00")
    assert buy["action"] == "buy" and buy["side"] == "yes" and buy["reason"] is None
    thin = rule.evaluate(0.55, yes_ask=0.50, yes_bid=0.48,
                         frozen_at="2026-11-07T15:05:00+00:00")
    assert thin["action"] == "skip" and thin["reason"] == "no_edge"
    assert abs(thin["best_edge_net"] - (0.05 - 0.07 * 0.5 * 0.5)) < 1e-9
    noq = rule.evaluate(0.90, yes_ask=None, yes_bid=None,
                        frozen_at="2026-11-07T15:05:00+00:00")
    assert noq["action"] == "skip" and noq["reason"] == "no_quote"
    wide = rule.evaluate(0.90, yes_ask=0.995, yes_bid=0.99,
                         frozen_at="2026-11-07T15:05:00+00:00")
    assert wide["reason"] == "no_quote"  # outside the tradeable band counts as no quote
    halt = rule.evaluate(0.90, yes_ask=0.50, yes_bid=0.48,
                         frozen_at="2026-11-07T22:05:00+00:00")  # 5:05 PM ET
    assert halt["action"] == "skip" and halt["reason"] == "halt" and halt["side"] is None


def test_record_reports_the_gated_record_beside_the_raw_one(monkeypatch):
    rows = {("oil_wti_15m", "wti-15m-v2"): [
        {"target": "a", "probability": 0.63, "payload": {"yes_ask": 0.51, "yes_bid": 0.49}, "frozen_at": "2026-11-13T21:30:00+00:00"},
        {"target": "g", "probability": 0.615, "payload": {"yes_ask": 0.51, "yes_bid": 0.49}, "frozen_at": "2026-11-13T20:45:00+00:00"},
    ]}
    monkeypatch.setattr(rule.store, "fetch_forecasts", lambda supa, f, v: rows.get((f, v), []))
    monkeypatch.setattr(rule.store, "fetch_settlements", lambda supa, targets: {t: 1 for t in targets})
    out = rule.record(FakeSupa())
    assert out["forward"]["n"] == 2          # the raw record is untouched: both windows bought
    assert out["gate"]["forward"]["n"] == 1  # the fee-eaten window is not a gated buy
    assert out["gate"]["by_session"]["open"]["n"] == 1
    assert out["gate"]["by_session"]["closed"]["n"] == 0
    # The tracking sections fail soft to empty while their tables are absent.
    assert out["decisions"]["recorded"] == 0 and out["offsets"]["by_offset"] == []


class _Chain:
    """The supabase query chain store.select_all walks: select/order/range/execute."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a):
        return self

    def order(self, *_a):
        return self

    def range(self, lo, hi):
        self._slice = self._rows[lo:hi + 1]
        return self

    def execute(self):
        return type("R", (), {"data": self._slice})()


class TableSupa:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _Chain(self._tables.get(name, []))


def test_record_reads_the_decision_and_offset_tables(monkeypatch):
    monkeypatch.setattr(rule.store, "fetch_forecasts", lambda supa, f, v: [])
    monkeypatch.setattr(rule.store, "fetch_settlements", lambda supa, targets: {})
    supa = TableSupa({
        rule.DECISIONS_TABLE: [
            {"action": "buy", "reason": None}, {"action": "skip", "reason": "no_edge"},
            {"action": "skip", "reason": "no_edge"}, {"action": "skip", "reason": "stale_tape"},
        ],
        rule.OFFSETS_TABLE: [
            {"offset_min": 5, "target": "a", "edge_net": 0.12, "pnl": 0.4,
             "move_to_settle_bps": 30.0, "move_to_60m_bps": 55.0},
            {"offset_min": 5, "target": "b", "edge_net": 0.2, "pnl": -0.6,
             "move_to_settle_bps": -10.0, "move_to_60m_bps": 5.0},
            {"offset_min": 7, "target": "a", "edge_net": None, "pnl": None,
             "move_to_settle_bps": 25.0, "move_to_60m_bps": None},
        ],
    })
    out = rule.record(supa)
    d = out["decisions"]
    assert d["recorded"] == 4 and d["buy"] == 1 and d["skip"] == 3
    assert d["by_reason"] == {"no_edge": 2, "stale_tape": 1}
    by = {o["offset_min"]: o for o in out["offsets"]["by_offset"]}
    assert by[5]["windows"] == 2 and by[5]["priced"] == 2 and by[5]["n"] == 2
    assert by[5]["net_per_contract"] == -0.1 and by[5]["win_rate"] == 0.5
    assert by[5]["mean_move_to_settle_bps"] == 10.0 and by[5]["mean_move_to_60m_bps"] == 30.0
    assert by[7]["priced"] == 0 and by[7]["n"] == 0 and by[7]["net_per_contract"] is None


def test_record_returns_by_session_split(monkeypatch):
    # forward trades: one open (Fri 16:30), one closed (Sat 12:00), one open (Wed 18:30)
    # Use dates after PREREG_AT (2026-11-07T00:00:00+00:00)
    # Closed but not in halt: Saturday 12:00 ET (17:00 UTC) - futures_open=False, in_halt=False (12:00 < 16:45)
    # Open before halt: Friday 16:30 ET (21:30 UTC) - futures_open=True, in_halt=False
    # Open after halt: Wednesday 18:30 ET (23:30 UTC) - futures_open=True, in_halt=False
    rows = {("oil_wti_15m", "wti-15m-v2"): [
        {"target": "a", "probability": 0.62, "payload": {"yes_ask": 0.50, "yes_bid": 0.48}, "frozen_at": "2026-11-13T21:30:00+00:00"},  # Fri 16:30 ET (open, before halt)
        {"target": "b", "probability": 0.62, "payload": {"yes_ask": 0.50, "yes_bid": 0.48}, "frozen_at": "2026-11-14T17:00:00+00:00"},  # Sat 12:00 ET (closed, not in halt)
        {"target": "c", "probability": 0.62, "payload": {"yes_ask": 0.50, "yes_bid": 0.48}, "frozen_at": "2026-11-11T23:30:00+00:00"},  # Wed 18:30 ET (open, after halt)
    ]}
    monkeypatch.setattr(rule.store, "fetch_forecasts", lambda supa, f, v: rows.get((f, v), []))
    monkeypatch.setattr(rule.store, "fetch_settlements", lambda supa, targets: {t: 1 for t in targets})
    out = rule.record(FakeSupa())
    assert "by_session" in out
    assert out["by_session"]["open"]["n"] == 2
    assert out["by_session"]["closed"]["n"] == 1
    # windows in by_session
    assert out["by_session"]["open"]["windows"] == 2  # two distinct open windows
    assert out["by_session"]["closed"]["windows"] == 1
