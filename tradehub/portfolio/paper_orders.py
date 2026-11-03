"""The ONLY order path in the codebase (Trading HQ steps 4-5). Paper account only, off by default.

- The host is alpaca_paper.PAPER_BASE; this file names no other host (tests/test_portfolio_alpaca_paper.py).
- Two kinds of request: POST /v2/orders (new orders), and DELETE /v2/orders/{id} only for a protective order the
  hub itself placed (client_order_id `idea-<n>-stop-...`). No replaces, no position closes, nothing else.
- Protective orders carry one of two sanctioned tags: the hub's own `idea-<n>-stop-...` or the machine
  API's `ext-<key>-stop-...` (2026-11-02: Kevin's staged mirror book needed its stops to ride through the
  machine door; the API fences those to held positions, this module fences the tag family and the shape).
- Nothing is sent unless the book's kill switch is exactly "on" (TRADEHUB_PAPER_ORDERS for the main
  book, TRADEHUB_PAPER_ORDERS_BIG for the $1M book; each idea has its own switch too).
- Rule orders: market or limit, at the open (opg), at the close (cls) or during the day (day). Protective orders
  (stop, trailing stop, take-profit limit) are good-till-cancelled and must carry the stop tag. Whole shares.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import requests

from tradehub.portfolio.alpaca_paper import PAPER_BASE, AccountNotConnected, _headers

ORDER_TYPES = ("market", "limit", "stop", "trailing_stop")
TIMES_IN_FORCE = ("opg", "cls", "day", "gtc")
STOP_TAG = re.compile(r"^idea-\d+-stop-")
MACHINE_STOP_TAG = re.compile(r"^ext-\d+-stop-")
ORDER_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


class OrdersDisabled(Exception):
    """TRADEHUB_PAPER_ORDERS is not "on": nothing was sent."""


class DuplicateOrder(Exception):
    """Alpaca already has an order with this client_order_id: it was sent before (a re-run), not sent twice."""


class OrderRejected(Exception):
    """Alpaca refused the order (not shortable, market closed, insufficient buying power...)."""


class OrderGone(Exception):
    """The order to cancel already filled or was already cancelled."""


def orders_enabled(book: str | None = None) -> bool:
    from tradehub.portfolio.books import orders_enabled as _book_enabled

    return _book_enabled(book)


def _price(p: float) -> str:
    return f"{p:.2f}" if p >= 1 else f"{p:.4f}"


def submit(symbol: str, qty: int, side: Literal["buy", "sell"], client_order_id: str, *,
           order_type: str = "market", time_in_force: str = "opg", limit_price: float | None = None,
           stop_price: float | None = None, trail_percent: float | None = None,
           order_class: str | None = None, take_profit_price: float | None = None,
           book: str | None = None, session=requests) -> dict[str, Any]:
    if order_type not in ORDER_TYPES or time_in_force not in TIMES_IN_FORCE or side not in ("buy", "sell"):
        raise ValueError(f"unsupported order: {order_type}/{time_in_force}/{side}")
    protective = order_type in ("stop", "trailing_stop") or time_in_force == "gtc" or order_class is not None
    sanctioned = STOP_TAG.match(client_order_id) or MACHINE_STOP_TAG.match(client_order_id)
    if protective and not (sanctioned and time_in_force == "gtc"
                           and order_type in ("stop", "trailing_stop", "limit")):
        raise ValueError("stops and good-till-cancelled orders are only sanctioned protective orders "
                         "(an idea- stop tag or a machine ext- stop tag)")
    if order_class not in (None, "oco"):
        raise ValueError(f"unsupported order class: {order_class}")
    if order_class == "oco" and not (order_type == "limit" and take_profit_price and stop_price):
        raise ValueError("a one-cancels-other exit needs a take-profit price and a stop price")
    if order_type == "limit" and not (limit_price or order_class == "oco"):
        raise ValueError("a limit order needs a limit price")
    if order_type == "stop" and not stop_price:
        raise ValueError("a stop order needs a stop price")
    if order_type == "trailing_stop" and not trail_percent:
        raise ValueError("a trailing stop needs a trail percent")
    if int(qty) != qty or qty < 1:
        raise ValueError(f"qty must be a whole number of shares, got {qty}")
    if not orders_enabled(book):
        raise OrdersDisabled("the book's order switch is off")
    body = {"symbol": symbol, "qty": str(int(qty)), "side": side, "type": order_type, "time_in_force": time_in_force,
            "client_order_id": client_order_id}
    if order_class == "oco":
        body.update({"order_class": "oco", "take_profit": {"limit_price": _price(take_profit_price)},
                     "stop_loss": {"stop_price": _price(stop_price)}})
    elif order_type == "limit":
        body["limit_price"] = _price(limit_price)
    if order_type == "stop":
        body["stop_price"] = _price(stop_price)
    if order_type == "trailing_stop":
        body["trail_percent"] = f"{trail_percent:g}"
    return _post_order(body, client_order_id, book, session)


def _post_order(body: dict, client_order_id: str, book: str | None, session) -> dict[str, Any]:
    """The file's one POST call site: every order (single, OCO, multi-leg) funnels
    through here, so the host pin and the error ladder exist exactly once."""
    response = session.post(PAPER_BASE + "/v2/orders", headers=_headers(book), json=body, timeout=10)
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


def submit_mleg(legs: list[dict], qty: int, limit_price: float, client_order_id: str, *,
                book: str | None = None, session=requests) -> dict[str, Any]:
    """One multi-leg option order (Kevin, 2026-11-03): a defined-risk vertical placed
    as a unit, so the short leg is evaluated as part of a spread -- sent on its own it
    reads as an uncovered contract and Alpaca refuses it (Idea 50, 2026-11-03). The
    limit price is the NET price: positive is a debit paid, negative a credit taken
    (Alpaca's convention for mleg orders). Legs carry position_intent so opens and
    closes never blur."""
    from tradehub.portfolio.options import is_occ

    if not 2 <= len(legs) <= 4:
        raise ValueError(f"a multi-leg order takes 2-4 legs, got {len(legs)}")
    for leg in legs:
        if not is_occ(str(leg.get("symbol", ""))):
            raise ValueError(f"not an option contract: {leg.get('symbol')!r}")
        if leg.get("side") not in ("buy", "sell"):
            raise ValueError(f"unsupported leg side: {leg.get('side')!r}")
        if leg.get("position_intent") not in ("buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"):
            raise ValueError(f"unsupported position intent: {leg.get('position_intent')!r}")
    if int(qty) != qty or qty < 1:
        raise ValueError(f"qty must be a whole number of contracts, got {qty}")
    if not orders_enabled(book):
        raise OrdersDisabled("the book's order switch is off")
    body = {"order_class": "mleg", "type": "limit", "time_in_force": "day", "qty": str(int(qty)),
            "limit_price": _price(limit_price), "client_order_id": client_order_id,
            "legs": [{"symbol": leg["symbol"], "side": leg["side"],
                      "ratio_qty": str(leg.get("ratio_qty", 1)),
                      "position_intent": leg["position_intent"]} for leg in legs]}
    return _post_order(body, client_order_id, book, session)


EXT_TAG = re.compile(r"^ext-\d+-[A-Za-z0-9_-]+$")


def _delete_order(order_id: str, *, book: str | None = None, session=requests) -> None:
    """The module's one DELETE call site (a test counts them): every cancel path funnels
    through here, after its own tag guard has decided the order is its to cancel."""
    response = session.delete(PAPER_BASE + f"/v2/orders/{order_id}", headers=_headers(book), timeout=10)
    if response.status_code == 401:
        raise AccountNotConnected("Alpaca rejected the keys (HTTP 401)")
    if response.status_code in (404, 422):
        raise OrderGone(order_id)
    if response.status_code >= 400:
        raise OrderRejected(f"HTTP {response.status_code}")


def cancel_machine_order(order_id: str, client_order_id: str, *, book: str | None = None,
                         session=requests) -> None:
    """Cancel one machine-API order (ext- tag only): the machine door's counterpart to
    cancel(). Each refuses the other's orders before any request, so neither path can be
    talked into touching an order family it does not own."""
    if not EXT_TAG.match(client_order_id or "") or not ORDER_ID.match(order_id or ""):
        raise ValueError("only the machine API's own ext- orders can be cancelled this way")
    if not orders_enabled(book):
        raise OrdersDisabled("the book's order switch is off")
    _delete_order(order_id, book=book, session=session)


def cancel(order_id: str, client_order_id: str, *, book: str | None = None, session=requests) -> None:
    """Cancel one protective order the hub placed (stop tag only). Anything else is refused before any request."""
    if not STOP_TAG.match(client_order_id or "") or not ORDER_ID.match(order_id or ""):
        raise ValueError("only the hub's own stop orders can be cancelled")
    if not orders_enabled(book):
        raise OrdersDisabled("the book's order switch is off")
    _delete_order(order_id, book=book, session=session)
