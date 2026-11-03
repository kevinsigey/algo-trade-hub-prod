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


def protective(idea_id: int, exits, symbol: str, held: float, entry: float, stamp: date | str) -> dict | None:
    """The one resting order that protects an idea's position during the day (step 5 intraday exits), or None.

    Alpaca reserves a position's shares for one resting exit, so it is one of: a stop, a trailing stop, a
    take-profit limit, or a stop and take-profit as one-cancels-other. Prices come from the idea's average entry."""
    qty = math.floor(abs(held))
    if qty < 1 or not (exits.stop_loss_pct or exits.trailing_pct or exits.take_profit_pct):
        return None
    side_mult = 1 if held > 0 else -1
    # The stamp (YYYYMMDDHHMM from the protect job) keeps a second replacement the same day from reusing an id.
    tag = f"idea-{idea_id}-stop-{stamp:%Y%m%d}-{symbol}" if isinstance(stamp, date) else f"idea-{idea_id}-stop-{stamp}-{symbol}"
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
    if stop is None and oco:  # Alpaca returns an OCO as its take-profit limit with the stop in legs[]
        stop = next((leg.get("stop_price") for leg in order.get("legs") or [] if leg.get("stop_price")), None)
    kind = "oco" if oco else order.get("order_type") or order.get("type")
    if kind == "trailing_stop":
        stop = None  # Alpaca reports the trailing level it has computed; only the percent defines the order
    return (order["symbol"], int(float(order["qty"])), order["side"], kind, num(stop),
            num(None if oco else order.get("limit_price")), num(take if oco else None), num(order.get("trail_percent")))


# ── Option legs (Kevin, 2026-11-02: automatic legs, built as far as they safely go) ──
#
# A leg rides its underlying's target weight: in while the idea wants long exposure to
# the underlying, out when it doesn't. Contracts = qty_per_share per 100 target shares.
# Two sizing rules are Kevin's explicit calls:
# - a defined-risk vertical (every sell leg covered by a bought leg) trades at least
#   ONE contract even when the share math rounds to zero -- but only when one unit's
#   max loss fits inside the idea's size budget; if it doesn't fit, or the legs can't
#   be priced to check, the leg becomes a manual action instead of an order;
# - a covered call gets NO minimum: it needs the real 100 shares per contract.
# Orders are DAY limits at the quote mid; a missing or wide quote never becomes an
# order -- it becomes a manual action row (status "manual") for Kevin's hand.

def _opt_row(idea_id: int, occ: str, qty_signed: float, kind: str, mid: float | None, day: date,
             status: str = "send", reason: str = "") -> dict:
    side = "buy" if qty_signed > 0 else "sell"
    return {"symbol": occ, "side": side, "qty": int(abs(qty_signed)), "kind": kind, "price": mid,
            "client_order_id": f"idea-{idea_id}-auto-{day:%Y%m%d}-{occ.replace(' ', '')}-{kind}",
            "order_type": "limit", "time_in_force": "day", "limit_price": mid,
            "status": status, "reason": reason}


def _manual(idea_id: int, occ: str, qty: float, kind: str, day: date, reason: str) -> dict:
    row = _opt_row(idea_id, occ, qty, kind, None, day, "manual", reason)
    row["side"] = "buy" if kind == "close" else row["side"]
    return row


