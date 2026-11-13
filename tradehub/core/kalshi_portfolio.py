"""
Kalshi Portfolio — API Integration (RSA-Signed Auth)

Fetches account balance, open positions, and settlement history.
Uses RSA-PSS signing per Kalshi API docs.

Order writes (create/cancel) exist ONLY for the demo auto-trader
(tradehub/kalshi_demo.py) and are hard-guarded to the demo host: every
write method calls assert_demo_host() first, which requires
KALSHI_ENV=demo AND a resolved host of exactly demo-api.kalshi.co.
There is no code path in this module that can place an order on the
live Kalshi host.

Required .env vars:
  KALSHI_API_KEY_ID  — Your API key ID (from Kalshi account settings)
  KALSHI_API_KEY     — Your RSA private key (PEM format)
"""

import requests
import os
import time
import base64
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from tradehub.markets import quote_cents

# No `load_dotenv()` at import time -- see `tradehub.core.env`. `root_dir` is
# only a base path for locating the private key file; it no longer doubles as
# the `.env` location.
root_dir = Path(__file__).resolve().parent.parent
KALSHI_API_BASE = os.getenv("KALSHI_API_BASE", "https://demo-api.kalshi.co").strip('"').strip("'")
KALSHI_BASE_URL = f"{KALSHI_API_BASE}/trade-api/v2"

DEMO_HOST = "demo-api.kalshi.co"


class NotDemoHostError(RuntimeError):
    """A Kalshi order write was attempted outside the demo sandbox."""


class KalshiWriteError(RuntimeError):
    """A signed Kalshi write returned a non-2xx status; order calls never fail silently."""

    def __init__(self, status: int, text: str):
        super().__init__(f"Kalshi write failed: HTTP {status} -- {text[:200]}")
        self.status = status


