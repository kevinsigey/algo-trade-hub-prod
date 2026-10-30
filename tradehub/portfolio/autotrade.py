"""Pure order planning for automated paper trading (Trading HQ step 4).

From an idea's target weights, its size, the account and what the idea already holds, work out the orders. Every
row is either sent or skipped with a reason; the morning job logs all of them.
- The idea's own shares only: it never sells shares it does not hold (Kevin's manual shares are untouched).
- Exposure falls before it rises: closing/reducing rows first, then opening/adding rows.
- A long-to-short flip is two orders (close, then open): Alpaca won't reverse a position in one order.
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


def close_out(idea_id: int, held: dict[str, float], prices: dict[str, float], day: date,
              execution: Execution) -> list[dict]:
    """Sell/cover every whole share the idea holds (kill or switch-off)."""
    return [_row(idea_id, s, -math.copysign(math.floor(abs(q)), q), "close", prices[s], day, execution)
            for s, q in sorted(held.items()) if math.floor(abs(q)) >= 1]
