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

Amendment (2026-11-08, Kevin; spec docs/superpowers/specs/2026-11-08-fifteen-rule-edge-gate-amendment.md):
the 10-point bar above was measured GROSS -- the taker fee was charged in the PnL but never in the
gate, so a "10-point edge" at a 50c cost was really 8.25 points. The gate now measures the edge NET
of the fee (`pick_net` / `evaluate` below): the same 0.10 bar, honestly netted. The reconstruction
above is NOT rewritten, and the gated record is reported beside it. Every targeted window also gets
a persisted decision (buy, or skip with its reason) and every settled window a per-minute shadow
track, written by `tradehub/fifteen_tracking.py`, so the best entry minute can be read off data.

Amendment (2026-11-09, Kevin; same spec doc): the go-live bar moved to the gated record. The 300
settled trades it counts are the gated record's -- re-derived over the full forward history, so the
count did not restart -- and the raw reconstruction stays reported as the control the bar is
checked against (`go_live_bar` below).
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
GATE_RULE = ("The live gate since the 2026-11-08 amendment: the same 10-point bar, measured net of "
             "Kalshi's taker fee -- a side is bought only when its chance beats its price by 10 "
             "points after the fee it would pay.")
DECISIONS_TABLE = "fifteen_rule_decisions"
OFFSETS_TABLE = "fifteen_window_offsets"
# The tracking tables are shared with the metals family (2026-11-09). This
# family's summaries exclude the metals series' rows, so the second family
# can never inflate this record; every other row is this family's, exactly
# as before the tables were shared.
METALS_KALSHI_SERIES = ("KXGOLD15M", "KXSILVER15M", "KXCOPPER15M")


def in_halt(frozen_at: str) -> bool:
    """CME halts oil and gas futures 5-6 PM ET while the model's tape keeps trading: no trade around it."""
    t = datetime.fromisoformat(frozen_at).astimezone(NY)
    return HALT_ET[0] <= t.hour + t.minute / 60 < HALT_ET[1]


def futures_open(frozen_at: str) -> bool:
    """CME energy futures trade Sunday 6:00 PM ET to Friday 5:00 PM ET, closed daily 5:00-6:00 PM ET.
    Closed: Saturday all day; Friday at/after 17:00; Sunday before 18:00; any day 17:00-17:59.
    """
    t = datetime.fromisoformat(frozen_at).astimezone(NY)
    wd = t.weekday()  # Monday=0, Sunday=6
    hour_min = t.hour + t.minute / 60
    if wd == 5:  # Saturday
        return False
    if wd == 4 and hour_min >= 17.0:  # Friday at/after 17:00
        return False
    if wd == 6 and hour_min < 18.0:  # Sunday before 18:00
        return False
    if 17.0 <= hour_min < 18.0:  # daily 17:00-17:59 halt
        return False
    return True


def pick(p: float, *, yes_ask: float | None, yes_bid: float | None) -> tuple[str, float] | None:
    """The side to buy and its cost, or None. The NO side costs 1 - the YES bid."""
    if yes_ask is None or yes_bid is None or not 0.02 < yes_bid <= yes_ask < 0.98:
        return None
    yes_edge, no_edge = p - yes_ask, yes_bid - p
    if max(yes_edge, no_edge) < MIN_EDGE - 1e-9:
        return None
    return ("yes", round(yes_ask, 4)) if yes_edge >= no_edge else ("no", round(1 - yes_bid, 4))


def fee(cost: float) -> float:
    """Kalshi's taker fee on one contract bought at `cost` -- the record's existing cost model,
    charged once at entry. The contract settles at $1/$0 with no exit fee, so this is the whole
    round-trip cost the edge has to clear."""
    return TAKER_FEE_RATE * cost * (1 - cost)


def net_edges(p: float, *, yes_ask: float | None, yes_bid: float | None) -> tuple[float, float] | None:
    """(YES edge, NO edge) net of the fee each side would pay, or None when the quote cannot be
    traded (missing, crossed, or outside the band `pick` has always required)."""
    if yes_ask is None or yes_bid is None or not 0.02 < yes_bid <= yes_ask < 0.98:
        return None
    return p - yes_ask - fee(yes_ask), yes_bid - p - fee(1 - yes_bid)


def pick_net(p: float, *, yes_ask: float | None, yes_bid: float | None) -> tuple[str, float, float] | None:
    """The gated pick (amendment 2026-11-08): (side, cost, net edge) when the better side's edge
    clears MIN_EDGE after its fee, else None. Same bar as `pick`, measured honestly."""
    edges = net_edges(p, yes_ask=yes_ask, yes_bid=yes_bid)
    if edges is None:
        return None
    yes_edge, no_edge = edges
    if max(yes_edge, no_edge) < MIN_EDGE - 1e-9:
        return None
    return ("yes", round(yes_ask, 4), yes_edge) if yes_edge >= no_edge else ("no", round(1 - yes_bid, 4), no_edge)


