"""Live prices from Hyperliquid's xyz oil and gas perpetuals: free, no key, no delay.

Kalshi settles on Pyth's PYTHOIL, BRENT and NATGAS, which our key can't read. Scored against Kalshi's own
15-minute strikes and results over 312 windows (2026-11-05), candle closes here matched the settlement's
15-minute direction 96.2% of the time on WTI, 97.8% on Brent and 94.2% on natural gas, with WTI's level within
about 2.5c. OKX's perps did no better and Yahoo's closer match runs about 10 minutes late.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import requests

from tradehub.backtest.pit import Observation

HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_OIL = "xyz:CL"


class HyperliquidUnavailable(Exception):
    """No usable Hyperliquid price."""


def hyperliquid_price(coin: str, now: datetime, *, session: Any = requests) -> Observation:
    """One xyz perp's oracle price. The API stamps no time on it, so it's as of this read, and a stuck
    oracle wouldn't show here; the shadows' grading is what would catch it."""
    try:
        response = session.post(HYPERLIQUID_URL, json={"type": "metaAndAssetCtxs", "dex": "xyz"}, timeout=5)
    except requests.RequestException as exc:
        raise HyperliquidUnavailable(f"Hyperliquid could not be reached ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise HyperliquidUnavailable(f"Hyperliquid answered {response.status_code}")
    try:
        meta, contexts = response.json()
        names = [a["name"] for a in meta["universe"]]
        value = float(contexts[names.index(coin)]["oraclePx"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise HyperliquidUnavailable("Hyperliquid's answer wasn't in the expected shape") from None
    if not math.isfinite(value) or value <= 0:
        raise HyperliquidUnavailable("Hyperliquid returned no price")
    return Observation(coin, value, now)


def hyperliquid_oil_price(now: datetime, *, session: Any = requests) -> Observation:
    return hyperliquid_price(HYPERLIQUID_OIL, now, session=session)


def hyperliquid_candles(coin: str, start: datetime, end: datetime, *,
                        session: Any = requests) -> list[tuple[datetime, float]]:
    """(candle open time, close) for the coin's 1-minute candles in [start, end),
    oldest first. Kalshi's 15-minute rules read candle closes, so the window open
    is the close of the candle that ends at the window's start."""
    body = {"type": "candleSnapshot",
            "req": {"coin": coin, "interval": "1m",
                    "startTime": int(start.timestamp() * 1000),
                    "endTime": int(end.timestamp() * 1000)}}
    try:
        response = session.post(HYPERLIQUID_URL, json=body, timeout=10)
    except requests.RequestException as exc:
        raise HyperliquidUnavailable(f"Hyperliquid could not be reached ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise HyperliquidUnavailable(f"Hyperliquid answered {response.status_code}")
    try:
        rows = [(datetime.fromtimestamp(int(c["t"]) / 1000, UTC), float(c["c"]))
                for c in response.json()]
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise HyperliquidUnavailable("Hyperliquid's candles weren't in the expected shape") from None
    return sorted((t, v) for t, v in rows if math.isfinite(v) and v > 0)
