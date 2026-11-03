"""Crypto 1-minute bars (Yahoo BTC-USD / ETH-USD) as point-in-time observations.

The hourly crypto model's tape: Kalshi's KXBTC/KXETH settle on the CF Benchmarks
BRTI value at the top of the hour; Yahoo's 1-minute closes are the free,
keyless spot series whose level the walk-forward replay (2026-11-02) anchored
on. Bars are stamped with their bar time, so a caller can refuse a stale print
instead of pricing an old price as if it were live -- the wti loader's rule.

Yahoo-only in v1 on purpose: the model needs the trailing 120 minutes of bars
for its realized-volatility sigma, so a level-only fallback (a ticker quote)
could never rescue a freeze on its own; a Yahoo outage reads as a gap in the
journal, never as a silently different model.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from tradehub.backtest.pit import Observation

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"


def _default_fetch(symbol: str) -> Any:
    req = urllib.request.Request(_CHART.format(symbol=symbol),
                                 headers={"User-Agent": "tradehub/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def crypto_bars_1m(symbol: str, *, fetch: Callable[[str], Any] = _default_fetch) -> list[Observation]:
    """The day's 1-minute closes for `symbol` (e.g. "BTC-USD"), oldest first."""
    try:
        data = fetch(symbol)
        result = data["chart"]["result"][0]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except Exception:  # noqa: BLE001 -- any fetch/parse failure is "no bars", never a crash
        return []
    out = []
    for stamp, close in zip(stamps, closes):
        if close is None:
            continue
        out.append(Observation(f"CRYPTO:{symbol}:1m", float(close),
                               datetime.fromtimestamp(stamp, tz=timezone.utc)))
    return out


def crypto_last_price(symbol: str, *, fetch: Callable[[str], Any] = _default_fetch) -> Observation | None:
    bars = crypto_bars_1m(symbol, fetch=fetch)
    return bars[-1] if bars else None