class KalshiPortfolio:
    """Kalshi portfolio client with RSA-PSS authentication.

    Reads work against whatever host the env resolves. Writes are
    demo-only: see the module docstring and assert_demo_host().
    """

    def __init__(self, api_base: str | None = None):
        # api_base is a test seam: production passes nothing and resolves
        # the module constant exactly as before.
        self.api_base = (api_base or KALSHI_API_BASE).strip('"').strip("'")
        self.base_url = f"{self.api_base}/trade-api/v2"
        self.api_key_id = os.getenv("KALSHI_API_KEY_ID", "")
        private_key_pem = os.getenv("KALSHI_API_KEY", "")
        self.key_file_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")

        if not self.api_key_id:
            raise ValueError(
                "KALSHI_API_KEY_ID not found in .env. "
                "Get it from Kalshi → Settings → API Keys."
            )
        if not private_key_pem and not self.key_file_path:
            raise ValueError("KALSHI_API_KEY or KALSHI_PRIVATE_KEY_PATH (RSA private key) not found in .env.")

        # Load the RSA private key
        try:
            pem_bytes = None

            # Method 1: Check if a path is provided and valid
            key_path = self.key_file_path or os.getenv("KALSHI_KEY_FILE", "")
            if key_path:
                potential_path = Path(key_path)
                if potential_path.is_file():
                    pem_bytes = potential_path.read_bytes()
                elif (root_dir / key_path).is_file():
                    pem_bytes = (root_dir / key_path).read_bytes()

            # Method 2: Check default filenames in root_dir
            if pem_bytes is None:
                for fname in ['kalshi_private_key.pem', 'kalshi_key.pem', '.kalshi_key.pem', 'Kalshi Edge Tracker.txt']:
                    p = root_dir / fname
                    if p.is_file():
                        pem_bytes = p.read_bytes()
                        break

            # Method 3: Fallback to KALSHI_API_KEY environment variable
            if pem_bytes is None and private_key_pem:
                if 'BEGIN' in private_key_pem:
                    pem_bytes = private_key_pem.encode()
                else:
                    # Generic reconstruction for single-line PEMs
                    body = private_key_pem.strip().replace(' ', '').replace('\\n', '\n')
                    if 'BEGIN' not in body:
                        # Add headers if missing
                        body = f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----"
                    pem_bytes = body.encode()

            if pem_bytes is None:
                raise ValueError("No private key found (checked paths and env)")

            # Final Cleanup: Remove any non-printable chars or weird whitespace that might break base64
            # We preserve newlines as they are ignored by PEM loaders
            clean_pem = b""
            for b in pem_bytes:
                if b in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=-\n\r " or b == ord('-'):
                    clean_pem += bytes([b])
            
            self.private_key = serialization.load_pem_private_key(
                clean_pem, password=None
            )
        except Exception as e:
            raise ValueError(f"Failed to load RSA private key: {e}")

    def _sign_request(self, method, path):
        """
        Generate RSA-PSS signed headers for a Kalshi API request.
        Kalshi requires: timestamp_ms + method + path (no query params) signed with RSA-PSS + SHA256.
        """
        timestamp_ms = str(int(time.time() * 1000))
        message = f"{timestamp_ms}{method}{path}"

        signature = self.private_key.sign(
            message.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        sig_b64 = base64.b64encode(signature).decode()

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "Content-Type": "application/json",
        }

    def _get(self, endpoint, params=None):
        """Make authenticated GET request."""
        path = f"/trade-api/v2{endpoint}"
        url = f"{self.base_url}{endpoint}"
        headers = self._sign_request("GET", path)
        try:
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            else:
                # Silently fail for market data if needed, but log for others
                if "/markets/" not in endpoint:
                    print(f"  Kalshi API {endpoint}: {r.status_code} — {r.text[:200]}")
                return None
        except Exception as e:
            if "/markets/" not in endpoint:
                print(f"  Kalshi API error: {e}")
            return None

    # -- demo-guarded writes -------------------------------------------------
    # The ONLY order-writing surface in tradehub/. Every method below
    # asserts the demo host before any request leaves the process.

    def resolved_host(self) -> str:
        return urlparse(self.base_url).hostname or ""

    def assert_demo_host(self) -> None:
        """Raise unless BOTH the env and the resolved host say demo.

        The two checks are independent on purpose: the module default is
        already the demo host, so a host check alone would bless a box
        whose KALSHI_ENV was never set to demo; an env check alone would
        bless a mis-set KALSHI_API_BASE pointing at the live host.
        """
        env = os.getenv("KALSHI_ENV", "")
        if env != "demo":
            raise NotDemoHostError(
                f"KALSHI_ENV is {env!r}, not 'demo' -- Kalshi order writes refused")
        host = self.resolved_host()
        if host != DEMO_HOST:
            raise NotDemoHostError(
                f"resolved Kalshi host is {host!r}, not {DEMO_HOST!r} -- order writes refused")

    def _write(self, method: str, endpoint: str, body: dict | None = None) -> dict:
        path = f"/trade-api/v2{endpoint}"
        url = f"{self.base_url}{endpoint}"
        headers = self._sign_request(method, path)
        r = requests.request(method, url, headers=headers, json=body, timeout=10)
        if not 200 <= r.status_code < 300:
            raise KalshiWriteError(r.status_code, r.text)
        return r.json() if r.text else {}

    def _post(self, endpoint: str, body: dict) -> dict:
        self.assert_demo_host()
        return self._write("POST", endpoint, body)

    def _delete(self, endpoint: str) -> dict:
        self.assert_demo_host()
        return self._write("DELETE", endpoint)

    def create_order(self, *, ticker: str, side: str, count: int,
                     limit_price_cents: int, client_order_id: str,
                     expiration_ts: int) -> dict:
        """Place ONE buy limit order on the demo host (Create Order V2).

        V2 prices only the YES leg: side is bid (buy YES) or ask (sell
        YES), price is a fixed-point dollar string, count a 2-decimal
        string. Buying NO at c cents is therefore an ask on YES at
        (100 - c) cents. Expiry is good_till_canceled + expiration_time.
        Response is flat: {order_id, client_order_id, fill_count,
        remaining_count, ts_ms}.
        """
        yes_cents = int(limit_price_cents) if side == "yes" else 100 - int(limit_price_cents)
        body = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "side": "bid" if side == "yes" else "ask",
            "count": f"{int(count)}.00",
            "price": f"{yes_cents / 100:.4f}",
            "time_in_force": "good_till_canceled",
            "expiration_time": int(expiration_ts),
            "self_trade_prevention_type": "taker_at_cross",
        }
        return self._post("/portfolio/events/orders", body)

    def cancel_order(self, order_id: str) -> dict:
        return self._delete(f"/portfolio/events/orders/{order_id}")  # V2 cancel

    def get_order(self, order_id: str) -> dict | None:
        data = self._get(f"/portfolio/orders/{order_id}")
        if data:
            return data.get("order", data)
        return None

    def get_orders(self, status: str | None = None) -> list:
        # Get Orders has no client_order_id filter; callers match client-side.
        # status: resting | canceled | executed.
        params = {"status": status} if status else None
        data = self._get("/portfolio/orders", params=params)
        if data:
            return data.get("orders", [])
        return []

    def get_market_data(self, ticker):
        """Get raw market data for a single ticker."""
        return self._get(f"/markets/{ticker}")

    def get_balance(self):
        """Get account balance. Returns dict with 'balance' in cents."""
        return self._get("/portfolio/balance")

    def get_positions(self, limit=200):
        """Get all open positions (fail-soft: [] when the read fails)."""
        data = self._get("/portfolio/positions", params={"limit": limit})
        if data:
            positions = data.get('market_positions', data.get('positions', []))
            return positions
        return []

    def get_positions_strict(self, limit=200):
        """Same read, but a failed request raises instead of reading as an
        empty book -- for callers that must not report 'no positions' when
        the read never landed."""
        data = self._get("/portfolio/positions", params={"limit": limit})
        if data is None:
            raise RuntimeError("Kalshi positions read failed")
        return data.get('market_positions', data.get('positions', []))

    def get_settlements(self, limit=50):
        """Get recent settlements (closed positions and payouts)."""
        data = self._get("/portfolio/settlements", params={"limit": limit})
        if data:
            return data.get('settlements', [])
        return []

    def get_fills(self, limit=50):
        """Get recent trade fills (execution history)."""
        data = self._get("/portfolio/fills", params={"limit": limit})
        if data:
            return data.get('fills', [])
        return []

    def get_portfolio_summary(self):
        """
        Aggregate portfolio data into a summary dict.
        Returns balance, positions, recent P&L, and stats.
        """
        summary = {
            'balance': None,
            'portfolio_value': None,
            'positions': [],
            'total_invested': 0,
            'market_exposure': 0,
            'total_positions': 0,
            'settlements': [],
            'total_pnl': 0,
            'wins': 0,
            'losses': 0,
            'error': None,
        }

        try:
            # Balance
            bal = self.get_balance()
            if bal:
                summary['balance'] = bal.get('balance', 0) / 100  # cents → dollars
                summary['portfolio_value'] = bal.get('portfolio_value', 0) / 100

            # Open positions
            positions = self.get_positions()
            summary['positions'] = positions
            summary['total_positions'] = len(positions)

            for pos in positions:
                ticker = pos.get('ticker')
                # total_traded = total cost in cents, market_exposure = current value in cents
                summary['total_invested'] += float(pos.get('total_traded_dollars', pos.get('total_traded', 0) / 100))
                
                # Fetch live price for accurate exposure
                m_data = self.get_market_data(ticker)
                if m_data and m_data.get('market'):
                    prices = quote_cents(m_data['market'])
                    yes_ask, yes_bid = prices['yes_ask'], prices['yes_bid']
                    # Use yes_ask/yes_bid to estimate mid-market
                    if yes_ask is not None and yes_bid is not None:
                        current_price = (yes_ask + yes_bid) / 2
                    else:
                        current_price = yes_ask if yes_ask is not None else yes_bid
                    # An unpriceable market leaves the position untouched rather
                    # than persisting a fabricated 0c price and 0 exposure.
                    if current_price is not None:
                        pos['current_price'] = current_price
                        pos['market_exposure_dollars'] = (current_price * pos.get('position', 0)) / 100
                
                summary['market_exposure'] += float(pos.get('market_exposure_dollars', pos.get('market_exposure', 0) / 100))

            # Settlements
            settlements = self.get_settlements(limit=30)
            summary['settlements'] = settlements

            for s in settlements:
                payout = s.get('revenue', 0) / 100  # cents → dollars
                summary['total_pnl'] += payout
                if payout > 0:
                    summary['wins'] += 1
                elif payout < 0:
                    summary['losses'] += 1

        except Exception as e:
            summary['error'] = str(e)

        return summary