def evaluate(p: float, *, yes_ask: float | None, yes_bid: float | None, frozen_at: str) -> dict[str, Any]:
    """One window's gated decision at its freeze: a buy with its side, cost and net edge, or a
    skip with the reason named (halt / no_quote / no_edge) and the best net edge that was seen."""
    base: dict[str, Any] = {"side": None, "cost": None, "edge_net": None, "best_edge_net": None}
    if in_halt(frozen_at):
        return {"action": "skip", "reason": "halt", **base}
    edges = net_edges(p, yes_ask=yes_ask, yes_bid=yes_bid)
    if edges is None:
        return {"action": "skip", "reason": "no_quote", **base}
    best = max(edges)
    if best < MIN_EDGE - 1e-9:
        return {"action": "skip", "reason": "no_edge", **base, "best_edge_net": best}
    side, cost, edge = pick_net(p, yes_ask=yes_ask, yes_bid=yes_bid)
    return {"action": "buy", "reason": None, "side": side, "cost": cost,
            "edge_net": edge, "best_edge_net": best}


def pnl(side: str, cost: float, outcome: int) -> float:
    """Per contract, after the taker fee: a YES pays when the outcome is 1, a NO when it is 0."""
    won = outcome == 1 if side == "yes" else outcome == 0
    return round((1.0 if won else 0.0) - cost - TAKER_FEE_RATE * cost * (1 - cost), 4)


def _stats(trades: list[dict]) -> dict[str, Any]:
    n = len(trades)
    if not n:
        return {"n": 0, "net_per_contract": None, "total": 0.0, "win_rate": None, "low95": None, "ready": False, "windows": 0}
    xs = [t["pnl"] for t in trades]
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else None
    low = mean - 1.96 * sd / math.sqrt(n) if sd is not None else None
    windows = len({t["frozen_at"] for t in trades})
    return {"n": n, "net_per_contract": round(mean, 4), "total": round(sum(xs), 2),
            "win_rate": round(sum(x > 0 for x in xs) / n, 3),
            "low95": round(low, 4) if low is not None else None,
            "ready": n >= READY_TRADES and low is not None and low > 0,
            "windows": windows}


def summarize(trades: list[dict]) -> dict[str, Any]:
    return {"replay": _stats([t for t in trades if t["frozen_at"] < PREREG_AT]),
            "forward": _stats([t for t in trades if t["frozen_at"] >= PREREG_AT])}


def go_live_bar(gated_forward: dict[str, Any], raw_forward: dict[str, Any], *,
                pending: int = 0) -> dict[str, Any]:
    """The go-live bar (amendment 2026-11-09): READY_TRADES settled forward trades, still ahead at
    the low end of the 95% range, counted on the GATED record -- the trades the live gate would
    actually have taken. The raw record's figures ride along as the control."""
    return {"basis": "gated", "trades": gated_forward["n"], "ready_trades": READY_TRADES,
            "ready": gated_forward["ready"], "low95": gated_forward["low95"],
            "windows": gated_forward["windows"], "pending": pending,
            "control": {"basis": "raw", "trades": raw_forward["n"],
                        "ready": raw_forward["ready"], "low95": raw_forward["low95"]}}


def _series_trades(supa, first: dict[str, dict], label: str, picker) -> tuple[list[dict], int]:
    """Settled trades one picker takes on one series' first-frozen rows, and how many of its
    picks are still waiting to settle. The picker returns (side, cost[, edge]) or None."""
    picks = {}
    for target, r in first.items():
        if in_halt(r["frozen_at"]):
            continue
        pay = r.get("payload") or {}
        choice = picker(float(r["probability"]), yes_ask=pay.get("yes_ask"), yes_bid=pay.get("yes_bid"))
        if choice:
            picks[target] = (r, choice)
    settled = store.fetch_settlements(supa, list(picks)) if picks else {}
    trades, pending = [], 0
    for target, (r, choice) in picks.items():
        side, cost = choice[0], choice[1]
        if target not in settled:
            pending += 1
            continue
        trades.append({"series": label, "target": target, "frozen_at": r["frozen_at"], "side": side,
                       "cost": cost, "model": round(float(r["probability"]), 3),
                       "outcome": settled[target], "pnl": pnl(side, cost, settled[target])})
    return trades, pending


