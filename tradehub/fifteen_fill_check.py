"""Gas fill check: could the 15-minute rule's gated gas trades have filled?

Backlog model item 1 (Nov 12): the shadow record assumes a fill at the
frozen ask. Since PR #472 the minute tape (fifteen_min_ticks) carries the
contracts on offer at each side's ask, so every settled gated gas trade
can be marked with the depth that was actually there at its freeze, and
the record can say how many would have filled -- at the record's own
1-contract unit, and at the demo runner's launch size (1% of the $500
demo start, Kevin's sizing rule).

Read-only: this module never writes. The marking joins ticks by
(series, close_time) and takes the tick nearest the decision's frozen_at
whose side size is present.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

SERIES = "KXNATGAS15M"
START_BALANCE_USD = 500.0   # the demo account's starting balance
BUDGET_PCT = 0.01           # Kevin's sizing rule (see tradehub/kalshi_demo.py)


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def demo_size(cost: float) -> int:
    """Contracts the demo places at launch for a trade frozen at `cost`:
    1% of the $500 start, minimum 1 (the runner's sizing, restated here so
    this check stands alone)."""
    if cost <= 0:
        return 0
    return max(1, math.floor(START_BALANCE_USD * BUDGET_PCT / cost))


def _side_size(tick: dict, side: str) -> float | None:
    size = tick.get("yes_ask_size" if side == "yes" else "no_ask_size")
    return None if size is None else float(size)


def mark_trades(decisions: list[dict], ticks: list[dict]) -> list[dict]:
    """One marked row per SETTLED gated gas buy in `decisions`.

    `ticks` is the tape rows for the same windows (any series rows are
    ignored unless they match a decision's series + close_time).
    """
    by_window: dict[tuple[str, str], list[dict]] = {}
    for tick in ticks:
        by_window.setdefault((tick["series"], str(tick["close_time"])), []).append(tick)

    marked = []
    for d in decisions:
        if d.get("action") != "buy" or d.get("pnl") is None:
            continue
        frozen = _dt(d["frozen_at"])
        size = None
        best_gap = None
        for tick in by_window.get((d["series"], str(d["close_time"])), []):
            tick_size = _side_size(tick, d["side"])
            if tick_size is None or tick.get("at") is None:
                continue
            gap = abs((_dt(tick["at"]) - frozen).total_seconds())
            if best_gap is None or gap < best_gap:
                best_gap, size = gap, tick_size
        sized = demo_size(float(d["cost"]))
        marked.append({
            "target": d["target"], "close_time": d["close_time"],
            "side": d["side"], "cost": float(d["cost"]),
            "pnl": float(d["pnl"]), "gate_version": d.get("gate_version"),
            "ask_size": size,
            "sized_contracts": sized,
            "would_fill_1": None if size is None else size >= 1,
            "would_fill_sized": None if size is None else size >= sized,
        })
    return marked


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[idx]


def summarize(marked: list[dict]) -> dict[str, Any]:
    """Aggregate first: totals, fill rates, and how much of the shadow
    P&L sits on trades that would actually have filled."""
    with_depth = [m for m in marked if m["ask_size"] is not None]
    fill_1 = [m for m in with_depth if m["would_fill_1"]]
    fill_sized = [m for m in with_depth if m["would_fill_sized"]]
    sizes = [m["ask_size"] for m in with_depth]
    return {
        "settled_gated": len(marked),
        "with_depth": len(with_depth),
        "without_depth": len(marked) - len(with_depth),
        "would_fill_1": len(fill_1),
        "fill_rate_1": (len(fill_1) / len(with_depth)) if with_depth else None,
        "would_fill_sized": len(fill_sized),
        "fill_rate_sized": (len(fill_sized) / len(with_depth)) if with_depth else None,
        "median_ask_size": _pct(sizes, 0.5),
        "p10_ask_size": _pct(sizes, 0.1),
        "shadow_pnl_all": round(sum(m["pnl"] for m in marked), 4),
        "shadow_pnl_with_depth": round(sum(m["pnl"] for m in with_depth), 4),
        "shadow_pnl_fillable_1": round(sum(m["pnl"] for m in fill_1), 4),
        "shadow_pnl_fillable_sized": round(sum(m["pnl"] for m in fill_sized), 4),
    }
