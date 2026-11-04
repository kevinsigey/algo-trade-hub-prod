"""The live WTI price Kalshi settles its hourly oil markets on: Pyth's PYTHOIL feed.

Pyth Pro needs an API key (PYTH_API_KEY; Kevin's trial started 2026-11-04 and runs 14 days). Feed ID and
exponent are from Pyth's public symbol list. An error names what went wrong and never carries the key.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import requests

from tradehub.backtest.pit import Observation

LATEST_URL = "https://pyth-lazer.dourolabs.app/v1/latest_price"
PYTHOIL_ID = 3063
EXPONENT = -5


class PythUnavailable(Exception):
    """No usable Pyth price. The message is safe to show publicly."""


def pyth_oil_price(*, session: Any = requests) -> Observation:
    key = os.getenv("PYTH_API_KEY", "").strip()
    if not key:
        raise PythUnavailable("no API key set")
    try:
        response = session.post(LATEST_URL, json={"priceFeedIds": [PYTHOIL_ID], "properties": ["price"], "formats": [],
                                                  "channel": "fixed_rate@200ms"},
                                headers={"Authorization": f"Bearer {key}"}, timeout=5)
    except requests.RequestException as exc:
        raise PythUnavailable(f"Pyth could not be reached ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise PythUnavailable(f"Pyth answered {response.status_code}")
    try:
        parsed = response.json()["parsed"]
        feed = next(f for f in parsed["priceFeeds"] if f["priceFeedId"] == PYTHOIL_ID)
        value = int(feed["price"]) * 10.0 ** EXPONENT
        published = datetime.fromtimestamp(int(parsed["timestampUs"]) / 1_000_000, UTC)
    except (KeyError, StopIteration, TypeError, ValueError):
        raise PythUnavailable("Pyth's answer wasn't in the expected shape") from None
    if value <= 0:
        raise PythUnavailable("Pyth returned no price")
    return Observation("PYTHOIL", value, published)