def _session_split(trades: list[dict]) -> dict[str, Any]:
    forward = [t for t in trades if t["frozen_at"] >= PREREG_AT]
    return {"open": _stats([t for t in forward if futures_open(t["frozen_at"])]),
            "closed": _stats([t for t in forward if not futures_open(t["frozen_at"])])}


def _read_rows(supa, table: str) -> list[dict]:
    """This family's rows of a tracking table, or [] while the table is not there yet (code reaches
    production before its migration does; an absent table reads as an empty record, never an error)."""
    try:
        rows = store.select_all(supa, table, lambda q: q, ("id",))
    except Exception:  # noqa: BLE001
        return []
    return [r for r in rows if r.get("series") not in METALS_KALSHI_SERIES]


def _decisions_summary(supa) -> dict[str, Any]:
    rows = _read_rows(supa, DECISIONS_TABLE)
    by_reason: dict[str, int] = {}
    buy = skip = 0
    for r in rows:
        if r.get("action") == "buy":
            buy += 1
        else:
            skip += 1
            if r.get("reason"):
                by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    return {"recorded": len(rows), "buy": buy, "skip": skip, "by_reason": by_reason}


def _offsets_summary(supa) -> dict[str, Any]:
    """The entry-time dataset in one view: per minute offset, how many windows were priced there,
    the mean net edge on offer, and what entering at that minute would have made."""
    groups: dict[int, list[dict]] = {}
    for r in _read_rows(supa, OFFSETS_TABLE):
        groups.setdefault(int(r["offset_min"]), []).append(r)

    def mean(xs: list[float], digits: int) -> float | None:
        return round(sum(xs) / len(xs), digits) if xs else None

    by_offset = []
    for off in sorted(groups):
        g = groups[off]
        priced = [r for r in g if r.get("edge_net") is not None]
        settled = [r for r in g if r.get("pnl") is not None]
        by_offset.append({
            "offset_min": off, "windows": len({r["target"] for r in g}), "priced": len(priced),
            "mean_edge_net": mean([float(r["edge_net"]) for r in priced], 4),
            "n": len(settled),
            "net_per_contract": mean([float(r["pnl"]) for r in settled], 4),
            "win_rate": round(sum(r["pnl"] > 0 for r in settled) / len(settled), 3) if settled else None,
            "mean_move_to_settle_bps": mean([float(r["move_to_settle_bps"]) for r in g
                                             if r.get("move_to_settle_bps") is not None], 1),
            "mean_move_to_60m_bps": mean([float(r["move_to_60m_bps"]) for r in g
                                          if r.get("move_to_60m_bps") is not None], 1),
        })
    return {"by_offset": by_offset}


def record(supa) -> dict[str, Any]:
    """The public read: every settled trade the rule would have taken, replay and forward apart."""
    trades, gated, pending, gated_pending = [], [], 0, 0
    for forecaster, version, label in SERIES:
        rows = store.fetch_forecasts(supa, forecaster, version)
        first: dict[str, dict] = {}
        for r in sorted(rows, key=lambda r: r["frozen_at"]):
            first.setdefault(r["target"], r)  # the freeze the rule acts on is the first one
        raw_t, raw_p = _series_trades(supa, first, label, pick)
        gated_t, gated_p = _series_trades(supa, first, label,
                                          lambda p, *, yes_ask, yes_bid: (c[:2] if (c := pick_net(
                                              p, yes_ask=yes_ask, yes_bid=yes_bid)) else None))
        trades += raw_t
        gated += gated_t
        pending += raw_p
        gated_pending += gated_p
    trades.sort(key=lambda t: t["frozen_at"], reverse=True)
    by_series = {label: _stats([t for t in trades if t["series"] == label and t["frozen_at"] >= PREREG_AT])
                 for _, _, label in SERIES}
    # by_session split for forward trades only (frozen_at >= PREREG_AT)
    raw = summarize(trades)
    gate = {"rule": GATE_RULE, "min_edge": MIN_EDGE, **summarize(gated),
            "by_session": _session_split(gated),
            # The gated split by market, same forward-only shape as by_series above:
            # the Strategies page lists one entry per market, each with its gated record.
            "by_series": {label: _stats([t for t in gated if t["series"] == label
                                         and t["frozen_at"] >= PREREG_AT])
                          for _, _, label in SERIES}}
    return {"rule": RULE, "prereg_at": PREREG_AT, "ready_trades": READY_TRADES, **raw,
            "by_series": by_series, "by_session": _session_split(trades), "pending": pending,
            "recent": trades[:12], "gate": gate,
            "bar": go_live_bar(gate["forward"], raw["forward"], pending=gated_pending),
            "decisions": _decisions_summary(supa), "offsets": _offsets_summary(supa)}
