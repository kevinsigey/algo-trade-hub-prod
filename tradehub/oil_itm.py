"""Freeze + grade the Oil page's best-strike picks (Kevin, 2026-11-03).

The live ladder computes a pick every poll (tradehub/oil_live.py);
this module makes it a RECORD: once per event, inside the freeze window
(25-35 minutes to close), the pick is stored. After the event settles,
the pick grades against Kalshi's settlement value for the event: a YES
hits when the value closes above the strike, a NO when it doesn't. The EV
column is per contract at the frozen cost, after Kalshi's taker fee: would
paying that price have paid? Nothing here trades or tunes anything; the read feeds the hourly
model's calibration review.

Picker v2 (2026-11-09, spec docs/superpowers/specs/
2026-11-09-hourly-best-strike-picker-v2-amendment.md): freezes are made
by the v2 rule -- probabilities calibrated on the journal's settled
hourly rows (tradehub/oil_calibration.py, fitted fresh per freeze with
the freeze event's close as the walk-forward cutoff), a 15-point gross
bar on the calibrated probability, and full instrumentation (quotes,
sigma, exact minutes, both probabilities, the map version). A second
freeze lands at T-10 per event as its own pick set. The v1 rows stay as
the legacy control segment (picker_version NULL); grading is unchanged
and covers every segment.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from tradehub.engines.oil_hourly import event_hour
from tradehub.journal.forecasters.oil_hourly import SERIES
from tradehub.oil_calibration import apply_map, fit_map, load_samples, pairs_before
from tradehub.oil_live import TAKER_FEE_RATE, live_ladder, pick_best_strike_v2

log = logging.getLogger(__name__)

FREEZE_MIN, FREEZE_MAX = 25.0, 35.0
# One freeze per (event, kind): T-30 in the v1 window, T-10 in a window
# as wide as the runner's ~10-minute cadence so any run phase lands
# exactly one run inside it.
FREEZE_WINDOWS = {"T-30": (FREEZE_MIN, FREEZE_MAX), "T-10": (5.0, 15.0)}
PICKER_VERSION = "v2"
TABLE = "oil_itm_lines"


def in_freeze_window(minutes_to_close: float, kind: str = "T-30") -> bool:
    low, high = FREEZE_WINDOWS[kind]
    return low <= minutes_to_close <= high


def grade(side: str, strike: float, cost: float, settled_value: float) -> tuple[bool, float]:
    """(hit, net per contract at the frozen cost, after the taker fee)."""
    hit = (settled_value > strike) == (side == "yes")
    return hit, round((1.0 if hit else 0.0) - cost - TAKER_FEE_RATE * cost * (1 - cost), 4)


def _close_of(view: dict) -> datetime:
    raw = view.get("close_time")
    if raw:
        return datetime.fromisoformat(raw)
    return event_hour(view["event"])


def _freeze_from_view(supa, view: dict, kind: str, cmap, now: datetime) -> str | None:
    """The v2 pick off one live ladder view, frozen once per
    (event, kind) under picker v2. The pick is recomputed here from the
    view's rows -- never taken from the view's own best -- so the map
    fitted for this exact event cutoff is the one that decides."""
    pick, _closest = pick_best_strike_v2(view["rows"], lambda p: apply_map(cmap, p))
    if pick is None:
        return None
    event = view["event"]
    existing = (supa.table(TABLE).select("id").eq("event_ticker", event)
                .eq("freeze_kind", kind).eq("picker_version", PICKER_VERSION)
                .execute().data or [])
    if existing:
        return None
    (supa.table(TABLE).insert({
        "event_ticker": event, "strike": pick["strike"], "side": pick["side"],
        "ours": pick["prob_raw"], "ours_cal": pick["prob"],
        "market": pick["cost"], "cost": pick["cost"],
        "edge_pts": pick["edge_pts"], "edge_net_pts": pick["net_pts"],
        "yes_bid": pick["yes_bid"], "yes_ask": pick["yes_ask"],
        "sigma_h": view.get("sigma_h"),
        "minutes_to_close": round(float(view.get("minutes_to_close") or 0), 2),
        "freeze_kind": kind, "picker_version": PICKER_VERSION,
        "calib_map_version": cmap.version,
        "live_price": view.get("live_price"),
        "frozen_at": now.isoformat(),
    }).execute())
    return event


def run(supa, *, now: datetime | None = None, live=None,
        ladder_fn=live_ladder, event_ladder_fn=None,
        samples_fn=None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    summary = {"graded": 0, "frozen": None, "frozen_t10": None}

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

    # Calibration state for this run: samples load at most once, and each
    # freeze fits its map on events closed strictly before its own event.
    state: dict[str, Any] = {"samples": None, "maps": {}}

    def cmap_for(close: datetime):
        if close not in state["maps"]:
            if state["samples"] is None:
                try:
                    state["samples"] = (samples_fn or load_samples)(supa)
                except Exception:  # noqa: BLE001 -- an unreadable journal degrades to the identity map
                    log.warning("oil picker v2: calibration samples unreadable; identity map", exc_info=True)
                    state["samples"] = []
            state["maps"][close] = fit_map(pairs_before(state["samples"], close))
        return state["maps"][close]

    # Freeze the T-30 pick, once, inside the window. The gate is the v2
    # pick off the ladder's rows (calibration can promote a candidate the
    # raw rule had no pick on, so view["best"] is never the gate).
    view = ladder_fn(now)
    if view.get("state") == "live" and view.get("rows") \
            and in_freeze_window(float(view.get("minutes_to_close") or 0), "T-30"):
        summary["frozen"] = _freeze_from_view(
            supa, view, "T-30", cmap_for(_close_of(view)), now)

    # Freeze the T-10 pick for the imminent event (the standard ladder
    # has already rolled past it, so it is targeted directly). Its own
    # try: a T-10 failure never costs the T-30 freeze or the grading.
    try:
        from tradehub.data.kalshi_live import KalshiLive

        client = live or KalshiLive()
        closes: dict[str, datetime] = {}
        for lm in client.open_markets(SERIES):
            closes.setdefault(lm.market.event_ticker, lm.market.close_time)
        for event, close in sorted(closes.items(), key=lambda kv: kv[1]):
            minutes = (close - now).total_seconds() / 60.0
            if not in_freeze_window(minutes, "T-10"):
                continue
            view10 = (event_ladder_fn or ladder_fn)(now, event_ticker=event)
            if view10.get("state") == "live" and view10.get("rows"):
                summary["frozen_t10"] = _freeze_from_view(
                    supa, view10, "T-10", cmap_for(_close_of(view10)), now)
            break
    except Exception:  # noqa: BLE001 -- retried next run; the window is cadence-wide
        log.warning("oil picker v2: T-10 freeze failed", exc_info=True)
    return summary


def _backtest(supa) -> dict[str, Any] | None:
    try:
        rows = supa.rpc("oil_best_strike_backtest").execute().data or []
    except Exception:  # noqa: BLE001 -- unknown is shown as unknown; the record still reads
        log.exception("oil: best-strike backtest unreadable")
        return None
    return rows[0] if rows else None


def _segment(rows: list[dict]) -> dict[str, Any]:
    settled = [r for r in rows if r.get("settled")]
    hits = sum(1 for r in settled if r.get("hit"))
    evs = [float(r["ev"]) for r in settled if r.get("ev") is not None]
    return {"frozen": len(rows), "settled": len(settled), "hits": hits,
            "hit_rate": round(hits / len(settled), 4) if settled else None,
            "net_per_contract": round(sum(evs) / len(evs), 4) if evs else None}


def record(supa) -> dict[str, Any]:
    """The public read: how the frozen picks have done, and the rule replayed over the journal."""
    rows = (supa.table(TABLE).select("*").order("frozen_at", desc=True)
            .limit(500).execute().data or [])
    settled = [r for r in rows if r.get("settled")]
    hits = sum(1 for r in settled if r.get("hit"))
    evs = [float(r["ev"]) for r in settled if r.get("ev") is not None]
    recent = [{"event_ticker": r["event_ticker"], "strike": float(r["strike"]), "side": r.get("side") or "yes",
               "ours": float(r["ours"]), "market": float(r["market"]),
               "ours_cal": (float(r["ours_cal"]) if r.get("ours_cal") is not None else None),
               "freeze_kind": r.get("freeze_kind") or "T-30",
               "picker_version": r.get("picker_version") or "v1",
               "calib_map_version": r.get("calib_map_version"),
               "settled": bool(r.get("settled")), "hit": r.get("hit"),
               "frozen_at": r["frozen_at"]} for r in rows[:8]]
    # The segments never merge (spec 2026-11-09): the v1 record is the
    # control, and each v2 freeze kind grades as its own pick set.
    by_segment = {
        "legacy": _segment([r for r in rows if r.get("picker_version") != PICKER_VERSION]),
        "v2_T-30": _segment([r for r in rows if r.get("picker_version") == PICKER_VERSION
                             and (r.get("freeze_kind") or "T-30") == "T-30"]),
        "v2_T-10": _segment([r for r in rows if r.get("picker_version") == PICKER_VERSION
                             and r.get("freeze_kind") == "T-10"]),
    }
    return {"frozen": len(rows), "settled": len(settled), "hits": hits,
            "hit_rate": round(hits / len(settled), 3) if settled else None,
            "net_per_contract": round(sum(evs) / len(evs), 4) if evs else None,
            "backtest": _backtest(supa),
            "by_segment": by_segment,
            "recent": recent}
