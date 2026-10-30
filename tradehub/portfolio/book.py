"""Pure book math for the public Portfolio page: Alpaca JSON + stored snapshots in, page numbers out.

Unknown is `None`, never zero: one snapshot has no return yet, and the page shows a dash for it.
Alpaca sends numbers as strings, so everything goes through float().
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict, deque
from datetime import datetime

# A fill belongs to an idea by its order's client_order_id tag (`idea-<id>-...`) or a later relabel (spec §4.6).
MANUAL = "No idea yet (manual)"
TAG = re.compile(r"^idea-(\d+)-")


def tag_id(client_order_id: str | None) -> int | None:
    m = TAG.match(client_order_id or "")
    return int(m.group(1)) if m else None


def tag_fills(fills: list[dict], client_ids: dict[str, str], labels: dict[str, int | None],
              titles: dict[int, str]) -> list[dict]:
    """Add `idea_id` and `idea` (title) to each fill. A relabel beats the tag; an id not in `titles` is manual."""
    out = []
    for f in fills:
        order = f.get("order_id")
        wanted = labels[order] if order in labels else tag_id(client_ids.get(order))
        idea_id = wanted if wanted in titles else None
        out.append({**f, "idea_id": idea_id, "idea": titles[idea_id] if idea_id is not None else MANUAL})
    return out


def _pct(new: float, old: float) -> float:
    return (new / old - 1) * 100


def _split(qty: float, lots: dict[str, float]) -> list[tuple[str, float]]:
    """Shares per idea for one position: open lots on the same side, scaled down if they exceed the position."""
    same = {idea: q for idea, q in lots.items() if q and (q > 0) == (qty > 0) and idea != MANUAL}
    covered = sum(same.values())
    scale = qty / covered if abs(covered) > abs(qty) else 1.0
    parts = [(idea, q * scale) for idea, q in same.items()]
    rest = qty - sum(q for _, q in parts)
    return parts + ([(MANUAL, rest)] if abs(rest) > 1e-9 else [])


def positions_view(account: dict, positions: list[dict], open_by_idea: dict[str, dict[str, float]] | None = None
                   ) -> list[dict]:
    equity = float(account["equity"])
    rows = []
    for p in positions:
        qty, value, pl = float(p["qty"]), float(p["market_value"]), float(p["unrealized_pl"])
        for idea, part in _split(qty, (open_by_idea or {}).get(p["symbol"], {})) if qty else [(MANUAL, qty)]:
            share = part / qty if qty else 1.0
            rows.append({
                "symbol": p["symbol"],
                "qty": part,
                "side": p.get("side", "long"),
                "market_value": value * share,
                "pct_of_book": abs(value * share) / equity * 100 if equity else None,
                "unrealized_pl": pl * share,
                "idea": idea,
            })
    cash = float(account["cash"])
    rows.append({"symbol": "Cash", "qty": None, "side": None, "market_value": cash,
                 "pct_of_book": cash / equity * 100 if equity else None, "unrealized_pl": None, "idea": None})
    return rows


def composition(rows: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in rows:
        if r["idea"] is None:  # cash
            continue
        g = groups.setdefault(r["idea"], {"idea": r["idea"], "pct_of_book": 0.0, "unrealized_pl": 0.0})
        g["pct_of_book"] += r["pct_of_book"] or 0.0
        g["unrealized_pl"] += r["unrealized_pl"]
    return list(groups.values())


def _daily_closes(snapshots: list[dict]) -> list[float]:
    last_per_day: dict[str, float] = {}
    for s in snapshots:  # sorted by taken_at, so the last write per day wins
        last_per_day[s["taken_at"][:10]] = s["equity"]
    return list(last_per_day.values())


def _sharpe(snapshots: list[dict]) -> float | None:
    closes = _daily_closes(snapshots)
    if len(closes) < 5:
        return None
    returns = [b / a - 1 for a, b in zip(closes, closes[1:])]
    sd = statistics.stdev(returns)
    return statistics.mean(returns) / sd * math.sqrt(252) if sd else None


def _max_drawdown(snapshots: list[dict]) -> float:
    peak, worst = snapshots[0]["equity"], 0.0
    for s in snapshots:
        peak = max(peak, s["equity"])
        worst = min(worst, _pct(s["equity"], peak))
    return worst


def scoreboard(snapshots: list[dict]) -> dict:
    out = {"start_at": None, "equity": None, "return_pct": None, "spy_return_pct": None,
           "ahead_pts": None, "max_drawdown_pct": None, "sharpe": None}
    if not snapshots:
        return out
    first, last = snapshots[0], snapshots[-1]
    out["start_at"], out["equity"] = first["taken_at"], last["equity"]
    if len(snapshots) < 2:
        return out
    out["return_pct"] = _pct(last["equity"], first["equity"])
    out["spy_return_pct"] = _pct(last["spy_price"], first["spy_price"])
    out["ahead_pts"] = out["return_pct"] - out["spy_return_pct"]
    out["max_drawdown_pct"] = _max_drawdown(snapshots)
    out["sharpe"] = _sharpe(snapshots)
    return out


def curve(snapshots: list[dict]) -> list[dict]:
    if not snapshots:
        return []
    e0, s0 = snapshots[0]["equity"], snapshots[0]["spy_price"]
    return [{"t": s["taken_at"], "portfolio_pct": _pct(s["equity"], e0), "spy_pct": _pct(s["spy_price"], s0)}
            for s in snapshots]


def _day(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _fifo(fills: list[dict]) -> tuple[list[dict], dict[str, deque]]:
    """FIFO round trips from Alpaca FILL activities, plus the lots still open. Longs qty > 0, shorts qty < 0.
    FIFO runs per idea first: a sale closes its own idea's lots before anyone else's. A trade carries the idea
    of the lot that opened it."""
    lots: dict[str, deque] = defaultdict(deque)  # symbol -> [signed qty, price, time, idea]
    trades = []
    for f in sorted(fills, key=lambda f: f["transaction_time"]):
        qty = float(f["qty"]) * (1 if f["side"] == "buy" else -1)
        price, at = float(f["price"]), f["transaction_time"]
        book, idea = lots[f["symbol"]], f.get("idea", MANUAL)
        while qty and book and (book[0][0] > 0) != (qty > 0):
            # A closing fill takes its own idea's oldest lot first, then the oldest lot of any idea.
            at_lot = next((i for i, lot in enumerate(book) if lot[3] == idea), 0)
            lot = book[at_lot]
            matched = min(abs(qty), abs(lot[0]))
            signed = math.copysign(matched, lot[0])
            trades.append({
                "symbol": f["symbol"], "qty": signed, "entry_price": lot[1], "exit_price": price,
                "entered_at": lot[2], "exited_at": at, "pnl": (price - lot[1]) * signed,
                "return_pct": _pct(price, lot[1]) * (1 if signed > 0 else -1),
                "held_days": (_day(at).date() - _day(lot[2]).date()).days, "idea": lot[3],
            })
            lot[0] -= signed
            qty += signed
            if not lot[0]:
                del book[at_lot]
        if qty:
            book.append([qty, price, at, idea])
    return trades, lots


def closed_trades(fills: list[dict]) -> list[dict]:
    return _fifo(fills)[0]


def open_lots(fills: list[dict]) -> dict[str, dict[str, float]]:
    """Open signed quantity per symbol per idea."""
    out: dict[str, dict[str, float]] = {}
    for symbol, book in _fifo(fills)[1].items():
        for qty, _, _, idea in book:
            out.setdefault(symbol, {})
            out[symbol][idea] = out[symbol].get(idea, 0.0) + qty
    return {s: v for s, v in out.items() if v}


def win_rate(trades: list[dict]) -> float | None:
    if not trades:
        return None
    return sum(1 for t in trades if t["pnl"] > 0) / len(trades) * 100


def open_cost(fills: list[dict]) -> dict[str, dict[str, tuple[float, float]]]:
    """Open signed quantity and average entry price per symbol per idea (the base for protective stops)."""
    out: dict[str, dict] = {}
    for symbol, lots in _fifo(fills)[1].items():
        for qty, price, _, idea in lots:
            q, cost = out.setdefault(symbol, {}).get(idea, (0.0, 0.0))
            out[symbol][idea] = (q + qty, cost + qty * price)
    return {s: {i: (q, c / q) for i, (q, c) in v.items() if q} for s, v in out.items()}
