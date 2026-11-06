"""A copyable trade rule on the 15-minute oil and gas markets, kept as a paper record (Kevin, 2026-11-05).

The rule, fixed here before its forward record starts:
  At the model's freeze (about 5 minutes into each 15-minute window), if the model's chance beats
  the price of a side by 10 points or more, buy that side at its ask, one contract, and hold it to
  the window's close. No early exit. No trade on windows frozen between 4:45 and 6:30 PM New York
  time, around the daily futures halt (amended 2026-11-05, before the forward record started).

It is graded only on rows the journal froze before the window settled, at the quotes frozen with
them, after Kalshi's taker fee. Rows frozen before PREREG_AT are the replay that suggested the rule
(Nov 4-5: 49 trades, +9.7c a contract); only rows after it count toward going live. Nothing here
places an order. Fills at the quoted ask are assumed; the book's depth is not recorded.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradehub.journal import store
from tradehub.oil_live import TAKER_FEE_RATE

NY = ZoneInfo("America/New_York")
MIN_EDGE = 0.10
# Moved from 2026-11-06 00:00 UTC when the halt exclusion was added: the amended rule could not deploy
# before the first start, so its forward record starts a day later.
PREREG_AT = "2026-11-07T00:00:00+00:00"
HALT_ET = (16.75, 18.5)  # 4:45 PM to 6:30 PM New York time
READY_TRADES = 300
SERIES = (("oil_wti_15m", "wti-15m-v2", "WTI"), ("oil_brent_15m", "brent-15m-v2", "Brent"),
          ("natgas_15m", "natgas-15m-v2", "Natural gas"))
RULE = ("At the freeze, about 5 minutes into each 15-minute window: if the model's chance beats a "
        "side's price by 10 points or more, buy that side at its ask and hold it to the close. "
        "No trades from 4:45 to 6:30 PM ET, around the daily futures halt.")


def in_halt(frozen_at: str) -> bool:
    """CME halts oil and gas futures 5-6 PM ET while the model's tape keeps trading: no trade around it."""
    t = datetime.fromisoformat(frozen_at).astimezone(NY)
    return HALT_ET[0] <= t.hour + t.minute / 60 < HALT_ET[1]


def pick(p: float, *, yes_ask: float | None, yes_bid: float | None) -> tuple[str, float] | None:
    """The side to buy and its cost, or None. The NO side costs 1 - the YES bid."""
    if yes_ask is None or yes_bid is None or not 0.02 < yes_bid <= yes_ask < 0.98:
        return None
    yes_edge, no_edge = p - yes_ask, yes_bid - p
    if max(yes_edge, no_edge) < MIN_EDGE - 1e-9:
        return None
    return ("yes", round(yes_ask, 4)) if yes_edge >= no_edge else ("no", round(1 - yes_bid, 4))


def pnl(side: str, cost: float, outcome: int) -> float:
    """Per contract, after the taker fee: a YES pays when the outcome is 1, a NO when it is 0."""
    won = outcome == 1 if side == "yes" else outcome == 0
    return round((1.0 if won else 0.0) - cost - TAKER_FEE_RATE * cost * (1 - cost), 4)


def _stats(trades: list[dict]) -> dict[str, Any]:
    n = len(trades)
    if not n:
        return {"n": 0, "net_per_contract": None, "total": 0.0, "win_rate": None, "low95": None, "ready": False}
    xs = [t["pnl"] for t in trades]
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else None
    low = mean - 1.96 * sd / math.sqrt(n) if sd is not None else None
    return {"n": n, "net_per_contract": round(mean, 4), "total": round(sum(xs), 2),
            "win_rate": round(sum(x > 0 for x in xs) / n, 3),
            "low95": round(low, 4) if low is not None else None,
            "ready": n >= READY_TRADES and low is not None and low > 0}


def summarize(trades: list[dict]) -> dict[str, Any]:
    return {"replay": _stats([t for t in trades if t["frozen_at"] < PREREG_AT]),
            "forward": _stats([t for t in trades if t["frozen_at"] >= PREREG_AT])}


def record(supa) -> dict[str, Any]:
    """The public read: every settled trade the rule would have taken, replay and forward apart."""
    trades, pending = [], 0
    for forecaster, version, label in SERIES:
        rows = store.fetch_forecasts(supa, forecaster, version)
        first: dict[str, dict] = {}
        for r in sorted(rows, key=lambda r: r["frozen_at"]):
            first.setdefault(r["target"], r)  # the freeze the rule acts on is the first one
        picks = {}
        for target, r in first.items():
            if in_halt(r["frozen_at"]):
                continue
            pay = r.get("payload") or {}
            choice = pick(float(r["probability"]), yes_ask=pay.get("yes_ask"), yes_bid=pay.get("yes_bid"))
            if choice:
                picks[target] = (r, choice)
        settled = store.fetch_settlements(supa, list(picks)) if picks else {}
        for target, (r, (side, cost)) in picks.items():
            if target not in settled:
                pending += 1
                continue
            trades.append({"series": label, "target": target, "frozen_at": r["frozen_at"], "side": side,
                           "cost": cost, "model": round(float(r["probability"]), 3),
                           "outcome": settled[target], "pnl": pnl(side, cost, settled[target])})
    trades.sort(key=lambda t: t["frozen_at"], reverse=True)
    by_series = {label: _stats([t for t in trades if t["series"] == label and t["frozen_at"] >= PREREG_AT])
                 for _, _, label in SERIES}
    return {"rule": RULE, "prereg_at": PREREG_AT, "ready_trades": READY_TRADES, **summarize(trades),
            "by_series": by_series, "pending": pending, "recent": trades[:12]}
