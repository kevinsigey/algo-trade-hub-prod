"""Row-click quote (Kevin, 2026-11-03): clicking a screener result shows the
stock's last quote and a price chart. The payload comes from the screening
data layer (Yahoo history, cached an hour, labelled delayed downstream);
no data means None / a 404 -- never an invented zero.
"""

from __future__ import annotations

import sys
import types

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tradehub.api import admin, main
from tradehub.screening import quote as quote_mod
from tradehub.screening.sources import DataStore


class _FakeTicker:
    calls = 0

    def __init__(self, ticker):
        self.ticker = ticker

    def history(self, period="1y", auto_adjust=False):
        type(self).calls += 1
        idx = pd.bdate_range("2026-10-30", periods=3)
        return pd.DataFrame(
            {"Close": [100.0, 110.0, 121.0], "Volume": [1000, 2000, 3000]}, index=idx)


class _EmptyTicker:
    def __init__(self, ticker):
        self.ticker = ticker

    def history(self, period="1y", auto_adjust=False):
        return pd.DataFrame()


@pytest.fixture
def fake_yf(monkeypatch):
    _FakeTicker.calls = 0
    mod = types.ModuleType("yfinance")
    mod.Ticker = _FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    return mod


def test_quote_series_math_and_shape(tmp_path, fake_yf):
    store = DataStore(tmp_path)
    q = store.quote_series("AAA")
    assert q["ticker"] == "AAA"
    assert q["price"] == 121.0
    assert q["prev_close"] == 110.0
    assert q["change_pct"] == pytest.approx(10.0)
    assert q["volume"] == 3000
    assert q["as_of"] == "2026-11-03"
    assert [c["close"] for c in q["closes"]] == [100.0, 110.0, 121.0]
    # Cached: a second call does not refetch.
    assert store.quote_series("AAA") == q
    assert _FakeTicker.calls == 1


def test_quote_series_no_data_is_none_not_zero(tmp_path, monkeypatch):
    mod = types.ModuleType("yfinance")
    mod.Ticker = _EmptyTicker
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    store = DataStore(tmp_path)
    assert store.quote_series("ZZZZ") is None
    assert any(m["field"] == "quote" for m in store.missing)


def _client(monkeypatch, payload):
    monkeypatch.setattr(quote_mod, "quote_payload", lambda store, ticker: payload)
    app = main.app
    app.dependency_overrides[admin.require_admin] = lambda: {"email": "a@b.c"}
    return TestClient(app, raise_server_exceptions=False)


def test_quote_endpoint_serves_the_payload(monkeypatch):
    payload = {"ticker": "AAA", "price": 121.0, "prev_close": 110.0, "change_pct": 10.0,
               "volume": 3000, "as_of": "2026-11-03", "closes": []}
    client = _client(monkeypatch, payload)
    try:
        r = client.get("/api/screening/quote/aaa")
        assert r.status_code == 200
        assert r.json()["ticker"] == "AAA"
        assert r.json()["price"] == 121.0
    finally:
        main.app.dependency_overrides.pop(admin.require_admin, None)


def test_quote_endpoint_404s_when_there_is_no_data(monkeypatch):
    client = _client(monkeypatch, None)
    try:
        r = client.get("/api/screening/quote/zzzz")
        assert r.status_code == 404
    finally:
        main.app.dependency_overrides.pop(admin.require_admin, None)
