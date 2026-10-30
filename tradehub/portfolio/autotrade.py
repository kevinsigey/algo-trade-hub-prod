"""Pure order planning for automated paper trading (Trading HQ step 4).

From an idea's target weights, its size, the account and what the idea already holds, work out the orders. Every
row is either sent or skipped with a reason; the morning job logs all of them.
- The idea's own shares only: it never sells shares it does not hold (Kevin's manual shares are untouched).
- Exposure falls before it rises: closing/reducing rows first, then opening/adding rows.
- A long-to-short flip closes today and opens the new side the next morning: Alpaca won't open a short while the
  long is still held (or the reverse).
- It never opens against the account's opposite-side position (Kevin's manual shares or another idea): FIFO would
  net the two and the idea would buy again every day.
- The 25% limit is checked on every row that adds exposure, against the whole account plus earlier rows of this run.
- Whole shares (opening/closing auction orders can't be fractional). Under 1 share or under $100 is noise, except a
  close, which is always sent so an idea can always get flat.
"""

from __future__ import annotations

import math
from datetime import date

from tradehub.workshop.spec import Execution

MAX_POSITION_PCT = 25
MIN_ORDER_USD = 100
TIF = {"open": "opg", "close": "cls", "day": "day"}


def _row(idea_id: int, symbol: str, qty: float, kind: str, price: float, day: date, ex: Execution,
         status: str = "send", reason: str = "", direction: float | None = None) -> dict:
    side = "buy" if (qty if direction is None else direction) > 0 else "sell"
    limit = None
    if ex.order_type == "limit":
        move = ex.limit_offset_bps / 1e4
        limit = round(price * (1 - move if side == "buy" else 1 + move), 2 if price >= 1 else 4)
    return {"symbol": symbol, "side": side, "qty": int(abs(qty)), "kind": kind, "price": price,
            "client_order_id": f"idea-{idea_id}-auto-{day:%Y%m%d}-{symbol}-{kind}", "order_type": ex.order_type,
            "time_in_force": TIF[ex.timing], "limit_price": limit, "status": status, "reason": reason}


def plan(idea_id: int, weights: dict[str, float], size_pct: float, equity: float, prices: dict[str, float],
         held: dict[str, float], book: dict[str, float], day: date, execution: Execution) -> list[dict]:
    """`held`: this idea's signed shares. `book`: the account's signed market value per symbol (all ideas + manual)."""
    budget = max(equity, 0) * size_pct / 100
    closing, opening = [], []
    for symbol in sorted(set(weights) | {s for s, q in held.items() if q}):
        price = prices[symbol]
        w, have = weights.get(symbol, 0.0), held.get(symbol, 0.0)
        target = math.copysign(math.floor(abs(w) * budget / price), w) if w else 0.0
        if have and (target == 0 or (have > 0) != (target > 0)):  # get flat in this symbol first
            if math.floor(abs(have)) >= 1:
                closing.append(_row(idea_id, symbol, -math.copysign(math.floor(abs(have)), have), "close", price, day,
                                    execution))
                if target:  # a flip: Alpaca won't open the other side while this side is still held
                    opening.append(_row(idea_id, symbol, target, "open", price, day, execution, "skip",
                                        "flipping sides: the close goes first, the new side opens tomorrow"))
                continue
            have = 0.0
        delta = target - have
        if w and target == 0 and have == 0:
            opening.append(_row(idea_id, symbol, 0, "open", price, day, execution, "skip",
                                f"too small: {abs(w) * size_pct:.1f}% of the account buys less than one share",
                                direction=w))
            continue
        if not delta:
            continue
        reducing = abs(target) < abs(have)
        qty = math.copysign(math.floor(abs(delta)), delta)
        kind = "close" if reducing else "open"
        if abs(qty) < 1 or abs(qty) * price < MIN_ORDER_USD:
            (closing if reducing else opening).append(
                _row(idea_id, symbol, qty, kind, price, day, execution, "skip", "too small to trade", direction=delta))
            continue
        others = book.get(symbol, 0.0) - have * price  # manual shares and other ideas, signed
        if not reducing and others and (others > 0) != (qty > 0):
            opening.append(_row(idea_id, symbol, qty, kind, price, day, execution, "skip",
                                f"the account holds the opposite side of {symbol} (manual or another idea)"))
            continue
        (closing if reducing else opening).append(_row(idea_id, symbol, qty, kind, price, day, execution))
    book = dict(book)
    for r in closing + opening:
        if r["status"] != "send":
            continue
        signed = r["qty"] * (1 if r["side"] == "buy" else -1) * prices[r["symbol"]]
        after = book.get(r["symbol"], 0.0) + signed
        if r["kind"] == "open" and equity > 0 and abs(after) / equity * 100 > MAX_POSITION_PCT:
            r["status"] = "skip"
            r["reason"] = (f"would make {r['symbol']} {abs(after) / equity * 100:.0f}% of the account; "
                           f"the limit is {MAX_POSITION_PCT}%")
            continue
        book[r["symbol"]] = after
    return closing + opening


