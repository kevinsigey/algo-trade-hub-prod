"""The ONLY order path in the codebase (Trading HQ step 4). Paper account only, new orders only, off by default.

- The host is alpaca_paper.PAPER_BASE; this file names no other host (tests/test_portfolio_alpaca_paper.py).
- It sends one kind of request: POST /v2/orders. No cancels, no replaces, no position closes.
- Nothing is sent unless the server env TRADEHUB_PAPER_ORDERS is exactly "on" (each idea has its own switch too).
- Order kinds: market or limit, at the open (opg), at the close (cls) or during the day (day). Whole shares.
"""

from __future__ import annotations

import os
from typing import Any, Literal

import requests

from tradehub.portfolio.alpaca_paper import PAPER_BASE, AccountNotConnected, _headers

ORDER_TYPES = ("market", "limit")
TIMES_IN_FORCE = ("opg", "cls", "day")


class OrdersDisabled(Exception):
    """TRADEHUB_PAPER_ORDERS is not "on": nothing was sent."""


class DuplicateOrder(Exception):
    """Alpaca already has an order with this client_order_id: it was sent before (a re-run), not sent twice."""


class OrderRejected(Exception):
    """Alpaca refused the order (not shortable, market closed, insufficient buying power...)."""


def orders_enabled() -> bool:
    return os.getenv("TRADEHUB_PAPER_ORDERS", "").strip().strip('"') == "on"


def submit(symbol: str, qty: int, side: Literal["buy", "sell"], client_order_id: str, *,
           order_type: str = "market", time_in_force: str = "opg", limit_price: float | None = None,
           session=requests) -> dict[str, Any]:
    if order_type not in ORDER_TYPES or time_in_force not in TIMES_IN_FORCE or side not in ("buy", "sell"):
        raise ValueError(f"unsupported order: {order_type}/{time_in_force}/{side}")
    if order_type == "limit" and not limit_price:
        raise ValueError("a limit order needs a limit price")
    if int(qty) != qty or qty < 1:
        raise ValueError(f"qty must be a whole number of shares, got {qty}")
    if not orders_enabled():
        raise OrdersDisabled("TRADEHUB_PAPER_ORDERS is off")
    body = {"symbol": symbol, "qty": str(int(qty)), "side": side, "type": order_type, "time_in_force": time_in_force,
            "client_order_id": client_order_id}
    if order_type == "limit":
        body["limit_price"] = f"{limit_price:.2f}" if limit_price >= 1 else f"{limit_price:.4f}"
    response = session.post(PAPER_BASE + "/v2/orders", headers=_headers(), json=body, timeout=10)
    if response.status_code == 401:  # 403 on an order is a refusal (buying power, wash trade), not the keys
        raise AccountNotConnected("Alpaca rejected the keys (HTTP 401)")
    if response.status_code == 422:
        message = str((response.json() or {}).get("message", ""))
        if "client_order_id must be unique" in message:
            raise DuplicateOrder(client_order_id)
        raise OrderRejected(message or "HTTP 422")
    if response.status_code >= 400:
        raise OrderRejected(f"HTTP {response.status_code}: {(response.json() or {}).get('message', '')}"[:200])
    return response.json()
