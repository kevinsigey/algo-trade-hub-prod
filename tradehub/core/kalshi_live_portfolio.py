"""Kalshi LIVE portfolio client for the micro-pilot lane (issue #590).

A separate client with a separate guard, exactly as the pilot's
preregistration requires: `KalshiPortfolio` and its demo guard are
untouched, and nothing in this module is reachable from the demo lane.

Auth is Kalshi's RSA-PSS signing, the same scheme as the demo client,
but the credentials are the LIVE account's own and come only from:

  KALSHI_LIVE_KEY_ID           -- the live key's id
  KALSHI_LIVE_PRIVATE_KEY_PATH -- path to the live RSA private key (PEM)

Kevin places both on the VPS himself; the key never appears in the
repo, the chat or the logs (issue #590, "Kevin does").

Writes are refused unless ALL THREE hold (assert_live_host):

  - KALSHI_LIVE_ENABLED == "1"   (Kevin sets it after reviewing the
    merged PR; the lane ships with it unset)
  - KALSHI_LIVE_ENV == "live"
  - the resolved host is the production host -- the host of
    kalshi_prod_book.PROD_BASE (api.elections.kalshi.com)

The checks are independent on purpose, mirroring assert_demo_host: an
env slip alone or a host slip alone never blesses a write. Reads are
signed GETs and carry no guard beyond holding the live key, so the
scoreboard can show the balance once Kevin has placed the key, before
he enables trading.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from tradehub import kalshi_prod_book
from tradehub.core.kalshi_portfolio import KalshiWriteError

PROD_HOST = urlparse(kalshi_prod_book.PROD_BASE).hostname or ""
_LIVE_BASE = kalshi_prod_book.PROD_BASE  # includes /trade-api/v2


class NotLiveHostError(RuntimeError):
    """A live Kalshi write was attempted without the full live guard."""


def live_enabled() -> bool:
    return os.getenv("KALSHI_LIVE_ENABLED", "") == "1"


def check_live_available() -> bool:
    """The scoreboard's availability read: a live key id plus an
    existing key file. Says nothing about the trading guard."""
    if not os.getenv("KALSHI_LIVE_KEY_ID", ""):
        return False
    path = os.getenv("KALSHI_LIVE_PRIVATE_KEY_PATH", "")
    return bool(path) and Path(path).is_file()


class KalshiLivePortfolio:
    """The live account's client. Constructs only when the live key id
    and key file are present; writes additionally require
    assert_live_host() to pass on every call."""

    def __init__(self, api_base: str | None = None,
                 key_id: str | None = None, key_path: str | None = None):
        # api_base / key_id / key_path are test seams: production passes
        # nothing and resolves the production base and the KALSHI_LIVE_*
        # env vars.
        base = (api_base or _LIVE_BASE).strip('"').strip("'")
        # Accept either the bare origin or the full /trade-api/v2 base;
        # normalize to the full base so resolved_host and request paths
        # are the production ones either way.
        self.base_url = base if base.endswith("/trade-api/v2") \
            else f"{base}/trade-api/v2"
        self.api_key_id = key_id or os.getenv("KALSHI_LIVE_KEY_ID", "")
        self.key_file_path = key_path or os.getenv(
            "KALSHI_LIVE_PRIVATE_KEY_PATH", "")
        if not self.api_key_id:
            raise ValueError(
                "KALSHI_LIVE_KEY_ID not set. Kevin places the live key "
                "on the VPS himself (issue #590).")
        if not self.key_file_path or not Path(self.key_file_path).is_file():
            raise ValueError(
                "KALSHI_LIVE_PRIVATE_KEY_PATH does not name an existing "
                "file. Kevin places the live key on the VPS himself "
                "(issue #590).")
        try:
            pem_bytes = Path(self.key_file_path).read_bytes()
            clean_pem = b"".join(
                bytes([b]) for b in pem_bytes
                if b in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                        b"0123456789+/=-\n\r " or b == ord("-"))
            self.private_key = serialization.load_pem_private_key(
                clean_pem, password=None)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Failed to load live RSA private key: {exc}")

    # -- the guard ------------------------------------------------------

    def resolved_host(self) -> str:
        return urlparse(self.base_url).hostname or ""

    def assert_live_host(self) -> None:
        """Raise unless the enable flag, the env marker AND the
        resolved host all say live production."""
        if not live_enabled():
            raise NotLiveHostError(
                "KALSHI_LIVE_ENABLED is not '1' -- live Kalshi writes "
                "refused (Kevin enables the lane himself)")
        env = os.getenv("KALSHI_LIVE_ENV", "")
        if env != "live":
            raise NotLiveHostError(
                f"KALSHI_LIVE_ENV is {env!r}, not 'live' -- live "
                "Kalshi writes refused")
        host = self.resolved_host()
        if host != PROD_HOST:
            raise NotLiveHostError(
                f"resolved Kalshi host is {host!r}, not {PROD_HOST!r} "
                "-- live Kalshi writes refused")

    # -- transport ------------------------------------------------------

    def _sign_request(self, method: str, path: str) -> dict:
        timestamp_ms = str(int(time.time() * 1000))
        message = f"{timestamp_ms}{method}{path}"
        signature = self.private_key.sign(
            message.encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256())
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str, params: dict | None = None):
        path = f"/trade-api/v2{endpoint}"
        url = f"{self.base_url}{endpoint}"
        headers = self._sign_request("GET", path)
        try:
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            if "/markets/" not in endpoint:
                print(f"  Kalshi live API {endpoint}: {r.status_code} "
                      f"-- {r.text[:200]}")
            return None
        except Exception as exc:  # noqa: BLE001
            if "/markets/" not in endpoint:
                print(f"  Kalshi live API error: {exc}")
            return None

    def _write(self, method: str, endpoint: str,
               body: dict | None = None) -> dict:
        path = f"/trade-api/v2{endpoint}"
        url = f"{self.base_url}{endpoint}"
        headers = self._sign_request(method, path)
        r = requests.request(method, url, headers=headers, json=body,
                             timeout=10)
        if not 200 <= r.status_code < 300:
            raise KalshiWriteError(r.status_code, r.text)
        return r.json() if r.text else {}

    def _post(self, endpoint: str, body: dict) -> dict:
        self.assert_live_host()
        return self._write("POST", endpoint, body)

    # -- orders ----------------------------------------------------------

    def create_order(self, *, ticker: str, side: str, count: int,
                     limit_price_cents: int, client_order_id: str,
                     expiration_ts: int,
                     time_in_force: str = "immediate_or_cancel") -> dict:
        """Place ONE buy order on the live host (Create Order V2), same
        body shape as the demo client's: V2 prices only the YES leg, so
        buying NO at c cents is an ask on YES at (100 - c) cents. The
        pilot crosses IOC and nothing ever rests; expiration_time is
        sent only for GTC, exactly as on the demo client."""
        yes_cents = int(limit_price_cents) if side == "yes" \
            else 100 - int(limit_price_cents)
        body = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "side": "bid" if side == "yes" else "ask",
            "count": f"{int(count)}.00",
            "price": f"{yes_cents / 100:.4f}",
            "time_in_force": time_in_force,
            "self_trade_prevention_type": "taker_at_cross",
        }
        if time_in_force == "good_till_canceled":
            body["expiration_time"] = int(expiration_ts)
        return self._post("/portfolio/events/orders", body)

    # -- reads -----------------------------------------------------------

    def get_balance(self):
        """Account balance: {'balance': cents, ...} or None."""
        return self._get("/portfolio/balance")

    def get_market_data(self, ticker: str):
        return self._get(f"/markets/{ticker}")

    def get_order(self, order_id: str) -> dict | None:
        data = self._get(f"/portfolio/orders/{order_id}")
        if data:
            return data.get("order", data)
        return None

    def get_orders(self, status: str | None = None) -> list:
        params = {"status": status} if status else None
        data = self._get("/portfolio/orders", params=params)
        if data is None:  # an unread book never reads as 'no orders'
            raise RuntimeError("Kalshi live orders read failed")
        return data.get("orders", [])

    def get_fills(self, limit: int = 200) -> list:
        """Recent fills. A failed request raises instead of reading as
        'no fills' -- reconciling a placed order must not treat an
        unread book as an unfilled one (the demo client's contract)."""
        data = self._get("/portfolio/fills", params={"limit": limit})
        if data is None:
            raise RuntimeError("Kalshi live fills read failed")
        return data.get("fills", [])

    def get_positions(self, limit: int = 200) -> list:
        data = self._get("/portfolio/positions", params={"limit": limit})
        if data is None:  # an unread book never reads as 'no positions'
            raise RuntimeError("Kalshi live positions read failed")
        return data.get("market_positions", data.get("positions", []))
