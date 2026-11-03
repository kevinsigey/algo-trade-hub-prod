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
