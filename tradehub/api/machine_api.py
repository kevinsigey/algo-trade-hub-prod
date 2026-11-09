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
import re
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


_OPEN_T = time(9, 30)
_CLOSE_T = time(16, 0)


def session_fields(order: dict, *, now: datetime | None = None) -> dict:
    """When an order actually goes live (2026-11-08): `effective_session`, the ET
    trading date whose session the order belongs to, and `session_state` --
    "held_for_open" while an accepted order is still waiting for that session,
    so a Sunday-night OPG order staged for Monday's auction is never mistaken
    for a working one. Derived from the order's own time-in-force and the NYSE
    calendar the journal already keeps (tradehub.journal.nyse); no second
    calendar is invented here."""
    from tradehub.journal import nyse

    tif = (order.get("time_in_force") or "day").lower()
    try:
        submitted = datetime.fromisoformat(str(order.get("submitted_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        submitted = now or datetime.now(_ET)
    if submitted.tzinfo is None:
        submitted = submitted.replace(tzinfo=timezone.utc)
    local = submitted.astimezone(_ET)
    day, tod = local.date(), local.time()
    if tif == "opg":
        effective = day if (nyse.is_session(day) and tod < _OPEN_T) \
            else nyse.next_session(day + timedelta(days=1))
    elif tif == "cls":
        effective = day if (nyse.is_session(day) and tod < _CLOSE_T) \
            else nyse.next_session(day + timedelta(days=1))
    elif tif == "gtc":
        effective = nyse.next_session(day)
    else:  # day / ioc / fok: live in the session they were sent into
        effective = day if (nyse.is_session(day) and tod < _CLOSE_T) \
            else nyse.next_session(day + timedelta(days=1))
    now_et = (now or datetime.now(_ET)).astimezone(_ET)
    opens = datetime.combine(effective, _OPEN_T, tzinfo=_ET)
    held = order.get("status") in OPEN_STATUSES and now_et < opens
    return {"effective_session": effective.isoformat(),
            "session_state": "held_for_open" if held else "active"}


def _leg_readback(order: dict, num) -> dict:
    """The combo read-back (2026-11-08): per-leg fills, the `expected_leg_fills`
    echo of what the placement requested (parent qty x each leg's ratio), and a
    leg_state. A parent whose legs are out of sync with its own fill -- the parent
    claims contracts a leg never delivered -- reads leg_state/status_warning
    "partial_leg_fill", never a plain filled: the Idea 50 lesson, and the IBKR
    combo-quantity lesson, is that the legs are the truth, not the headline."""
    parent_qty = num(order.get("qty"))
    parent_filled = num(order.get("filled_qty")) or 0
    views, expected = [], []
    desync, all_filled = False, True
    for leg in order.get("legs") or []:
        ratio = num(leg.get("ratio_qty")) or 1
        leg_qty = parent_qty * ratio if parent_qty is not None else num(leg.get("qty"))
        leg_filled = num(leg.get("filled_qty"))
        views.append({"symbol": leg.get("symbol"), "side": leg.get("side"),
                      "ratio_qty": ratio, "position_intent": leg.get("position_intent"),
                      "status": leg.get("status"), "qty": leg_qty,
                      "filled_qty": leg_filled,
                      "filled_avg_price": num(leg.get("filled_avg_price"))})
        expected.append({"symbol": leg.get("symbol"), "side": leg.get("side"),
                         "ratio_qty": ratio, "qty": leg_qty})
        if leg_filled is not None and abs(leg_filled - parent_filled * ratio) > 1e-9:
            desync = True
        if leg_qty is None or leg_filled is None or leg_filled < leg_qty:
            all_filled = False
    if desync and parent_filled > 0:
        state = "partial_leg_fill"
    elif all_filled:
        state = "complete"
    else:
        state = "pending"
    out = {"legs": views, "expected_leg_fills": expected, "leg_state": state}
    if state == "partial_leg_fill":
        out["status_warning"] = "partial_leg_fill"
    return out


def broker_order_view(order: dict, *, now: datetime | None = None) -> dict:
    """One broker order, normalized for the staged-orders views: what it is, what it
    costs, how much has filled -- the fields a staged book is checked against."""
    def num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    view = {"alpaca_order_id": order.get("id"), "client_order_id": order.get("client_order_id"),
            "symbol": order.get("symbol"), "side": order.get("side"),
            "type": order.get("type"), "time_in_force": order.get("time_in_force"),
            "qty": num(order.get("qty")), "filled_qty": num(order.get("filled_qty")),
            "limit_price": num(order.get("limit_price")), "stop_price": num(order.get("stop_price")),
            "status": order.get("status"), "submitted_at": order.get("submitted_at"),
            "filled_avg_price": num(order.get("filled_avg_price")),
            **session_fields(order, now=now)}
    if order.get("legs"):  # a combo carries its legs or it is not fully read
        view.update(_leg_readback(order, num))
        # The package's own net fill price, named as what it is (2026-11-09):
        # per contract of the parent, on the debit-positive convention.
        view["net_fill_price"] = num(order.get("filled_avg_price"))
    return view


_MACHINE_ID = re.compile(r"^ext-(\d+)-(?:stop-)?")
_IDEA_ID = re.compile(r"^idea-(\d+)-")


def attribute_orders(supa, views: list[dict]) -> list[dict]:
    """Who placed each resting order (2026-11-08): the staged book is broker-wide,
    and an unlabelled list invites duplicate or conflicting orders from a second
    reader. Attribution, in order: the machine id namespace names its key
    (ext-<key id>-... -> that key's label); the hub's idea-<id> family names its
    idea; the workshop label ledger (order_labels) wins wherever it has a row --
    it is the only source that knows a manual relabel. Anything else is an
    external placement (the Alpaca app) and reads "unknown", stated, not hidden."""
    try:
        key_labels = {k["id"]: k["label"] for k in machine_keys.list_keys(supa)}
    except Exception:  # noqa: BLE001 -- attribution is enrichment; the read must not fail for it
        key_labels = {}
    try:
        from tradehub.workshop import store as workshop_store

        history = workshop_store.label_history(supa)
    except Exception:  # noqa: BLE001
        history = {}
    for view in views:
        cid = view.get("client_order_id") or ""
        placed_by, idea_id, source = "unknown", None, "external"
        m = _MACHINE_ID.match(cid)
        if m:
            label = key_labels.get(int(m.group(1)))
            placed_by = f"api:{label}" if label else f"api:key {m.group(1)}"
            source = "machine"
        else:
            mi = _IDEA_ID.match(cid)
            if mi:
                idea_id, placed_by, source = int(mi.group(1)), "hub:idea engine", "hub"
        rows = history.get(view.get("alpaca_order_id") or "")
        if rows:
            latest = rows[-1]
            if latest.get("idea_id") is not None:
                idea_id = latest["idea_id"]
            if latest.get("by"):
                placed_by = latest["by"]
                source = "machine" if str(latest["by"]).startswith("api:") else source
        view.update({"placed_by": placed_by, "idea_id": idea_id, "source": source})
    return views


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


EXIT_BYPASSED_CAPS = ["max_qty", "max_notional", "daily_cap"]


def classify_share_exit(spec: dict, symbol: str, side: str, qty: int, book: str | None) -> dict:
    """The shares exit test (Kevin, 2026-11-09): a sell whose TOTAL quantity --
    for a split, the group total, which is what `qty` carries -- is no larger
    than the book's held quantity in the symbol. The order can take the position
    to zero; it can never make it negative. A buy, an oversell, a sell of an
    unheld symbol, or a position read that fails is NOT an exit: the caps apply
    in full, with no partial exemption for the covered part. The classification
    is this book math and nothing else -- a caller's `exit` claim is recorded
    (`claimed`) and reported when it disagrees, but it never decides."""
    info: dict = {"is_exit": False, "bypassed": [], "claimed": spec.get("exit_claim"),
                  "detail": ""}
    if side != "sell":
        info["detail"] = "not an exit: only a sell can close a long share position"
    else:
        try:
            held = position_qty(symbol, book=book)
        except Exception:  # noqa: BLE001 -- unprovable is unexempted: fail toward the caps
            info["detail"] = ("not an exit: positions could not be read, so the book math "
                              "cannot prove this sale only closes a position; the caps apply")
            return info
        if qty <= held:
            info["is_exit"] = True
            info["bypassed"] = list(EXIT_BYPASSED_CAPS)
            info["detail"] = (f"an exit: selling {qty} of the {held:g} {symbol} shares held "
                              "only closes the position; the machine caps do not apply to exits")
        else:
            info["detail"] = (f"not an exit: the book holds {held:g} {symbol} shares and this "
                              f"sell is for {qty}; the excess would open a short, so the caps apply")
    if info["claimed"] and not info["is_exit"]:
        info["detail"] += (" The caller marked this order an exit; the book math disagrees, "
                           "and the math wins.")
    return info


def classify_option_exit(legs: list[dict], held: dict[str, float], claim=None) -> dict:
    """The options exit test (Kevin, 2026-11-09): EVERY leg closes a position the
    book actually holds -- sell_to_close no larger than the held long,
    buy_to_close no larger than the held short (`held` is
    option_orders.positions_map: signed qty per symbol). One opening leg, or a
    close larger than the holding, makes the whole package a non-exit."""
    info: dict = {"is_exit": False, "bypassed": [], "claimed": claim, "detail": ""}
    for leg in legs:
        have = held.get(leg["symbol"], 0.0)
        intent = leg["position_intent"]
        if intent == "sell_to_close" and have >= leg["qty"]:
            continue
        if intent == "buy_to_close" and have <= -leg["qty"]:
            continue
        if intent in ("buy_to_close", "sell_to_close"):
            info["detail"] = (f"not an exit: {intent} {leg['qty']} x {leg['symbol']} exceeds "
                              f"the {abs(have):g} contracts held; the package runs under the caps")
        else:
            info["detail"] = (f"not an exit: the {leg['symbol']} leg is {intent} -- an opening "
                              "leg makes the whole package an entry under the caps")
        break
    else:
        info["is_exit"] = True
        info["bypassed"] = list(EXIT_BYPASSED_CAPS)
        info["detail"] = ("an exit: every leg closes a held position; the machine caps "
                          "do not apply to exits")
    if info["claimed"] and not info["is_exit"]:
        info["detail"] += (" The caller marked this order an exit; the book math disagrees, "
                           "and the math wins.")
    return info


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
                 "symbol": "", "book": key_book(key), "daily_used": None, "breaker": None,
                 "option": None, "portfolio_check": None,
                 "exit": {"is_exit": False, "bypassed": [], "claimed": spec.get("exit_claim"),
                          "detail": "not classified: an earlier gate refused this order"}}

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
    # Options (2026-11-09): an OCC symbol or a legs[] body leaves the share path
    # entirely -- a 21-char contract symbol is not a too-long ticker. The branch
    # runs the shared option_orders validation the Portfolio hand-order form also
    # runs, plus this door's own caps.
    from tradehub.portfolio import option_orders as _option_orders

    if spec.get("legs") or _option_orders.is_option_symbol(spec.get("symbol")):
        return _validate_option_order(supa, key, spec, out, gate, dry_run=dry_run)
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
    if not gate("qty", qty >= 1, "qty is a positive whole number of shares",
                ("validation", 422, "qty must be at least 1")):
        return out
    # Exit classification (Kevin, 2026-11-09): computed here, in the shared
    # validation layer, from the book's live positions -- an exit is exempt
    # from the qty, notional and daily caps below, and from nothing else (the
    # kill switch above and the position/breaker checks below all still run).
    exit_info = classify_share_exit(spec, symbol, side, qty, book)
    out["exit"] = exit_info
    checks.append({"name": "exit_classification", "ok": True, "blocking": False,
                   "exit": exit_info["is_exit"], "bypassed": exit_info["bypassed"],
                   "detail": exit_info["detail"]})
    is_exit = exit_info["is_exit"]
    if is_exit:
        gate("max_qty", True,
             f"bypassed for an exit: the per-order cap of {key['max_qty']} does not apply "
             "to a closing order")
    elif split:
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
            if not is_exit:
                gate("pricing", False, f"no latest price for {symbol}; the notional cap cannot be checked",
                     ("notional_unpriced", 424, f"no latest price for {symbol}; the notional cap cannot be checked"))
                return out
            # An exit needs no price: the notional cap it would feed is bypassed.
            checks.append({"name": "pricing", "ok": True, "blocking": True,
                           "detail": f"no latest price for {symbol}; an exit does not need "
                                     "one (the notional cap does not apply to a closing order)"})
        else:
            checks.append({"name": "pricing", "ok": True, "blocking": True,
                           "detail": f"priced at the latest trade {price}"})
    out["price"] = price
    if is_exit:
        gate("max_notional", True,
             "bypassed for an exit: the per-order notional cap does not apply to a "
             "closing order, so an exit places as ONE order at its full quantity")
        out["chunks"] = [qty]
    elif split:
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
    if is_exit:
        gate("daily_cap", True,
             f"an exit does not consume the daily count: {used} placed today, "
             f"cap {key['daily_cap']}")
    else:
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
    # The portfolio check (Kevin, 2026-11-09): the last gate, on the post-trade
    # book. A protective stop moves nothing unless it fills and is already fenced
    # to held shares, so it carries a stated pass instead of a book read.
    if order_type == "stop":
        out["portfolio_check"] = {
            "outcome": "pass", "blocks": [], "warnings": [],
            "detail": "protective stop: it moves the book only if it fills and is "
                      "fenced to held shares; not portfolio-checked"}
    elif price is None:
        # The exit lane's unpriced exit: no price basis exists to value the
        # delta with, so the check states itself unavailable rather than
        # guessing one. Non-blocking, like every unavailable read.
        from tradehub.portfolio import portfolio_check

        out["portfolio_check"] = {
            "outcome": "unavailable", "blocks": [], "warnings": [],
            "detail": "portfolio check unavailable: this exit carries no price, "
                      "so its post-trade weight cannot be computed"}
        portfolio_check.record_event(
            supa, book, "machine_preflight" if dry_run else "machine_order",
            symbol, out["portfolio_check"])
    else:
        signed = qty if side == "buy" else -qty
        _portfolio_gate(supa, out, gate, book, {symbol: signed * price},
                        symbol=symbol, spec=spec, dry_run=dry_run, is_exit=is_exit)
    return out


def _portfolio_gate(supa, out: dict, gate, book: str, deltas: dict, *, symbol: str,
                    spec: dict, dry_run: bool, is_exit: bool = False) -> None:
    """Run the portfolio check and fold it into the validation walk. A block is a
    refusal like any other gate's (422, outcome `portfolio_check`, naming the cap
    and the post-trade weight); a pass or a warning joins `checks` as a
    non-blocking entry; an unreadable book is stated in out["portfolio_check"]
    itself and never silently passes (check_order's contract). `is_exit` is this
    door's own classification (the #440 book math, computed by the caller): it
    lets an exit cross a member floor with a named warning instead of a block
    (Kevin's ruling, 2026-11-09) and changes nothing else."""
    from tradehub.portfolio import portfolio_check

    block = portfolio_check.check_order(
        supa, book, deltas, source="machine_preflight" if dry_run else "machine_order",
        symbol=symbol, tag=spec.get("tag"), idea_id=spec.get("idea_id"),
        is_exit=is_exit)
    out["portfolio_check"] = block
    if block["outcome"] == "block":
        detail = block["blocks"][0]["detail"]
        gate("portfolio_check", False, detail,
             ("portfolio_check", 422, f"portfolio check: {detail}"))
    elif block["outcome"] in ("pass", "warn"):
        out["checks"].append({"name": "portfolio_check", "ok": True, "blocking": False,
                              "detail": block["detail"]})


def _validate_option_order(supa, key: dict, spec: dict, out: dict, gate, *, dry_run: bool = False) -> dict:
    """The options branch of validate_order (Kevin, 2026-11-09): single-leg OCC
    orders and 2-4 leg combos. The contract, defined-risk and max-loss checks are
    tradehub.portfolio.option_orders -- the same code the Portfolio hand-order
    form runs, so the two doors cannot diverge. This branch adds the machine
    door's own fences: per-leg caps, buying power against defined-risk max loss,
    the daily cap counting a combo ONCE, and the circuit breaker. On success
    out["option"] carries the normalized placement the route submits."""
    from tradehub.portfolio import breakers, option_orders
    from tradehub.portfolio.alpaca_paper import AccountNotConnected
    from tradehub.portfolio.options import fetch_mid

    checks = out["checks"]
    book = out["book"]

    # ── shape: normalize (a single-leg order is a one-leg list) ──
    raw_legs = spec.get("legs")
    try:
        if raw_legs:
            legs = option_orders.normalize_legs(raw_legs)
            kind = "combo"
        else:
            legs = [option_orders.normalize_leg(
                {"symbol": spec.get("symbol"), "side": spec.get("side"),
                 "qty": spec.get("qty"), "position_intent": spec.get("position_intent")})]
            kind = "single"
    except option_orders.OptionOrderError as exc:
        gate("option_shape", False, str(exc), ("validation", 422, str(exc)))
        return out
    gate("option_shape", True,
         f"a {kind} option order: " + ", ".join(
             f"{leg['side']} {leg['qty']} x {leg['symbol']} ({leg['position_intent']})"
             for leg in legs))
    out["symbol"] = legs[0]["symbol"] if kind == "single" else legs[0]["parsed"]["underlying"]

    order_type = spec.get("order_type") or "market"
    tif = spec.get("time_in_force") or "day"
    limit_price = spec.get("limit_price")
    shape: tuple | None = None
    if spec.get("split"):
        shape = ("validation", 422, "split is for share orders; an option order places as one order")
    elif spec.get("stop_price") is not None:
        shape = ("order_type", 422, "stop_price is for stop orders; option orders here are market or limit")
    elif order_type not in ("market", "limit"):
        shape = ("order_type", 422, "option orders are market or limit only")
    elif tif != "day":
        shape = ("order_type", 422,
                 f"option orders are day orders through this door: Alpaca paper does not take "
                 f"{tif} on an option order, and the door will not silently downgrade it to day")
    elif kind == "combo" and order_type != "limit":
        shape = ("order_type", 422, "a combo is placed at one net limit price; market combos are not taken")
    elif kind == "combo" and (limit_price is None or float(limit_price) == 0):
        shape = ("order_type", 422,
                 "a combo needs one net limit_price (positive is a debit paid, negative a credit taken)")
    elif kind == "single" and order_type == "limit" and limit_price is None:
        shape = ("order_type", 422, "a limit order needs a limit_price")
    elif kind == "single" and order_type == "limit" and float(limit_price) <= 0:
        shape = ("order_type", 422, "a single-leg limit_price must be positive")
    elif kind == "single" and order_type == "market" and limit_price is not None:
        shape = ("order_type", 422, "limit_price is for limit orders")
    if not gate("order_shape", shape is None, "the option order shape is one this door takes", shape):
        return out

    # ── contracts exist and are tradable on this book ──
    for symbol in dict.fromkeys(leg["symbol"] for leg in legs):
        try:
            row = option_orders.contract(symbol, book)
        except AccountNotConnected:
            gate("contract", False, "the paper account is not connected",
                 ("account", 424, "the paper account is not connected"))
            return out
        except Exception:  # noqa: BLE001 -- unverifiable is unplaceable: fail closed
            gate("contract", False, f"the contract read failed for {symbol}",
                 ("contract_unverified", 424, f"the contract for {symbol} could not be verified"))
            return out
        if row is None:
            gate("contract", False, f"{symbol} is not a tradable contract on this book",
                 ("contract", 422, f"{symbol} is not a tradable option contract on this paper account"))
            return out
    first = legs[0]["parsed"]
    gate("contract", True,
         f"contracts verified on the {book} book ({first['underlying']} expiring {first['expiry']})")

    # ── held positions: the defined-risk guard's cover ledger ──
    try:
        held = option_orders.positions_map(book)
    except AccountNotConnected:
        gate("position", False, "the paper account is not connected",
             ("account", 424, "the paper account is not connected"))
        return out
    except Exception:  # noqa: BLE001
        gate("position", False, "positions could not be read; the defined-risk check cannot run",
             ("position_unverified", 424, "positions could not be read; the defined-risk check cannot run"))
        return out

    # ── exit classification (Kevin, 2026-11-09): every leg closing a held
    # position exempts the package from the per-leg and daily caps below. The
    # defined-risk guard right after this still runs and still blocks. ──
    exit_info = classify_option_exit(legs, held, spec.get("exit_claim"))
    out["exit"] = exit_info
    checks.append({"name": "exit_classification", "ok": True, "blocking": False,
                   "exit": exit_info["is_exit"], "bypassed": exit_info["bypassed"],
                   "detail": exit_info["detail"]})
    is_exit = exit_info["is_exit"]

    # ── defined risk: no naked shorts, closes backed by holdings ──
    reason = option_orders.check_defined_risk(legs, held)
    if not gate("defined_risk", reason is None,
                "defined-risk: every short is covered by a long in the package or the book"
                if reason is None else reason,
                ("defined_risk", 422, reason or "")):
        return out

    # ── pricing + per-leg caps ──
    prices: dict[str, float] = {}
    unpriced_exits: list[str] = []
    for leg in legs:
        symbol = leg["symbol"]
        if symbol not in prices:
            if kind == "single" and order_type == "limit":
                prices[symbol] = float(limit_price)
            else:
                try:
                    mid = fetch_mid(symbol, book=book)
                except AccountNotConnected:
                    gate("pricing", False, "the paper account is not connected",
                         ("account", 424, "the paper account is not connected"))
                    return out
                except Exception:  # noqa: BLE001 -- an unpriceable leg is an uncheckable cap
                    mid = None
                if mid is None:
                    if not is_exit:
                        gate("pricing", False, f"no usable quote for {symbol}; the caps cannot be checked",
                             ("notional_unpriced", 424,
                              f"no usable quote for {symbol}; the notional cap cannot be checked"))
                        return out
                    # An exit leg needs no quote: the caps it would feed are
                    # bypassed, and a pure close's max loss is 0 at any price.
                    prices[symbol] = 0.0
                    unpriced_exits.append(symbol)
                else:
                    prices[symbol] = float(mid)
        leg_price = prices[symbol]
        if is_exit:
            gate("max_qty", True,
                 f"bypassed for an exit: {leg['qty']} x {symbol} closes a held position")
            gate("max_notional", True,
                 "bypassed for an exit: the per-order notional cap does not apply "
                 "to a closing leg")
            continue
        if not gate("max_qty", leg["qty"] <= int(key["max_qty"]),
                    f"{leg['qty']} contracts within the per-order cap of {key['max_qty']}",
                    ("max_qty", 429, f"cap exceeded: max_qty is {key['max_qty']} per order for this key")):
            return out
        notional = leg_price * leg["qty"] * 100
        if not gate("max_notional", notional <= float(key["max_notional"]),
                    f"${notional:,.0f} under the ${float(key['max_notional']):,.0f} per-order cap",
                    ("max_notional", 429,
                     f"cap exceeded: max_notional is ${float(key['max_notional']):,.0f} per order for this key")):
            return out
    pricing_detail = "legs priced at " + ", ".join(f"{s} {p:g}" for s, p in prices.items())
    if unpriced_exits:
        pricing_detail += ("; no usable quote for " + ", ".join(unpriced_exits)
                           + " (an exit does not need one)")
    checks.append({"name": "pricing", "ok": True, "blocking": True, "detail": pricing_detail})

    # ── max loss (defined-risk math) vs options buying power ──
    if kind == "combo":
        parent, ratios = option_orders.parent_and_ratios(legs)
        # The package's premium is its net limit, not the sum of leg mids: the
        # limit is the worst price the caller agreed to pay.
        premium = float(limit_price) * parent * 100
    else:
        parent, ratios = legs[0]["qty"], [1]
        premium = option_orders.opening_premium(legs, prices)
    max_loss = option_orders.max_loss(legs, held, premium)
    opening = any(leg["position_intent"] in option_orders.OPEN_INTENTS for leg in legs)
    obp: float | None = None
    if opening:
        try:
            obp = option_orders.options_buying_power(book)
        except AccountNotConnected:
            gate("buying_power", False, "the paper account is not connected",
                 ("account", 424, "the paper account is not connected"))
            return out
        except Exception:  # noqa: BLE001
            gate("buying_power", False, "buying power could not be read; the max-loss check cannot run",
                 ("buying_power_unverified", 424,
                  "buying power could not be read; the max-loss check cannot run"))
            return out
        if obp is None or max_loss > obp:
            detail = (f"max loss ${max_loss:,.0f} exceeds the book's options buying power ${obp:,.0f}"
                      if obp is not None else "the account reports no options buying power")
            gate("buying_power", False, detail, ("buying_power", 422, detail))
            return out
    gate("buying_power", True,
         f"max loss ${max_loss:,.0f} within options buying power ${obp:,.0f}" if opening
         else "a closing order risks nothing new")
    out["price"] = float(limit_price) if kind == "combo" else prices[legs[0]["symbol"]]

    # ── daily cap: the package counts once, never per leg; an exit counts zero ──
    used = placed_today(supa, key["id"])
    out["daily_used"] = used
    out["chunks"] = [1]
    if is_exit:
        gate("daily_cap", True,
             f"an exit does not consume the daily count: {used} placed today, "
             f"cap {key['daily_cap']}")
    elif not gate("daily_cap", used + 1 <= int(key["daily_cap"]),
                  f"{used} placed today, 1 planned (a combo counts once), cap {key['daily_cap']}",
                  ("daily_cap", 429, f"cap exceeded: daily_cap is {key['daily_cap']} orders/day for this key")):
        return out

    # ── circuit breaker: only a pure close passes a tripped book ──
    breaker = breakers.check(supa, book)
    out["breaker"] = breaker
    if breaker["tripped"]:
        closing_only = all(leg["position_intent"] in option_orders.CLOSE_INTENTS for leg in legs)
        if not closing_only:
            if not dry_run:
                breakers.notify(supa, book, breaker)
            gate("circuit_breaker", False,
                 f"circuit breaker: {'; '.join(breaker['reasons'])}. Only closing orders pass.",
                 ("circuit_breaker", 409,
                  f"circuit breaker: {'; '.join(breaker['reasons'])}. Only closing orders pass."))
            return out
    gate("circuit_breaker", True,
         "the book's circuit breaker is not tripped" if not breaker["tripped"]
         else "the breaker is tripped but this order only closes positions")

    out["option"] = {"kind": kind, "legs": legs, "parent_qty": parent, "ratios": ratios,
                     "net_limit_price": float(limit_price) if kind == "combo" else None,
                     "max_loss": max_loss, "options_buying_power": obp,
                     "order_type": order_type}

    # The portfolio check (Kevin, 2026-11-09): the legs' exposure lands on their
    # underlying -- a bought contract adds its premium value, a sold one removes
    # it -- and the package is judged against the post-trade book like any order.
    deltas: dict[str, float] = {}
    for leg in legs:
        underlying = leg["parsed"]["underlying"]
        signed = leg["qty"] * prices[leg["symbol"]] * 100
        deltas[underlying] = deltas.get(underlying, 0.0) + (signed if leg["side"] == "buy" else -signed)
    _portfolio_gate(supa, out, gate, book, deltas,
                    symbol=legs[0]["parsed"]["underlying"], spec=spec, dry_run=dry_run,
                    is_exit=is_exit)
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


def exit_event_detail(detail: str | None, is_exit: bool) -> str | None:
    """The audit detail for a placement, with the exit marker appended when the
    order was classified an exit: `exit` as its own `; `-separated segment (the
    same marker channel the split `group:<caller id>` prefix uses, and appended
    after it, so group parsing is untouched). The outcome stays "placed" -- the
    audit vocabulary and the ownership reads do not change; only the daily
    counter reads the marker."""
    if not is_exit:
        return detail
    return f"{detail}; exit" if detail else "exit"


def detail_marks_exit(detail) -> bool:
    """True when an audit row's detail carries the exit segment."""
    if not detail:
        return False
    return "exit" in {segment.strip() for segment in str(detail).split(";")}


def placed_today(supa, key_id: int, *, now: datetime | None = None) -> int:
    """Today's placements for the daily cap, counted from the audit trail itself (the ET
    trading day): the counter and the record are the same rows, so they cannot disagree.
    Exit placements are in the trail but carry the exit marker in their detail and do
    not count (Kevin, 2026-11-09: exits are exempt from the daily cap, prospectively --
    rows written before the marker existed keep counting, exactly as they did)."""
    now = now or datetime.now(timezone.utc)
    day_start = datetime.combine(now.astimezone(_ET).date(), time.min, tzinfo=_ET)
    rows = supa.table(machine_keys.EVENTS).select("at,detail").eq("key_id", key_id) \
        .eq("outcome", "placed").execute().data
    count = 0
    for r in rows:
        try:
            at = datetime.fromisoformat(str(r["at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if at >= day_start and not detail_marks_exit(r.get("detail")):
            count += 1
    return count
