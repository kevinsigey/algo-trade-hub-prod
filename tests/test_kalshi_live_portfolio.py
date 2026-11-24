"""Kalshi LIVE client: the three-condition guard, both directions.

The demo client must be refused on the live host and the live client
must be refused everywhere but the live host with the lane enabled.
No network: the guard raises before any request is built.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tradehub.core.kalshi_live_portfolio import (
    KalshiLivePortfolio,
    NotLiveHostError,
    check_live_available,
)
from tradehub.core.kalshi_portfolio import KalshiPortfolio, NotDemoHostError

PROD = "https://api.elections.kalshi.com/trade-api/v2"
DEMO = "https://demo-api.kalshi.co/trade-api/v2"


@pytest.fixture()
def key_file(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    path = tmp_path / "kalshi_live.pem"
    path.write_bytes(pem)
    return str(path)


@pytest.fixture()
def live_env(monkeypatch):
    monkeypatch.setenv("KALSHI_LIVE_ENABLED", "1")
    monkeypatch.setenv("KALSHI_LIVE_ENV", "live")


def _client(key_file, base=PROD):
    return KalshiLivePortfolio(api_base=base, key_id="live-key-id",
                               key_path=key_file)


def test_guard_passes_with_all_three_conditions(key_file, live_env):
    _client(key_file).assert_live_host()


def test_guard_refuses_without_enable_flag(key_file, monkeypatch):
    monkeypatch.setenv("KALSHI_LIVE_ENV", "live")
    monkeypatch.delenv("KALSHI_LIVE_ENABLED", raising=False)
    with pytest.raises(NotLiveHostError):
        _client(key_file).assert_live_host()


def test_guard_refuses_with_wrong_env_marker(key_file, monkeypatch):
    monkeypatch.setenv("KALSHI_LIVE_ENABLED", "1")
    monkeypatch.setenv("KALSHI_LIVE_ENV", "demo")
    with pytest.raises(NotLiveHostError):
        _client(key_file).assert_live_host()


def test_guard_refuses_on_the_demo_host(key_file, live_env):
    with pytest.raises(NotLiveHostError):
        _client(key_file, base=DEMO).assert_live_host()


def test_create_order_is_refused_before_any_request(key_file, monkeypatch):
    monkeypatch.setenv("KALSHI_LIVE_ENV", "live")
    monkeypatch.delenv("KALSHI_LIVE_ENABLED", raising=False)
    with pytest.raises(NotLiveHostError):
        _client(key_file).create_order(
            ticker="KXWTI15M-26NOV231200-00", side="yes", count=1,
            limit_price_cents=40, client_order_id="kl-x",
            expiration_ts=0)


def test_demo_client_is_refused_on_the_live_host(key_file, monkeypatch):
    monkeypatch.setenv("KALSHI_ENV", "demo")
    monkeypatch.setenv("KALSHI_API_KEY_ID", "demo-key-id")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", key_file)
    portfolio = KalshiPortfolio(api_base="https://api.elections.kalshi.com")
    with pytest.raises(NotDemoHostError):
        portfolio.assert_demo_host()


def test_missing_live_key_is_a_value_error(tmp_path, monkeypatch):
    monkeypatch.setenv("KALSHI_LIVE_KEY_ID", "live-key-id")
    monkeypatch.setenv("KALSHI_LIVE_PRIVATE_KEY_PATH",
                       str(tmp_path / "absent.pem"))
    with pytest.raises(ValueError):
        KalshiLivePortfolio()


def test_check_live_available(key_file, monkeypatch):
    monkeypatch.setenv("KALSHI_LIVE_KEY_ID", "live-key-id")
    monkeypatch.setenv("KALSHI_LIVE_PRIVATE_KEY_PATH", key_file)
    assert check_live_available() is True
    monkeypatch.delenv("KALSHI_LIVE_KEY_ID")
    assert check_live_available() is False


def test_failed_orders_and_positions_reads_raise(key_file, monkeypatch):
    client = _client(key_file)
    monkeypatch.setattr(client, "_get", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        client.get_orders()
    with pytest.raises(RuntimeError):
        client.get_positions()


def test_get_orders_pages_to_the_end_or_raises(key_file, monkeypatch):
    client = _client(key_file)
    pages = {None: {"orders": [{"order_id": "a"}], "cursor": "c2"},
             "c2": {"orders": [{"order_id": "b"}], "cursor": ""}}
    monkeypatch.setattr(client, "_get", lambda ep, params=None, **k:
                        pages[params.get("cursor")])
    assert [o["order_id"] for o in client.get_orders()] == ["a", "b"]
    monkeypatch.setattr(client, "_get", lambda ep, params=None, **k:
                        {"orders": [], "cursor": "again"})
    with pytest.raises(RuntimeError):
        client.get_orders()


def test_order_searches_by_ticker_current_and_historical(key_file, monkeypatch):
    client = _client(key_file)
    calls = []

    def fake_get(ep, params=None, **k):
        calls.append((ep, params.get("ticker")))
        return {"orders": [{"order_id": "x"}], "cursor": ""}
    monkeypatch.setattr(client, "_get", fake_get)
    client.get_orders(ticker="T1")
    client.get_historical_orders("T1")
    assert calls == [("/portfolio/orders", "T1"), ("/historical/orders", "T1")]
    monkeypatch.setattr(client, "_get", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        client.get_historical_orders("T1")