def plan_options(idea_id: int, legs: list, weights: dict[str, float], size_pct: float, equity: float,
                 spot: dict[str, float], held_contracts: dict[str, float], day: date,
                 select, mid) -> list[dict]:
    """Rows for one idea's option legs. `held_contracts`: OCC symbol -> signed contracts
    (long +, short -) from the idea's own fills. `select(leg, spot) -> OCC | None` picks
    the listed contract for a leg; `mid(occ) -> float | None` prices one (None = no
    tradable quote). Held contracts are attributed to a leg by underlying+kind+sign:
    long contracts belong to buy legs, short ones to sell legs."""
    from tradehub.portfolio.options import parse_occ

    budget = max(equity, 0) * size_pct / 100
    held_by_key: dict[tuple, dict[str, float]] = {}
    for occ, qty in held_contracts.items():
        if not qty:
            continue
        try:
            p = parse_occ(occ)
        except ValueError:
            continue
        held_by_key.setdefault((p["underlying"], p["kind"], qty > 0), {})[occ] = qty

    groups: dict[tuple, list] = {}
    for leg in legs:
        groups.setdefault((leg.underlying, leg.kind), []).append(leg)

    def vertical(group: list) -> tuple | None:
        """(buy_leg, sell_leg) when the group is exactly one defined-risk vertical."""
        buys = [l for l in group if l.side == "buy"]
        sells = [l for l in group if l.side == "sell"]
        if len(buys) != 1 or len(sells) != 1:
            return None
        b, s = buys[0], sells[0]
        protective = b.strike_pct < s.strike_pct if b.kind == "call" else b.strike_pct > s.strike_pct
        return (b, s) if protective else None

    closes: list[dict] = []
    opens: list[dict] = []

    def close_rows(leg, occs: dict[str, float], why: str = "") -> None:
        for occ, qty in sorted(occs.items()):
            m = mid(occ)
            if m is None:
                closes.append(_manual(idea_id, occ, -qty, "close", day,
                                      f"close {occ} by hand -- no tradable quote to price the exit"))
            else:
                closes.append(_opt_row(idea_id, occ, -qty, "close", m, day, reason=why))

    for (underlying, kind), group in sorted(groups.items()):
        price = spot.get(underlying, 0.0)
        active = weights.get(underlying, 0.0) > 0 and price > 0
        target_shares = math.floor(weights.get(underlying, 0.0) * budget / price) if active else 0
        vert = vertical(group)
        for leg in group:
            occs = held_by_key.get((underlying, kind, leg.side == "buy"), {})
            held_qty = sum(abs(q) for q in occs.values())
            if not active:
                if held_qty:
                    close_rows(leg, occs, "the idea no longer holds the underlying")
                continue
            want = math.floor(leg.qty_per_share * target_shares / 100)
            if want == 0 and held_qty == 0:
                if vert is None:
                    opens.append(_opt_row(idea_id, underlying, 0, "open", None, day, "skip",
                                          f"needs 100 shares per contract; the idea's {underlying} target is "
                                          f"{target_shares} shares"))
                    continue
                # Kevin's min-1 rule for defined-risk spreads, inside the budget or by hand.
                b_leg, s_leg = vert
                b_occ, s_occ = select(b_leg, price), select(s_leg, price)
                b_mid = mid(b_occ) if b_occ else None
                s_mid = mid(s_occ) if s_occ else None
                if not b_occ or not s_occ or b_mid is None or s_mid is None:
                    opens.append(_manual(idea_id, s_occ or b_occ or underlying, 1, "open", day,
                                         f"one {underlying} contract is the minimum and the spread cannot be "
                                         "priced to check it against the budget -- size it by hand"))
                    continue
                from tradehub.portfolio.options import parse_occ as _parse
                width = abs(_parse(s_occ)["strike"] - _parse(b_occ)["strike"])
                cashflow = s_mid - b_mid  # per share; + is a credit
                max_loss = (width - cashflow if cashflow >= 0 else -cashflow) * 100
                if max_loss > budget:
                    opens.append(_manual(idea_id, s_occ, 1, "open", day,
                                         f"one {underlying} spread risks ${max_loss:,.0f} at most, over this "
                                         f"idea's ${budget:,.0f} budget -- size it by hand"))
                    continue
                want = 1  # one contract per leg of the vertical
            if want == 0:  # held contracts exist but the target rounds to zero: close them
                close_rows(leg, occs, "the position rounds to zero contracts")
                continue
            # Manage each held contract: expiry first, then the roll window.
            kept = 0.0
            for occ, qty in sorted(occs.items()):
                from tradehub.portfolio.options import parse_occ as _parse
                days_left = (_parse(occ)["expiry"] - day).days
                if days_left <= 0:
                    if qty < 0:
                        opens.append(_manual(idea_id, occ, qty, "close", day,
                                             f"short {occ} is at/past expiry -- check for assignment"))
                    else:
                        closes.append(_opt_row(idea_id, occ, 0, "close", None, day, "skip",
                                               f"{occ} expired; the broker settles it"))
                    continue
                if leg.roll_days_left and days_left <= leg.roll_days_left:
                    m = mid(occ)
                    if m is None:
                        closes.append(_manual(idea_id, occ, -qty, "close", day,
                                              f"roll {occ} by hand -- no tradable quote to price the exit"))
                    else:
                        closes.append(_opt_row(idea_id, occ, -qty, "close", m, day, reason="roll window"))
                    continue
                kept += abs(qty)
            delta = want - kept
            if delta > 0:
                occ = select(leg, price)
                m = mid(occ) if occ else None
                if not occ or m is None:
                    opens.append(_manual(idea_id, occ or underlying, delta, "open", day,
                                         f"no tradable quote for the {underlying} {kind} leg -- place it by hand"))
                else:
                    signed = delta if leg.side == "buy" else -delta
                    opens.append(_opt_row(idea_id, occ, signed, "open", m, day))
            elif delta < 0:
                excess = -delta
                for occ, qty in sorted(occs.items()):
                    if excess <= 0:
                        break
                    from tradehub.portfolio.options import parse_occ as _parse
                    days_left = (_parse(occ)["expiry"] - day).days
                    if leg.roll_days_left and days_left <= max(leg.roll_days_left, 0):
                        continue  # already rolling out above
                    take = min(excess, abs(qty))
                    m = mid(occ)
                    if m is None:
                        closes.append(_manual(idea_id, occ, -math.copysign(take, qty), "close", day,
                                              f"close {occ} by hand -- no tradable quote"))
                    else:
                        closes.append(_opt_row(idea_id, occ, -math.copysign(take, qty), "close", m, day,
                                               reason="above the target contract count"))
                    excess -= take
    return closes + opens


def close_options(idea_id: int, held_contracts: dict[str, float], day: date, mid) -> list[dict]:
    """Close every contract the idea holds (kill or switch-off), at the quote mid;
    an unquotable contract becomes a manual action instead of a market order."""
    rows = []
    for occ, qty in sorted(held_contracts.items()):
        if not qty:
            continue
        m = mid(occ)
        if m is None:
            rows.append(_manual(idea_id, occ, -qty, "close", day,
                                f"close {occ} by hand -- no tradable quote to price the exit"))
        else:
            rows.append(_opt_row(idea_id, occ, -qty, "close", m, day))
    return rows