def close_out(idea_id: int, held: dict[str, float], prices: dict[str, float], day: date) -> list[dict]:
    """Sell/cover every whole share the idea holds (kill or switch-off), always market at the next open."""
    return [_row(idea_id, s, -math.copysign(math.floor(abs(q)), q), "close", prices[s], day, Execution())
            for s, q in sorted(held.items()) if math.floor(abs(q)) >= 1]


def protective(idea_id: int, exits, symbol: str, held: float, entry: float, day: date) -> dict | None:
    """The one resting order that protects an idea's position during the day (step 5 intraday exits), or None.

    Alpaca reserves a position's shares for one resting exit, so it is one of: a stop, a trailing stop, a
    take-profit limit, or a stop and take-profit as one-cancels-other. Prices come from the idea's average entry."""
    qty = math.floor(abs(held))
    if qty < 1 or not (exits.stop_loss_pct or exits.trailing_pct or exits.take_profit_pct):
        return None
    side_mult = 1 if held > 0 else -1
    tag = f"idea-{idea_id}-stop-{day:%Y%m%d}-{symbol}"
    row = {"symbol": symbol, "qty": qty, "side": "sell" if held > 0 else "buy", "time_in_force": "gtc",
           "order_class": None, "limit_price": None, "stop_price": None, "trail_percent": None,
           "take_profit_price": None}
    rnd = lambda p: round(p, 2 if p >= 1 else 4)  # noqa: E731
    stop = rnd(entry * (1 - side_mult * exits.stop_loss_pct / 100)) if exits.stop_loss_pct else None
    target = rnd(entry * (1 + side_mult * exits.take_profit_pct / 100)) if exits.take_profit_pct else None
    if exits.trailing_pct:
        return {**row, "order_type": "trailing_stop", "trail_percent": exits.trailing_pct, "client_order_id": f"{tag}-tr"}
    if stop and target:
        return {**row, "order_type": "limit", "order_class": "oco", "stop_price": stop, "take_profit_price": target,
                "client_order_id": f"{tag}-oco"}
    if stop:
        return {**row, "order_type": "stop", "stop_price": stop, "client_order_id": f"{tag}-sl"}
    return {**row, "order_type": "limit", "limit_price": target, "client_order_id": f"{tag}-tp"}


def signature(order: dict) -> tuple:
    """What makes two protective orders the same, for a desired row or a resting Alpaca order."""
    def num(v):
        return None if v in (None, "") else round(float(v), 4)
    oco = (order.get("order_class") or "") == "oco"
    take = order.get("take_profit_price")
    if take is None and isinstance(order.get("take_profit"), dict):
        take = order["take_profit"].get("limit_price")
    if take is None and oco:
        take = order.get("limit_price")
    stop = order.get("stop_price")
    if stop is None and isinstance(order.get("stop_loss"), dict):
        stop = order["stop_loss"].get("stop_price")
    return (order["symbol"], int(float(order["qty"])), order["side"], "oco" if oco else order.get("order_type") or
            order.get("type"), num(stop), num(None if oco else order.get("limit_price")), num(take if oco else None),
            num(order.get("trail_percent")))
