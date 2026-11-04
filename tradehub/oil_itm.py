"""Freeze + grade the Oil page's best-strike picks (Kevin, 2026-11-03).

The live ladder computes a pick every poll (tradehub/oil_live.py);
this module makes it a RECORD: once per event, inside the freeze window
(25-35 minutes to close), the pick is stored. After the event settles,
the pick grades against Kalshi's settlement value for the event: a YES
hits when the value closes above the strike, a NO when it doesn't. The EV
column is per contract at the frozen cost, after Kalshi's taker fee: would
paying that price have paid? Nothing here trades or tunes anything; the read feeds the hourly
model's calibration review.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from tradehub.journal.forecasters.oil_hourly import SERIES
from tradehub.oil_live import TAKER_FEE_RATE, live_ladder

log = logging.getLogger(__name__)

FREEZE_MIN, FREEZE_MAX = 25.0, 35.0
TABLE = "oil_itm_lines"


def in_freeze_window(minutes_to_close: float) -> bool:
    return FREEZE_MIN <= minutes_to_close <= FREEZE_MAX


def grade(side: str, strike: float, cost: float, settled_value: float) -> tuple[bool, float]:
    """(hit, net per contract at the frozen cost, after the taker fee)."""
    hit = (settled_value > strike) == (side == "yes")
    return hit, round((1.0 if hit else 0.0) - cost - TAKER_FEE_RATE * cost * (1 - cost), 4)


def run(supa, *, now: datetime | None = None, live=None,
        ladder_fn=live_ladder) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    summary = {"graded": 0, "frozen": None}

    # Grade anything settled: the event's Kalshi settlement value decides.
    try:
        from tradehub.data.kalshi_live import KalshiLive

        client = live or KalshiLive()
        settled = {o.name: o.value for o in client.settled_values_recent(SERIES, 72)}
    except Exception:  # noqa: BLE001 -- grading resumes next run; freezing matters more
        settled = {}
    if settled:
        pending = (supa.table(TABLE).select("*").eq("settled", False)
                   .execute().data or [])
        for row in pending:
            value = settled.get(row["event_ticker"])
            if value is None:
                continue
            hit, ev = grade(row.get("side") or "yes", float(row["strike"]),
                            float(row.get("cost") or row["market"]), value)
            (supa.table(TABLE).update({"settled": True, "hit": hit, "ev": ev,
                                       "settled_value": value,
                                       "settled_at": now.isoformat()})
             .eq("id", row["id"]).execute())
            summary["graded"] += 1

    # Freeze this hour's pick, once, inside the window.
    view = ladder_fn(now)
    if view.get("state") == "live" and view.get("best") \
            and in_freeze_window(float(view.get("minutes_to_close") or 0)):
        event = view["event"]
        existing = (supa.table(TABLE).select("id").eq("event_ticker", event)
                    .execute().data or [])
        if not existing:
            best = view["best"]
            (supa.table(TABLE).insert({
                "event_ticker": event, "strike": best["strike"], "side": best["side"], "ours": best["prob"],
                "market": best["cost"], "cost": best["cost"], "edge_pts": best["edge_pts"],
                "live_price": view.get("live_price"),
                "frozen_at": now.isoformat(),
            }).execute())
            summary["frozen"] = event
    return summary


def _backtest(supa) -> dict[str, Any] | None:
    try:
        rows = supa.rpc("oil_best_strike_backtest").execute().data or []
    except Exception:  # noqa: BLE001 -- unknown is shown as unknown; the record still reads
        log.exception("oil: best-strike backtest unreadable")
        return None
    return rows[0] if rows else None


def record(supa) -> dict[str, Any]:
    """The public read: how the frozen picks have done, and the rule replayed over the journal."""
    rows = (supa.table(TABLE).select("*").order("frozen_at", desc=True)
            .limit(500).execute().data or [])
    settled = [r for r in rows if r.get("settled")]
    hits = sum(1 for r in settled if r.get("hit"))
    evs = [float(r["ev"]) for r in settled if r.get("ev") is not None]
    recent = [{"event_ticker": r["event_ticker"], "strike": float(r["strike"]), "side": r.get("side") or "yes",
               "ours": float(r["ours"]), "market": float(r["market"]),
               "settled": bool(r.get("settled")), "hit": r.get("hit"),
               "frozen_at": r["frozen_at"]} for r in rows[:8]]
    return {"frozen": len(rows), "settled": len(settled), "hits": hits,
            "hit_rate": round(hits / len(settled), 3) if settled else None,
            "net_per_contract": round(sum(evs) / len(evs), 4) if evs else None,
            "backtest": _backtest(supa),
            "recent": recent}
