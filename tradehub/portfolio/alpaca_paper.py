"""Read-only access to the Alpaca PAPER account.

Paper only, by construction: the one trading host here is the paper host, and this module only
issues GETs (tests/test_portfolio_alpaca_paper.py fails if either changes). No order path exists.
"""

from __future__ import annotations

import os
from typing import Any

import requests

PAPER_BASE = "https://paper-api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"


class AccountNotConnected(Exception):
    """No usable paper keys: missing, or Alpaca rejected them. The page says so instead of showing zeros."""


def _headers(book: str | None = None) -> dict[str, str]:
    from tradehub.portfolio.books import BOOKS, resolve

    cfg = BOOKS[resolve(book)]
    key = os.getenv(cfg["key_env"], "").strip('"')
    secret = os.getenv(cfg["secret_env"], "").strip('"')
    if not key or not secret:
        raise AccountNotConnected(f"Alpaca paper keys are not configured for the {cfg['label']}")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _get(url: str, params: dict | None, session, book: str | None = None) -> Any:
    response = session.get(url, headers=_headers(book), params=params, timeout=10)
    if response.status_code in (401, 403):
        raise AccountNotConnected(f"Alpaca rejected the keys (HTTP {response.status_code})")
    response.raise_for_status()
    return response.json()


def paper_get(path: str, params: dict | None = None, *, session=requests,
              book: str | None = None) -> Any:
    return _get(PAPER_BASE + path, params, session, book)


def latest_price(symbol: str, *, session=requests, book: str | None = None) -> float:
    return float(_get(DATA_BASE + f"/v2/stocks/{symbol}/trades/latest", None, session,
                      book)["trade"]["p"])


def latest_spy_price(*, session=requests, book: str | None = None) -> float:
    return latest_price("SPY", session=session, book=book)


def latest_qqq_price(*, session=requests, book: str | None = None) -> float:
    return latest_price("QQQ", session=session, book=book)


def stock_bars(symbol: str, timeframe: str, start: str, end: str, *, session=requests,
               book: str | None = None) -> list[dict]:
    """Historical bars for one symbol over [start, end] (ISO timestamps),
    oldest first, following the data API's pagination. IEX feed, matching
    the snapshots read. Used by the QQQ snapshot backfill."""
    out: list[dict] = []
    params: dict = {"timeframe": timeframe, "start": start, "end": end,
                    "feed": "iex", "adjustment": "raw", "sort": "asc", "limit": 10000}
    while True:
        data = _get(DATA_BASE + f"/v2/stocks/{symbol}/bars", params, session, book)
        out.extend((data or {}).get("bars") or [])
        token = (data or {}).get("next_page_token")
        if not token:
            return out
        params = {**params, "page_token": token}


def latest_snapshots(symbols: list[str], *, session=requests,
                     book: str | None = None) -> dict[str, dict]:
    """Batched stock snapshots: the latest trade price and today's daily
    bar (its close is the regular-session close once the day has closed)
    per symbol. Feeds the Portfolio page's per-position after-hours move.
    Symbols the feed doesn't return are simply absent."""
    if not symbols:
        return {}
    data = _get(DATA_BASE + "/v2/stocks/snapshots",
                {"symbols": ",".join(symbols), "feed": "iex"}, session, book)
    out: dict[str, dict] = {}
    for symbol, snap in (data or {}).items():
        trade = (snap or {}).get("latestTrade") or {}
        bar = (snap or {}).get("dailyBar") or {}
        prev_bar = (snap or {}).get("prevDailyBar") or {}
        try:
            prev_close = float(prev_bar["c"])
        except (KeyError, TypeError, ValueError):
            prev_close = None
        try:
            out[symbol] = {
                "price": float(trade["p"]),
                "trade_at": str(trade.get("t", "")),
                "day_close": float(bar["c"]),
                "day": str(bar.get("t", ""))[:10],
                "prev_close": prev_close,
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out


def asset_flags(symbol: str, *, book: str | None = None, session=requests) -> dict:
    """Return tradable/shortable/easy_to_borrow/fractionable flags for a symbol."""
    url = PAPER_BASE + f"/v2/assets/{symbol}"
    try:
        response = session.get(url, headers=_headers(book), timeout=10)
        if response.status_code == 401:
            raise AccountNotConnected("Alpaca rejected the keys (HTTP 401)")
        if response.status_code >= 400:
            return {"tradable": False, "shortable": False, "easy_to_borrow": False, "fractionable": False}
        data = response.json() or {}
        return {
            "tradable": bool(data.get("tradable", False)),
            "shortable": bool(data.get("shortable", False)),
            "easy_to_borrow": bool(data.get("easy_to_borrow", False)),
            "fractionable": bool(data.get("fractionable", False)),
        }
    except requests.RequestException:
        return {"tradable": False, "shortable": False, "easy_to_borrow": False, "fractionable": False}
