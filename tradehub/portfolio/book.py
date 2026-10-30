"""Pure book math for the public Portfolio page: Alpaca JSON + stored snapshots in, page numbers out.

Unknown is `None`, never zero: one snapshot has no return yet, and the page shows a dash for it.
Alpaca sends numbers as strings, so everything goes through float().
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict, deque
from datetime import datetime

# Every position is manual until ideas exist (Trading HQ step 3 attributes them by client_order_id tag).
MANUAL = "No idea yet (manual)"


def _pct(new: float, old: float) -> float:
    return (new / old - 1) * 100


def positions_view(account: dict, positions: list[dict]) -> list[dict]:
    equity = float(account["equity"])
    rows = []
    for p in positions:
        value = float(p["market_value"])
        rows.append({
            "symbol": p["symbol"],
            "qty": float(p["qty"]),
            "side": p.get("side", "long"),
            "market_value": value,
            "pct_of_book": abs(value) / equity * 100 if equity else None,
            "unrealized_pl": float(p["unrealized_pl"]),
            "idea": MANUAL,
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


def closed_trades(fills: list[dict]) -> list[dict]:
    """FIFO round trips from Alpaca FILL activities. Long trades have qty > 0, shorts qty < 0."""
    lots: dict[str, deque] = defaultdict(deque)  # symbol -> [signed qty, price, time]
    trades = []
    for f in sorted(fills, key=lambda f: f["transaction_time"]):
        qty = float(f["qty"]) * (1 if f["side"] == "buy" else -1)
        price, at = float(f["price"]), f["transaction_time"]
        book = lots[f["symbol"]]
        while qty and book and (book[0][0] > 0) != (qty > 0):
            lot = book[0]
            matched = min(abs(qty), abs(lot[0]))
            signed = math.copysign(matched, lot[0])
            trades.append({
                "symbol": f["symbol"], "qty": signed, "entry_price": lot[1], "exit_price": price,
                "entered_at": lot[2], "exited_at": at, "pnl": (price - lot[1]) * signed,
                "return_pct": _pct(price, lot[1]) * (1 if signed > 0 else -1),
                "held_days": (_day(at).date() - _day(lot[2]).date()).days, "idea": MANUAL,
            })
            lot[0] -= signed
            qty += signed
            if not lot[0]:
                book.popleft()
        if qty:
            book.append([qty, price, at])
    return trades


def win_rate(trades: list[dict]) -> float | None:
    if not trades:
        return None
    return sum(1 for t in trades if t["pnl"] > 0) / len(trades) * 100
