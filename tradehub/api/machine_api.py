"""Machine API machinery (phase-2 spec §1): authentication, the kill switch, caps and the
rate limit for the /api/v1 routes in main.py.

Fail closed, in the admin-auth style: a missing or malformed header, an unknown or revoked
key and an admin session JWT are all the same 401 -- the machine routes are key-only, so the
two credentials can never substitute for each other. Every call that gets past authentication
and the rate limiter writes exactly one audit event (machine_keys.record_event); the two
exceptions are deliberate: a 401 has no key to attribute the event to, and a rate-limited
caller must not be able to flood the audit table it is being throttled for.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from tradehub.api import machine_keys

SWITCH = "TRADEHUB_MACHINE_ORDERS"
_ET = ZoneInfo("America/New_York")


def machine_orders_enabled() -> bool:
    """Exactly "on", the TRADEHUB_PAPER_ORDERS pattern. Anything else is off."""
    return os.getenv(SWITCH, "").strip().strip('"') == "on"


def authenticate(supa, authorization: str | None) -> dict:
    """The key row for an `Authorization: Bearer <redacted>` header, else a 401."""
    scheme, _, token = (authorization or "").partition(" ")
    key = None
    if scheme.lower() == "bearer" and token:
        key = machine_keys.verify_key(supa, token)
    if key is None:
        raise HTTPException(status_code=401, detail="machine key required")
    return key


def position_qty(symbol: str, book: str | None = None) -> float:
    """Signed shares held in `symbol` on this book. A read failure propagates; callers fail closed."""
    from tradehub.portfolio.alpaca_paper import paper_get

    for position in paper_get("/v2/positions", book=book) or []:
        if (position.get("symbol") or "").upper() == symbol:
            return float(position.get("qty") or 0)
    return 0.0


def stop_capacity(symbol: str, side: str, book: str | None = None) -> int:
    """Whole shares a new machine protective stop may cover for `symbol`/`side`.

    A stop the machine door places must protect a position that exists: the held
    quantity on the position's own side (long for a sell stop, short for a buy stop),
    net of shares already reserved by resting orders on that side -- so a stop can
    never become a fresh short or double-sell if its entry failed or the position
    was already closed. Reads go through alpaca_paper.paper_get; any failure
    propagates, and the caller fails closed. `book` names the account (handover
    item 6: this used to read the main book whatever the caller meant); None is
    the current book, as everywhere in the portfolio package.
    """
    from tradehub.portfolio.alpaca_paper import paper_get

    held = 0.0
    for position in paper_get("/v2/positions", book=book) or []:
        if (position.get("symbol") or "").upper() == symbol:
            held = float(position.get("qty") or 0)
    if side == "sell" and held <= 0:
        return 0
    if side == "buy" and held >= 0:
        return 0
    reserved = 0.0
    for order in paper_get("/v2/orders", {"status": "open", "limit": 500}, book=book) or []:
        if (order.get("symbol") or "").upper() == symbol and order.get("side") == side:
            reserved += float(order.get("qty") or 0)
    return max(0, int(abs(held)) - int(reserved))


def key_book(key: dict) -> str:
    """The book a key is bound to (Kevin, 2026-11-03). Rows minted before the book
    column -- and any row a caller hands us without one -- read as the main book,
    which is the only book that existed when they were created."""
    return key.get("book") or "main"


def resolve_book(supa, key: dict, requested: str | None, route: str) -> str:
    """The book a machine READ may serve. No parameter means the key's own book; a
    parameter naming another book is a 403, audited like a scope refusal -- a key
    only ever sees its own book, and the refusal is stated rather than silently
    serving the key's book under the requested name. An unknown book name is a
    422, as the reads answered before keys carried books."""
    from tradehub.portfolio import books

    own = key_book(key)
    if requested is None:
        return own
    if requested not in books.names():
        raise HTTPException(status_code=422, detail=f"unknown book: {requested}")
    if requested != own:
        machine_keys.record_event(supa, key["id"], route, "refused:book",
                                  detail=f"key is bound to {own}")
        raise HTTPException(status_code=403,
                            detail=f"this key is bound to the {own} book")
    return own


def require_scope(supa, key: dict, scope: str, route: str) -> None:
    if scope not in key.get("scopes", []):
        machine_keys.record_event(supa, key["id"], route, "refused:scope",
                                  detail=f"needs {scope}")
        raise HTTPException(status_code=403, detail=f"this key lacks the {scope} scope")


class RateLimiter:
    """In-process token bucket, 60 requests/minute/key (spec §1.4). One API process today;
    this is a seatbelt against a runaway loop, not a distributed-systems claim."""

    def __init__(self, capacity: int = 60, window: timedelta = timedelta(minutes=1)):
        self.capacity = capacity
        self.rate = capacity / window.total_seconds()
        self._buckets: dict[int, tuple[float, datetime]] = {}
        self._lock = threading.Lock()

    def allow(self, key_id: int, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            tokens, last = self._buckets.get(key_id, (float(self.capacity), now))
            tokens = min(float(self.capacity), tokens + (now - last).total_seconds() * self.rate)
            if tokens < 1.0:
                self._buckets[key_id] = (tokens, now)
                return False
            self._buckets[key_id] = (tokens - 1.0, now)
            return True


LIMITER = RateLimiter()


def check_rate_limit(key: dict) -> None:
    if not LIMITER.allow(key["id"]):
        raise HTTPException(status_code=429, detail="rate limit: 60 requests/minute per key")


def namespace(key: dict, caller_id: str) -> str:
    """The server-side id namespace (spec §1.3): ext-<key_id>-<caller value>."""
    return f"ext-{key['id']}-{caller_id}"


def resolve_caller_id(key: dict, value: str) -> str:
    """Accept the id either as the caller supplied it or as the API returned it (namespaced);
    ownership is checked against the namespaced form either way."""
    return value if value.startswith(f"ext-{key['id']}-") else namespace(key, value)


def placed_events(supa, key_id: int) -> list[dict]:
    """This key's placement events, newest first: the audit trail doubles as the ownership
    record for the read/cancel routes (spec §1.3) -- an order is yours iff your key placed it."""
    rows = supa.table(machine_keys.EVENTS).select("*").eq("key_id", key_id) \
        .eq("outcome", "placed").order("at", desc=True).execute().data
    return [r for r in rows if r.get("client_order_id")]


def owns_event(supa, key_id: int, namespaced_id: str) -> dict | None:
    for event in placed_events(supa, key_id):
        if event["client_order_id"] == namespaced_id:
            return event
    return None


OPEN_STATUSES = frozenset({"new", "accepted", "pending_new", "partially_filled",
                           "held", "accepted_for_bidding"})


def broker_order_view(order: dict) -> dict:
    """One broker order, normalized for the staged-orders views: what it is, what it
    costs, how much has filled -- the fields a staged book is checked against."""
    def num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {"alpaca_order_id": order.get("id"), "client_order_id": order.get("client_order_id"),
            "symbol": order.get("symbol"), "side": order.get("side"),
            "type": order.get("type"), "time_in_force": order.get("time_in_force"),
            "qty": num(order.get("qty")), "filled_qty": num(order.get("filled_qty")),
            "limit_price": num(order.get("limit_price")), "stop_price": num(order.get("stop_price")),
            "status": order.get("status"), "submitted_at": order.get("submitted_at"),
            "filled_avg_price": num(order.get("filled_avg_price"))}


def open_broker_orders(book: str | None = None) -> list[dict]:
    """Every order resting on the paper account, whatever placed it (machine API, the
    hub's protective machinery, or the Alpaca app): the staged book as the broker sees it."""
    from tradehub.portfolio.alpaca_paper import paper_get

    page = paper_get("/v2/orders", {"status": "open", "direction": "asc", "limit": 500}, book=book) or []
    return [broker_order_view(o) for o in page]


def broker_orders(book: str | None = None) -> dict[str, dict]:
    """client_order_id -> the broker's order, over the newest 500 orders on the account.
    An order older than that window reads as unknown status and cannot be cancelled through
    the API -- a bounded v1 window, stated here rather than discovered in production.
    `book` names the account (item 6); None is the current book."""
    from tradehub.portfolio.alpaca_paper import paper_get

    page = paper_get("/v2/orders", {"status": "all", "direction": "desc", "limit": 500}, book=book)
    return {o["client_order_id"]: o for o in page if o.get("client_order_id")}


def plan_chunks(total_qty: int, price: float | None, key: dict) -> list[int]:
    """Child quantities for a split (parent) order: greedy chunks that each satisfy
    BOTH per-order caps -- max_qty, and max_notional at the order's pricing basis
    (limit at its limit, market at the latest trade). An empty plan means a single
    share already breaks the notional cap: unplaceable, stated rather than chunked
    into a child the caps would refuse."""
    per = int(key["max_qty"])
    if price:
        per = min(per, int(float(key["max_notional"]) // price))
    if per < 1:
        return []
    out, left = [], int(total_qty)
    while left > 0:
        take = min(per, left)
        out.append(take)
        left -= take
    return out


def validate_order(supa, key: dict, spec: dict, *, dry_run: bool = False) -> dict:
    """The placement validators, shared verbatim by POST /api/v1/orders and the
    preflight route (2026-11-08): one code path, so a dry run can never promise
    what the real call would refuse. `spec` carries the order fields (symbol, qty,
    side, order_type, time_in_force, limit_price, stop_price, split); qty is the
    TOTAL for a split, whose per-child caps the returned chunk plan enforces.

    Returns {refusal, price, chunks, checks, symbol, book, daily_used, breaker}:
    `refusal` is the (outcome, status, detail) the live route audits and raises, or
    None when the order may proceed; `checks` is the same walk, one entry per gate,
    for the preflight response. A dry run never fires the breaker notice -- a
    question must not page anyone."""
    from tradehub.portfolio import books, breakers
    from tradehub.portfolio.alpaca_paper import AccountNotConnected, latest_price
    from tradehub.workshop.spec import TICKER

    checks: list[dict] = []
    out: dict = {"refusal": None, "price": None, "chunks": [], "checks": checks,
                 "symbol": "", "book": key_book(key), "daily_used": None, "breaker": None}

    def gate(name: str, ok: bool, detail: str, refusal: tuple | None = None) -> bool:
        checks.append({"name": name, "ok": ok, "detail": detail, "blocking": True})
        if not ok:
            out["refusal"] = refusal
        return ok

    book = out["book"]
    if not gate("book", book in books.names(), f"orders land on the {book} book",
                ("book", 422, f"this key is bound to an unknown book: {book}")):
        return out
    if not gate("machine_switch", machine_orders_enabled(),
                "machine orders are switched on" if machine_orders_enabled()
                else "machine orders are switched off (TRADEHUB_MACHINE_ORDERS)",
                ("switch_off", 409, "machine orders are switched off (TRADEHUB_MACHINE_ORDERS)")):
        return out
    symbol = str(spec.get("symbol") or "").strip().upper()
    out["symbol"] = symbol
    if not gate("symbol", bool(TICKER.match(symbol)), f"{symbol} is a ticker",
                ("validation", 422, f"not a ticker: {spec.get('symbol')!r}")):
        return out
    side = spec.get("side")
    if not gate("side", side in ("buy", "sell"), "side is buy or sell",
                ("validation", 422, "side must be buy or sell")):
        return out
    order_type, tif = spec.get("order_type") or "market", spec.get("time_in_force") or "day"
    limit_price, stop_price = spec.get("limit_price"), spec.get("stop_price")
    split = bool(spec.get("split"))
    qty = int(spec.get("qty") or 0)
    shape: tuple | None = None
    if order_type not in ("market", "limit", "stop"):
        shape = ("order_type", 422, "machine orders are market, limit or stop only")
    elif split and order_type == "stop":
        shape = ("validation", 422, "a protective stop is placed as one order; split is for market and limit orders")
    elif order_type == "stop":
        if tif != "gtc":
            shape = ("order_type", 422, "a machine stop is good-till-cancelled: time_in_force must be gtc")
        elif stop_price is None:
            shape = ("order_type", 422, "a stop order needs a stop_price")
        elif limit_price is not None:
            shape = ("order_type", 422, "limit_price is for limit orders")
    else:
        if tif not in ("opg", "cls", "day"):
            shape = ("validation", 422, "time_in_force must be opg, cls or day")
        elif stop_price is not None:
            shape = ("order_type", 422, "stop_price is for stop orders")
        elif order_type == "limit" and limit_price is None:
            shape = ("order_type", 422, "a limit order needs a limit_price")
        elif order_type == "market" and limit_price is not None:
            shape = ("order_type", 422, "limit_price is for limit orders")
    if not gate("order_shape", shape is None,
                "the order shape is one the machine door takes", shape):
        return out
    if split:
        gate("max_qty", True, f"the total {qty} is chunked under the per-order cap of {key['max_qty']}")
    elif not gate("max_qty", qty <= int(key["max_qty"]),
                  f"{qty} within the per-order cap of {key['max_qty']}",
                  ("max_qty", 429, f"cap exceeded: max_qty is {key['max_qty']} per order for this key")):
        return out
    price: float | None = None
    if order_type == "stop":
        try:
            capacity = stop_capacity(symbol, side, book=book)
        except AccountNotConnected:
            gate("position", False, "the paper account is not connected",
                 ("account", 424, "the paper account is not connected"))
            return out
        except Exception:  # noqa: BLE001 -- an unverifiable position is an unplaceable stop
            gate("position", False, "positions could not be read; the stop cannot be checked",
                 ("position_unverified", 424, "positions could not be read; the stop cannot be checked"))
            return out
        if not gate("position", qty <= capacity,
                    f"{qty} within the {capacity} uncovered shares held in {symbol}",
                    ("position", 422,
                     f"a {side} stop for {qty} exceeds the {capacity} uncovered shares held in {symbol}")):
            return out
        price = float(stop_price)  # the cap prices a stop at its stop, like a limit at its limit
        checks.append({"name": "pricing", "ok": True, "blocking": True,
                       "detail": f"priced at the stop {price}"})
    elif order_type == "limit":
        price = float(limit_price)  # the cap prices a limit at its limit: no estimate involved
        checks.append({"name": "pricing", "ok": True, "blocking": True,
                       "detail": f"priced at the limit {price}"})
    else:
        try:
            price = float(latest_price(symbol))
        except Exception:  # noqa: BLE001 -- an unpriceable order is an uncheckable cap: fail closed
            gate("pricing", False, f"no latest price for {symbol}; the notional cap cannot be checked",
                 ("notional_unpriced", 424, f"no latest price for {symbol}; the notional cap cannot be checked"))
            return out
        checks.append({"name": "pricing", "ok": True, "blocking": True,
                       "detail": f"priced at the latest trade {price}"})
    out["price"] = price
    if split:
        chunks = plan_chunks(qty, price, key)
        if not gate("max_notional", bool(chunks),
                    f"{len(chunks)} children, each under the ${float(key['max_notional']):,.0f} cap",
                    ("max_notional", 429,
                     f"cap exceeded: one share at {price} already exceeds max_notional "
                     f"${float(key['max_notional']):,.0f} for this key")):
            return out
        out["chunks"] = chunks
    else:
        if not gate("max_notional", price * qty <= float(key["max_notional"]),
                    f"${price * qty:,.0f} under the ${float(key['max_notional']):,.0f} per-order cap",
                    ("max_notional", 429,
                     f"cap exceeded: max_notional is ${float(key['max_notional']):,.0f} per order for this key")):
            return out
        out["chunks"] = [qty]
    used = placed_today(supa, key["id"])
    out["daily_used"] = used
    planned = len(out["chunks"])
    if not gate("daily_cap", used + planned <= int(key["daily_cap"]),
                f"{used} placed today, {planned} planned, cap {key['daily_cap']}",
                ("daily_cap", 429, f"cap exceeded: daily_cap is {key['daily_cap']} orders/day for this key")):
        return out
    breaker = breakers.check(supa, book)
    out["breaker"] = breaker
    if breaker["tripped"] and order_type != "stop":  # a stop is already fenced to protect held shares
        try:
            closing = breakers.closes_position(side, qty, position_qty(symbol, book=book))
        except Exception:  # noqa: BLE001 -- can't tell it's a closing order, so it isn't one
            gate("circuit_breaker", False, "positions could not be read; the circuit breaker cannot pass this order",
                 ("position_unverified", 424, "positions could not be read; the circuit breaker cannot pass this order"))
            return out
        if not closing:
            if not dry_run:
                breakers.notify(supa, book, breaker)
            gate("circuit_breaker", False, f"circuit breaker: {'; '.join(breaker['reasons'])}. Only closing orders pass.",
                 ("circuit_breaker", 409, f"circuit breaker: {'; '.join(breaker['reasons'])}. Only closing orders pass."))
            return out
    gate("circuit_breaker", True,
         "the book's circuit breaker is not tripped" if not breaker["tripped"]
         else "the breaker is tripped but this order closes or protects a position")
    return out


def group_events(supa, key_id: int, namespaced_group: str, caller_group_id: str) -> list[dict]:
    """The placed events of one split group, child order first to last. Membership is
    the `group:<caller id>` marker the placement wrote on each child's audit row,
    cross-checked against the child's namespaced id shape -- so one caller's `trim`
    can never swallow another's `trim-2`."""
    out = []
    for event in placed_events(supa, key_id):
        cid = event.get("client_order_id") or ""
        if not cid.startswith(namespaced_group + "-"):
            continue
        if not cid[len(namespaced_group) + 1:].isdigit():
            continue
        if not (event.get("detail") or "").startswith(f"group:{caller_group_id}"):
            continue
        out.append(event)
    return sorted(out, key=lambda e: int(e["client_order_id"].rsplit("-", 1)[1]))


def rollup_status(views: list[dict]) -> str:
    """One status for a split group from its children's broker views."""
    total = sum(v.get("qty") or 0 for v in views)
    filled = sum(v.get("filled_qty") or 0 for v in views)
    if total and filled >= total:
        return "filled"
    if filled > 0:
        return "partially_filled"
    statuses = [v.get("status") for v in views]
    if any(s in OPEN_STATUSES for s in statuses):
        return "open"
    if statuses and len(set(statuses)) == 1:
        return statuses[0]
    return "unknown" if not statuses else "canceled"


def weighted_fill_price(views: list[dict]) -> float | None:
    """The group's volume-weighted fill price; None until something has filled."""
    filled = sum(v.get("filled_qty") or 0 for v in views)
    if not filled:
        return None
    return sum((v.get("filled_qty") or 0) * v["filled_avg_price"]
               for v in views if v.get("filled_avg_price") is not None) / filled


def placed_today(supa, key_id: int, *, now: datetime | None = None) -> int:
    """Today's placements for the daily cap, counted from the audit trail itself (the ET
    trading day): the counter and the record are the same rows, so they cannot disagree."""
    now = now or datetime.now(timezone.utc)
    day_start = datetime.combine(now.astimezone(_ET).date(), time.min, tzinfo=_ET)
    rows = supa.table(machine_keys.EVENTS).select("at").eq("key_id", key_id) \
        .eq("outcome", "placed").execute().data
    count = 0
    for r in rows:
        try:
            at = datetime.fromisoformat(str(r["at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if at >= day_start:
            count += 1
    return count
