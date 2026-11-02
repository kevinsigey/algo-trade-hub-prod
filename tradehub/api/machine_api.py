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


def stop_capacity(symbol: str, side: str) -> int:
    """Whole shares a new machine protective stop may cover for `symbol`/`side`.

    A stop the machine door places must protect a position that exists: the held
    quantity on the position's own side (long for a sell stop, short for a buy stop),
    net of shares already reserved by resting orders on that side -- so a stop can
    never become a fresh short or double-sell if its entry failed or the position
    was already closed. Reads go through alpaca_paper.paper_get; any failure
    propagates, and the caller fails closed.
    """
    from tradehub.portfolio.alpaca_paper import paper_get

    held = 0.0
    for position in paper_get("/v2/positions") or []:
        if (position.get("symbol") or "").upper() == symbol:
            held = float(position.get("qty") or 0)
    if side == "sell" and held <= 0:
        return 0
    if side == "buy" and held >= 0:
        return 0
    reserved = 0.0
    for order in paper_get("/v2/orders", {"status": "open", "limit": 500}) or []:
        if (order.get("symbol") or "").upper() == symbol and order.get("side") == side:
            reserved += float(order.get("qty") or 0)
    return max(0, int(abs(held)) - int(reserved))


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


def open_broker_orders() -> list[dict]:
    """Every order resting on the paper account, whatever placed it (machine API, the
    hub's protective machinery, or the Alpaca app): the staged book as the broker sees it."""
    from tradehub.portfolio.alpaca_paper import paper_get

    page = paper_get("/v2/orders", {"status": "open", "direction": "asc", "limit": 500}) or []
    return [broker_order_view(o) for o in page]


def broker_orders() -> dict[str, dict]:
    """client_order_id -> the broker's order, over the newest 500 orders on the account.
    An order older than that window reads as unknown status and cannot be cancelled through
    the API -- a bounded v1 window, stated here rather than discovered in production."""
    from tradehub.portfolio.alpaca_paper import paper_get

    page = paper_get("/v2/orders", {"status": "all", "direction": "desc", "limit": 500})
    return {o["client_order_id"]: o for o in page if o.get("client_order_id")}


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
