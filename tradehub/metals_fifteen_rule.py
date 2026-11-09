"""The 15-minute metals rule's paper record (Kevin, 2026-11-09) -- a separate
family beside the oil and gas rule in `oil_fifteen_rule.py`, kept under its
own preregistration (docs/superpowers/specs/2026-11-09-metals-fifteen-prereg.md).

The rule is the family's rule, in the family's code -- the gate math below is
imported, never copied, so the two families can never drift apart:

  At the model's freeze (about 5 minutes into each 15-minute window), if the
  model's chance beats the price of a side by 10 points or more NET of
  Kalshi's taker fee, buy that side at its ask, one contract, and hold it to
  the window's close. No early exit. No trade on windows frozen between
  4:45 and 6:30 PM New York time, around the daily Globex halt (metals halt
  at the same hour as energy).

It is graded only on rows the journal froze at or after PREREG_AT, at the
quotes frozen with them, after the fee. This record counts toward nothing in
the oil family -- not its go-live bar, not the v2-oil shadow's promotion --
and borrows nothing from it: no oil statistic enters a metals verdict, and
oil's minute-1 variant is an oil hypothesis that metals do not inherit.
Nothing here places an order. Fills at the quoted ask are assumed; the
book's depth is not recorded.

Copper is in the family on Kevin's explicit pick, with its scoping risks on
the record (research/metals_15m/RESULTS.md): the weakest Hyperliquid tape
basis of any fifteen series (88.1% direction match) and 3c median freeze
spreads. The forward record below is what judges it, on gold and silver's
terms.
"""

from __future__ import annotations

from typing import Any

from tradehub import oil_fifteen_rule as _family
from tradehub.journal import store

# The gate is the family's gate: same bar, same fee-netting, same halt and
# session shape -- the same function objects, so a metals decision and an
# oil decision are the same computation by construction.
MIN_EDGE = _family.MIN_EDGE
evaluate = _family.evaluate
pick = _family.pick
pick_net = _family.pick_net
pnl = _family.pnl
in_halt = _family.in_halt
futures_open = _family.futures_open

PREREG_AT = "2026-11-09T21:30:00+00:00"
READY_TRADES = 300
SERIES = (("gold_15m", "gold-15m-v1", "Gold"), ("silver_15m", "silver-15m-v1", "Silver"),
          ("copper_15m", "copper-15m-v1", "Copper"))
KALSHI_SERIES = ("KXGOLD15M", "KXSILVER15M", "KXCOPPER15M")
RULE = ("At the freeze, about 5 minutes into each 15-minute window: if the model's chance beats a "
        "side's price by 10 points or more, buy that side at its ask and hold it to the close. "
        "No trades from 4:45 to 6:30 PM ET, around the daily futures halt.")
GATE_RULE = ("The gate since this family's first day (preregistration 2026-11-09): the family's "
             "10-point bar, measured net of Kalshi's taker fee -- a side is bought only when its "
             "chance beats its price by 10 points after the fee it would pay.")
DECISIONS_TABLE = _family.DECISIONS_TABLE
OFFSETS_TABLE = _family.OFFSETS_TABLE


def _summarize(trades: list[dict]) -> dict[str, Any]:
    return {"replay": _family._stats([t for t in trades if t["frozen_at"] < PREREG_AT]),
            "forward": _family._stats([t for t in trades if t["frozen_at"] >= PREREG_AT])}


def _session_split(trades: list[dict]) -> dict[str, Any]:
    forward = [t for t in trades if t["frozen_at"] >= PREREG_AT]
    return {"open": _family._stats([t for t in forward if futures_open(t["frozen_at"])]),
            "closed": _family._stats([t for t in forward if not futures_open(t["frozen_at"])])}


def _read_rows(supa, table: str) -> list[dict]:
    """This family's rows of a shared tracking table (the tables are keyed by
    series; the oil family's rows in them are not this record's business)."""
    try:
        rows = store.select_all(supa, table, lambda q: q, ("id",))
    except Exception:  # noqa: BLE001
        return []
    return [r for r in rows if r.get("series") in KALSHI_SERIES]


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
    """The entry-time dataset for the metals windows only, in the family's shape."""
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
    """The public read, in the oil family's shape: every settled trade the rule
    would have taken on the metals series, replay and forward apart, the gated
    record leading and the raw reconstruction beside it as the control."""
    trades, gated, pending, gated_pending = [], [], 0, 0
    for forecaster, version, label in SERIES:
        rows = store.fetch_forecasts(supa, forecaster, version)
        first: dict[str, dict] = {}
        for r in sorted(rows, key=lambda r: r["frozen_at"]):
            first.setdefault(r["target"], r)  # the freeze the rule acts on is the first one
        raw_t, raw_p = _family._series_trades(supa, first, label, pick)
        gated_t, gated_p = _family._series_trades(
            supa, first, label,
            lambda p, *, yes_ask, yes_bid: (c[:2] if (c := pick_net(
                p, yes_ask=yes_ask, yes_bid=yes_bid)) else None))
        trades += raw_t
        gated += gated_t
        pending += raw_p
        gated_pending += gated_p
    trades.sort(key=lambda t: t["frozen_at"], reverse=True)
    by_series = {label: _family._stats([t for t in trades if t["series"] == label
                                        and t["frozen_at"] >= PREREG_AT])
                 for _, _, label in SERIES}
    raw = _summarize(trades)
    gate = {"rule": GATE_RULE, "min_edge": MIN_EDGE, **_summarize(gated),
            "by_session": _session_split(gated),
            "by_series": {label: _family._stats([t for t in gated if t["series"] == label
                                                 and t["frozen_at"] >= PREREG_AT])
                          for _, _, label in SERIES}}
    return {"rule": RULE, "prereg_at": PREREG_AT, "ready_trades": READY_TRADES, **raw,
            "by_series": by_series, "by_session": _session_split(trades), "pending": pending,
            "recent": trades[:12], "gate": gate,
            "bar": _family.go_live_bar(gate["forward"], raw["forward"], pending=gated_pending),
            "decisions": _decisions_summary(supa), "offsets": _offsets_summary(supa)}