def check_portfolio_available():
    """Check if portfolio integration is configured.

    The key may be provisioned as a PEM string (KALSHI_API_KEY) or as a
    mounted file (KALSHI_PRIVATE_KEY_PATH / KALSHI_KEY_FILE -- the VPS
    demo service uses the file), so availability means a key id plus
    either a key string or an existing key file.
    """
    if not os.getenv("KALSHI_API_KEY_ID", ""):
        return False
    if os.getenv("KALSHI_API_KEY", ""):
        return True
    for var in ("KALSHI_PRIVATE_KEY_PATH", "KALSHI_KEY_FILE"):
        path = os.getenv(var, "")
        if path and Path(path).is_file():
            return True
    return False


if __name__ == "__main__":
    print("Testing Kalshi Portfolio API...")

    if not check_portfolio_available():
        print("❌ Missing KALSHI_API_KEY_ID in .env")
        print("   Get it from: Kalshi → Settings → API Keys")
        exit(1)

    try:
        portfolio = KalshiPortfolio()
        summary = portfolio.get_portfolio_summary()

        print(f"\n💰 Balance: ${summary['balance']:.2f}" if summary['balance'] else "Balance: N/A")
        print(f"📊 Open Positions: {summary['total_positions']}")
        print(f"💵 Total Invested: ${summary['total_invested']:.2f}")
        print(f"📈 Settlement P&L: ${summary['total_pnl']:.2f}")
        print(f"   Wins: {summary['wins']} | Losses: {summary['losses']}")

        if summary['positions']:
            print("\n── Open Positions ──")
            for p in summary['positions'][:10]:
                print(f"  {p.get('ticker', 'Unknown')}: qty={p.get('total_traded', 0)}, "
                      f"avg={p.get('average_price', 0)}¢")

    except ValueError as e:
        print(f"❌ {e}")
