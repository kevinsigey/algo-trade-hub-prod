"""Closing-line value: close on the row's own side, missing is None, never 0."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tradehub import settlement, track_record
from tradehub.backtest.kalshi_history import KalshiHistoryClient

LOG_AT = "2026-11-20T17:00:00+00:00"
CLOSE_AT = "2026-11-20T21:00:00+00:00"


def _row(**overrides):
    row = {
        "id": "r1", "status": "OPEN", "result": "yes", "market_ticker": "KXGAS-26NOV20",
        "our_prob": 0.7, "market_prob": 0.5, "as_of": LOG_AT,
        "engine": "gas", "engine_version": "v1",
    }
    row.update(overrides)
    return row


def _close(**overrides):
    close = {"yes_prob": 0.6, "source": "candle_60m", "at": CLOSE_AT}
    close.update(overrides)
    return close


def _settled_row(id_, prob, market_prob, result, close=None):
    outcome = 1 if result == "yes" else 0
    return {
        **_row(id=id_, our_prob=prob, market_prob=market_prob, result=result),
        "brier": round((prob - outcome) ** 2, 5),
        "market_brier": round((market_prob - outcome) ** 2, 5),
        "settlement_payload": {"market": {"status": "finalized", "result": result}, **({"close": close} if close else {})},
    }


# --- CLV math (port of predictor-hub stats.clv_points) ---


def test_clv_points_yes_side_is_close_minus_market():
    assert settlement.clv_points(_row(our_prob=0.7), _close(yes_prob=0.6)) == pytest.approx(0.1)


def test_clv_points_no_side_is_market_minus_close():
    # our_prob below the market means the favored side is NO; the same 0.6 YES
    # close is a 0.4 NO close, so this row was late, not early.
    assert settlement.clv_points(_row(our_prob=0.3), _close(yes_prob=0.6)) == pytest.approx(-0.1)


def test_clv_points_missing_close_is_none_not_zero():
    assert settlement.clv_points(_row(), None) is None
    assert settlement.clv_points(_row(), {}) is None
    assert settlement.clv_points(_row(), _close(yes_prob=None)) is None
    assert settlement.clv_points(_row(market_prob=None), _close()) is None
    assert settlement.clv_points(_row(our_prob=None), _close()) is None


def test_clv_points_canceled_row_has_no_clv():
    assert settlement.clv_points(_row(status="CANCELED", result=None), _close()) is None


def test_clv_points_close_seen_before_log_is_none():
    early = _close(at="2026-11-20T16:00:00+00:00")
    assert settlement.clv_points(_row(), early) is None
    # A close observed at the same instant the row was logged is still a close.
    assert settlement.clv_points(_row(), _close(at=LOG_AT)) == pytest.approx(0.1)


# --- public candlesticks ---


def _candle(ts, *, bid=None, ask=None, price=None):
    raw = {"end_period_ts": int(ts)}
    if bid is not None:
        raw["yes_bid"] = {"close": str(bid)}
    if ask is not None:
        raw["yes_ask"] = {"close": str(ask)}
    if price is not None:
        raw["price"] = {"close": str(price)}
    return raw


def _ts(hour):
    return int(datetime(2026, 11, 20, hour, tzinfo=UTC).timestamp())


def test_fetch_closing_price_uses_last_candle_at_or_before_close_and_bid_ask_midpoint():
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append((url, params))
        return {"candlesticks": [
            _candle(_ts(19), bid=0.40, ask=0.42),
            _candle(_ts(20), bid=0.50, ask=0.60),
            _candle(_ts(21), bid=0.88, ask=0.92),
            _candle(_ts(22), bid=0.99, ask=0.99),
        ]}

    close = settlement.fetch_closing_price(
        "KXGAS", "KXGAS-26NOV20", CLOSE_AT,
        client=KalshiHistoryClient(get_json=fake_get),
    )
    assert close == {"yes_prob": pytest.approx(0.9), "source": "candle_60m", "at": CLOSE_AT}
    url, params = calls[0]
    assert url.endswith("/series/KXGAS/markets/KXGAS-26NOV20/candlesticks")
    assert params["period_interval"] == 60
    assert params["end_ts"] == _ts(21)


def test_fetch_closing_price_falls_back_to_price_close():
    def fake_get(url, params=None, **kwargs):
        return {"candlesticks": [_candle(_ts(21), price=0.42)]}

    close = settlement.fetch_closing_price(
        "KXGAS", "KXGAS-26NOV20", CLOSE_AT,
        client=KalshiHistoryClient(get_json=fake_get),
    )
    assert close["yes_prob"] == pytest.approx(0.42)


def test_fetch_closing_price_no_eligible_candle_is_none():
    def fake_get(url, params=None, **kwargs):
        return {"candlesticks": [_candle(_ts(22), price=0.42)]}

    assert settlement.fetch_closing_price(
        "KXGAS", "KXGAS-26NOV20", CLOSE_AT,
        client=KalshiHistoryClient(get_json=fake_get),
    ) is None


# --- settlement pass: injected close fetch, failure isolation ---


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, io):
        self.io = io
        self.filters = {}
        self.payload = None

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def order(self, *_a):
        return self

    def range(self, *_a):
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def execute(self):
        matched = [r for r in self.io.rows if all(r.get(k) == v for k, v in self.filters.items())]
        if self.payload is None:
            return _Result(matched)
        for row in matched:
            row.update(self.payload)
            self.io.updates.append({**self.payload, "id": row["id"]})
        return _Result(matched)


class _Supa:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def table(self, name):
        assert name == "predictions"
        return _Query(self)


def _market(result="yes", *, close_time=CLOSE_AT):
    return {"market": {"status": "finalized", "result": result, "series_ticker": "KXGAS", "close_time": close_time}}


def test_run_settlement_pass_stores_close_once_per_ticker():
    rows = [_row(id="a", our_prob=0.7), _row(id="b", our_prob=0.7)]
    calls = []

    def fetch_close(series, ticker, close_time):
        calls.append((series, ticker, close_time))
        return _close()

    supa = _Supa(rows)
    summary = settlement.run_settlement_pass(supa, lambda _t: _market(), fetch_close=fetch_close)
    assert summary["settled"] == 2
    assert calls == [("KXGAS", "KXGAS-26NOV20", CLOSE_AT)]
    assert all(u["settlement_payload"]["close"] == _close() for u in supa.updates)


def test_run_settlement_pass_close_fetch_error_does_not_break_settlement(caplog):
    def boom(series, ticker, close_time):
        raise RuntimeError("429")

    supa = _Supa([_row(), _row(id="b")])
    with caplog.at_level("WARNING"):
        summary = settlement.run_settlement_pass(supa, lambda _t: _market(), fetch_close=boom)
    assert summary["settled"] == 2
    assert all("close" not in u["settlement_payload"] for u in supa.updates)
    assert len([r for r in caplog.records if "KXGAS-26NOV20" in r.message]) == 1


def test_run_settlement_pass_canceled_row_gets_no_close():
    calls = []

    def fetch_close(series, ticker, close_time):
        calls.append(ticker)
        return _close()

    supa = _Supa([_row()])
    summary = settlement.run_settlement_pass(supa, lambda _t: _market(result=None), fetch_close=fetch_close)
    assert summary["canceled"] == 1
    assert calls == []
    assert "close" not in supa.updates[0]["settlement_payload"]


# --- track record summary ---


def test_compute_engine_summary_clv_math_on_own_side():
    rows = [
        _settled_row("a", 0.7, 0.5, "yes", close=_close(yes_prob=0.6)),  # +0.1
        _settled_row("b", 0.3, 0.5, "no", close=_close(yes_prob=0.6)),   # -0.1
        _settled_row("c", 0.7, 0.5, "yes"),                              # no close
        _settled_row("d", 0.7, 0.5, "yes", close=_close()),              # canceled below
    ]
    rows[-1]["status"] = "CANCELED"
    rows[-1]["result"] = None
    summary = track_record.compute_engine_summary(rows)
    assert summary["clv_n"] == 2
    assert summary["clv_mean"] == pytest.approx(0.0)
    assert summary["clv_positive_share"] == pytest.approx(0.5)


def test_compute_engine_summary_no_close_is_none_not_zero():
    rows = [_settled_row("a", 0.7, 0.5, "yes"), _settled_row("b", 0.8, 0.9, "no")]
    summary = track_record.compute_engine_summary(rows)
    assert summary["clv_n"] == 0
    assert summary["clv_mean"] is None
    assert summary["clv_positive_share"] is None


# --- track-record API response ---


def test_track_record_endpoint_surfaces_clv_fields():
    from fastapi.testclient import TestClient

    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    class _ApiQuery:
        def __init__(self, rows):
            self.rows = rows

        def select(self, *_a):
            return self

        def eq(self, *_a):
            return self

        def order(self, *_a, **_k):
            return self

        def range(self, *_a, **_k):
            return self

        def execute(self):
            return _Result(self.rows)

    preds = [_settled_row("a", 0.7, 0.5, "yes", close=_close(yes_prob=0.6))]

    class _ApiSupa:
        def table(self, name):
            if name == "predictions":
                return _ApiQuery(preds)
            if name == "journal_scores":
                return _ApiQuery([])
            return _ApiQuery([{"engine": "gas", "engine_version": "v1", "gate_status": "SHADOW"}])

    main.app.dependency_overrides[get_supabase] = lambda: _ApiSupa()
    try:
        body = TestClient(main.app).get("/api/track-record").json()
    finally:
        main.app.dependency_overrides.clear()
    assert body[0]["clv_n"] == 1
    assert body[0]["clv_mean"] == pytest.approx(0.1)
    assert body[0]["clv_positive_share"] == pytest.approx(1.0)
