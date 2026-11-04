"""Live WTI prices: Pyth's PYTHOIL feed, which Kalshi settles its hourly oil markets on, and a free stand-in.

Pyth Pro needs an API key (PYTH_API_KEY; Kevin's trial started 2026-11-04 and runs 14 days). Feed ID and
exponent are from Pyth's public symbol list. An error names what went wrong and never carries the key.

Hyperliquid's xyz:CL oil perpetual needs no key. It isn't what Kalshi settles on, and its oracle's source isn't
checked, so a shadow model grades whether it can stand in once the Pyth trial ends.
"""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime
from typing import Any

import requests

from tradehub.backtest.pit import Observation

LATEST_URL = "https://pyth-lazer.dourolabs.app/v1/latest_price"
PYTHOIL_ID = 3063
HERMES_URL = "https://pyth.dourolabs.app/hermes/v2/updates/price/latest"
HERMES_FEED = "67784f72e95ac01337edb7d7bd5bbd1c03669101b7068a620df228ed4e52ef14"
EXPONENT = -5
MAX_FUTURE_SECONDS = 60


class PythUnavailable(Exception):
    """No usable Pyth price. The message is safe to show publicly."""


def _reason(response: Any, key: str) -> str:
    """Pyth's own words for a refusal, short and with the key scrubbed, since this goes on a public field."""
    text = str(getattr(response, "text", "") or "").replace(key, "[key]")
    return " ".join(text.split())[:120]


def _pro_price(key: str, session: Any, now: datetime | None) -> Observation:
    response = session.post(LATEST_URL, json={"priceFeedIds": [PYTHOIL_ID], "properties": ["price", "feedUpdateTimestamp"],
                                              "formats": [], "channel": "fixed_rate@200ms"},
                            headers={"Authorization": f"Bearer {key}"}, timeout=5)
    if response.status_code != 200:
        raise PythUnavailable(f"Pro {response.status_code} {_reason(response, key)}".strip())
    try:
        parsed = response.json()["parsed"]
        feed = next(f for f in parsed["priceFeeds"] if f["priceFeedId"] == PYTHOIL_ID)
        value = int(feed["price"]) * 10.0 ** EXPONENT
        # The feed's own time, not the response's: a fresh wrapper can carry an old price.
        published = datetime.fromtimestamp(int(feed["feedUpdateTimestamp"]) / 1_000_000, UTC)
    except (KeyError, StopIteration, TypeError, ValueError, OverflowError, OSError):
        raise PythUnavailable("Pro's answer wasn't in the expected shape") from None
    return _checked(value, published, now)


def _hermes_price(key: str, session: Any, now: datetime | None) -> Observation:
    response = session.get(HERMES_URL, params={"ids[]": HERMES_FEED, "parsed": "true"},
                           headers={"Authorization": f"Bearer {key}"}, timeout=5)
    if response.status_code != 200:
        raise PythUnavailable(f"Hermes {response.status_code} {_reason(response, key)}".strip())
    try:
        price = response.json()["parsed"][0]["price"]
        value = int(price["price"]) * 10.0 ** int(price["expo"])
        published = datetime.fromtimestamp(int(price["publish_time"]), UTC)
    except (KeyError, IndexError, TypeError, ValueError, OverflowError, OSError):
        raise PythUnavailable("Hermes's answer wasn't in the expected shape") from None
    return _checked(value, published, now)


def _checked(value: float, published: datetime, now: datetime | None) -> Observation:
    if value <= 0:
        raise PythUnavailable("Pyth returned no price")
    if (published - (now or datetime.now(UTC))).total_seconds() > MAX_FUTURE_SECONDS:
        raise PythUnavailable("Pyth's price was stamped in the future")
    return Observation("PYTHOIL", value, published)


def pyth_oil_price(*, session: Any = requests, now: datetime | None = None) -> Observation:
    """Pyth Pro, then Hermes on the same key: which one a key opens depends on the plan."""
    key = os.getenv("PYTH_API_KEY", "").strip()
    if not key:
        raise PythUnavailable("no API key set")
    failures = []
    for route in (_pro_price, _hermes_price):
        try:
            return route(key, session, now)
        except PythUnavailable as exc:
            failures.append(str(exc))
        except requests.RequestException as exc:
            failures.append(f"{route.__name__} could not connect ({type(exc).__name__})")
    raise PythUnavailable("; ".join(failures))


HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_OIL = "xyz:CL"


class HyperliquidUnavailable(Exception):
    """No usable Hyperliquid price."""


def hyperliquid_oil_price(now: datetime, *, session: Any = requests) -> Observation:
    """The perp's oracle price. The API stamps no time on it, so it's as of this read, and a stuck
    oracle wouldn't show here; the shadow's grading is what would catch it."""
    try:
        response = session.post(HYPERLIQUID_URL, json={"type": "metaAndAssetCtxs", "dex": "xyz"}, timeout=5)
    except requests.RequestException as exc:
        raise HyperliquidUnavailable(f"Hyperliquid could not be reached ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise HyperliquidUnavailable(f"Hyperliquid answered {response.status_code}")
    try:
        meta, contexts = response.json()
        names = [a["name"] for a in meta["universe"]]
        value = float(contexts[names.index(HYPERLIQUID_OIL)]["oraclePx"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise HyperliquidUnavailable("Hyperliquid's answer wasn't in the expected shape") from None
    if not math.isfinite(value) or value <= 0:
        raise HyperliquidUnavailable("Hyperliquid returned no price")
    return Observation(HYPERLIQUID_OIL, value, now)
