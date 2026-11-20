"""Production Kalshi public reads for the demo lane's would-have-filled
record (Kevin's ruling via Claude, 2026-11-17).

Observation only. This module's single transport issues HTTP GET
requests against Kalshi's PUBLIC production API
(api.elections.kalshi.com) with no credentials, and nothing in it can
place, cancel or modify anything: there is no write verb in the file,
no order endpoint, and no signing. The demo order path keeps its own
demo-host guard exactly as it was; this reader never touches it. The
hard guard is tested (tests/test_kalshi_prod_book.py): every request
this module can issue is a GET to the production host, and a source
scan fails the suite if a write method ever appears here.

Two reads per ticker: the market (top-of-book dollar quotes, the same
shape `tradehub.markets.quote_cents` reads) and the fixed-point
orderbook, from which the contracts on offer at the bought side's ask
are derived -- the YES ask is the mirror of the best NO bid, so the
size at the YES ask is the quantity resting at the NO-bid level priced
1 - ask (and symmetrically for NO).
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

PROD_BASE = "https://api.elections.kalshi.com/trade-api/v2"
_UA = {"User-Agent": "tradehub-prod-book-observer"}
# Short: two reads ride each demo decision, and a slow production
# book must never delay a demo placement by tens of seconds -- an
# unreadable book is simply no measurement (Claude's #560 review).
_TIMEOUT = 3


def _get(path: str) -> Any | None:
    """The module's only transport: one unauthenticated GET. None on
    any failure -- an unreadable production book is no measurement,
    never an exception in the runner's pass."""
    req = urllib.request.Request(f"{PROD_BASE}{path}", headers=_UA,
                                 method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read())
    except Exception:  # noqa: BLE001 -- observation is fail-soft
        return None


def read_market(ticker: str) -> dict | None:
    """The production market object for `ticker`, or None."""
    got = _get(f"/markets/{ticker}")
    if not isinstance(got, dict):
        return None
    market = got.get("market")
    return market if isinstance(market, dict) else None


def read_ask_size(ticker: str, side: str, ask: float) -> int | None:
    """Contracts on offer at `side`'s ask on the production book.

    The orderbook's fixed-point arrays carry resting BIDS per side
    ([price_dollars, quantity]); the ask for `side` is priced by the
    opposite side's bid at 1 - ask, and its quantity is what is on
    offer. No opposite level at that price -> 0 on offer there. None
    when the book cannot be read (unknown depth is not a measured
    zero)."""
    got = _get(f"/markets/{ticker}/orderbook")
    if not isinstance(got, dict):
        return None
    book = got.get("orderbook_fp")
    if not isinstance(book, dict):
        return None
    opposite = book.get("no_dollars" if side == "yes" else "yes_dollars")
    if not isinstance(opposite, list):
        return None
    mirror = round(1.0 - ask, 4)
    for level in opposite:
        try:
            price, qty = float(level[0]), float(level[1])
        except (TypeError, ValueError, IndexError):
            continue
        if abs(price - mirror) < 1e-9:
            return int(qty)
    return 0
