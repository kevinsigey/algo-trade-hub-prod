"""The one-click play check (Kevin, 2026-11-02): "can I run this play with the
book I have?" -- a read-only diff of an idea's target book at a chosen size
against the live paper portfolio, with a cash verdict. It never stages, places,
or modifies an order; it only reads.

The math is pure: the endpoint gathers the inputs (the engine's target weights
for today, latest closes, the portfolio read) and this module computes. Prices
are latest closes, labelled as such -- no live NBBO, no borrow check on shorts.
"""

from __future__ import annotations

from tradehub.portfolio.book import MANUAL
from tradehub.workshop.engine import MAX_POSITION_PCT

CASH_VERDICTS = ("affordable", "affordable_after_sells", "not_affordable")


def _money(x: float) -> float:
    return round(x + 0.0, 2)


def play_check(*, weights: dict[str, float], why: str, prices: dict[str, float],
               equity: float, cash: float, positions: list[dict], size_pct: float,
               own_title: str, otherwise: str, legs: list[str]) -> dict:
    """Diff the idea's target book at `size_pct`% of `equity` against the held book.

    `weights` are the engine's target weights for today (fractions of the idea's
    allocation, shorts negative, wrap blends already applied). `positions` are
    the portfolio read's rows (symbol, signed qty, signed market_value, idea
    attribution), Cash row excluded. A ticker held under another idea's title is
    an overlap: the play would add to a name another live idea already owns.
    """
    size_dollars = equity * size_pct / 100.0
    held: dict[str, dict] = {}
    for row in positions:
        sym = row["symbol"]
        if sym == "Cash":
            continue
        slot = held.setdefault(sym, {"qty": 0.0, "value": 0.0, "ideas": set()})
        slot["qty"] += float(row.get("qty") or 0.0)
        slot["value"] += float(row.get("market_value") or 0.0)
        if row.get("idea"):
            slot["ideas"].add(row["idea"])

    tickers = sorted(set(weights) | set(held), key=lambda t: -abs(weights.get(t, 0.0) * size_dollars
                                                               - held.get(t, {"value": 0.0})["value"]))
    rows, cap_breaches = [], []
    buys = sells = 0.0
    for t in tickers:
        target_value = weights.get(t, 0.0) * size_dollars
        price = prices.get(t)
        target_shares = (target_value / price) if price else None
        h = held.get(t, {"qty": 0.0, "value": 0.0, "ideas": set()})
        delta_value = target_value - h["value"]
        delta_shares = (target_shares - h["qty"]) if target_shares is not None else None
        if delta_value > 0:
            buys += delta_value
        else:
            sells -= delta_value
        pct = abs(target_value) / equity * 100 if equity else 0.0
        if pct > MAX_POSITION_PCT:
            cap_breaches.append({"ticker": t, "pct": round(pct, 1), "cap": MAX_POSITION_PCT})
        overlap = sorted(i for i in h["ideas"] if i != own_title and i != MANUAL)
        rows.append({
            "ticker": t, "weight": weights.get(t), "price": price,
            "target_value": _money(target_value),
            "target_shares": round(target_shares, 4) if target_shares is not None else None,
            "held_shares": h["qty"], "held_value": _money(h["value"]),
            "delta_value": _money(delta_value),
            "delta_shares": round(delta_shares, 4) if delta_shares is not None else None,
            "overlap_ideas": overlap,
            "cap_breach": pct > MAX_POSITION_PCT,
        })

    if buys <= cash + 1e-9:
        verdict, shortfall = "affordable", 0.0
    elif buys <= cash + sells + 1e-9:
        verdict, shortfall = "affordable_after_sells", 0.0
    else:
        verdict, shortfall = "not_affordable", buys - cash - sells

    # The rule is IN when any of its own legs carries weight today; a wrap's core
    # is held either way, so it never decides the state.
    state = "in" if any(abs(weights.get(t, 0.0)) > 0 for t in legs) else "out"
    line = _verdict_line(size_pct=size_pct, verdict=verdict, buys=buys, sells=sells,
                         shortfall=shortfall, cap_breaches=cap_breaches)
    return {
        "state": state, "exit_reason": why or None, "otherwise": otherwise,
        "size_pct": size_pct, "equity": _money(equity), "cash": _money(cash),
        "rows": rows, "buys": _money(buys), "sells": _money(sells),
        "verdict": verdict, "shortfall": _money(shortfall),
        "cap_breaches": cap_breaches, "verdict_line": line,
    }


def _verdict_line(*, size_pct: float, verdict: str, buys: float, sells: float,
                  shortfall: float, cap_breaches: list[dict]) -> str:
    if verdict == "not_affordable":
        line = f"Not runnable at {size_pct:g}% size — ${shortfall:,.0f} short on cash"
    else:
        funded = f", ${sells:,.0f} of it funded by sells" if sells > 0 else ""
        line = f"Runnable at {size_pct:g}% size — ${buys:,.0f} of buys{funded}"
        if verdict == "affordable" and sells > 0:
            line += " (cash on hand covers it before any sells)"
    if cap_breaches:
        first = cap_breaches[0]
        line += f"; {first['ticker']} would be {first['pct']:.0f}% of the account (cap {first['cap']:.0f}%)"
        if len(cap_breaches) > 1:
            line += f" + {len(cap_breaches) - 1} more over the cap"
    return line
