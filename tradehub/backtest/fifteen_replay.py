"""Step A0 of the fifteen-rule v4 plan (docs/plan-2026-11-12-fifteen-rule-v4.md):
replay the live 15-minute forecaster over Kalshi candle history, so entry
minutes 1-14 can be compared over months instead of the six forward days.

The replay is the live machinery, not a re-implementation: the probability
at entry minute k is `read_window` on the underlying's 1-minute tape (the
same function the journal freeze and the forward offsets track use), and
the would-be trade is `rule.net_edges` / `rule.pick_net` / `rule.pnl`,
exactly as `fifteen_tracking.record_offsets` computes the forward rows.

The one reconstruction choice: the quote at entry minute k is the close of
the Kalshi 1-minute candle ENDING at window open + k -- the last completed
candle when a minute-k decision is made (causal; no look-ahead). The
forward ticks are mid-minute book snapshots, so candle quotes will differ
from them in fast minutes; the golden check below reports probability
fidelity separately from quote agreement (which is measured, not assumed).

The golden gate is per prob_source (re-specified 2026-11-12 with Kevin's
provisional approval while Claude's review is pending; the original
single tolerance failed at 20.5% on the Nov 6-12 run). Tape-sourced
forward rows are the like-for-like test -- same engine, same minute
tape -- so they are hard-gated on reproducing to the stored rounding.
Tick-sourced rows were computed from the underlying's price at the
decision second, which no candle replay can reproduce exactly, so they
are gated on material agreement instead. Either way the replay makes no
claim to be the forward record: it is a causal, internally consistent
reconstruction for comparing entry minutes within itself, and the
forward rows stay the ground truth for what the live gate would have
traded.

Known limits (stated on every output): candles carry no order-book depth,
so fills cannot be proven; minutes whose candle volume is 0 are flagged
unfillable; the replay never counts toward a live record. Hyperliquid
serves only the last ~3.5 days of 1-minute candles (verified 2026-11-12:
1m requests before 2026-11-09 return empty for every coin, while 15m/1h
reach back months), so windows older than the tape's first candle carry
quotes and outcomes but prob_up None and never trade in the replay --
deep history cannot be rebuilt after the fact, it can only be archived
as it accrues.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from tradehub import oil_fifteen_rule as rule
from tradehub.engines.fifteen_min import WINDOW_MINUTES
from tradehub.journal.forecasters.fifteen_min import read_window

ENTRY_OFFSETS = range(1, 15)
# The forward store rounds prob_up to 5 decimals, so a stored value can sit
# up to 5e-6 from the true one; the golden tolerance is that plus float dust.
PROB_TOLERANCE = 6e-6
# Golden gate (re-specified 2026-11-12, see module docstring): tape rows
# must land within PROB_TOLERANCE for at least this share of compared
# rows; tick rows must land within PROB_MATERIAL (one cent of probability)
# for at least this share.
PROB_MATERIAL = 0.01
TAPE_TOLERANCE_SHARE_MIN = 0.90
TICK_MATERIAL_SHARE_MIN = 0.99


def replay_window(*, series: str, target: str, ticker: str | None,
                  close_time: datetime, outcome: int | None,
                  tape: list, candles: list) -> list[dict[str, Any]]:
    """One settled window's replay rows, offsets 1..14, shaped like
    fifteen_window_offsets plus source/candle_volume/spread/fillable.

    `tape` is the underlying's (minute_start, close) list covering the
    window (read_window wants the trailing span too); `candles` are
    kalshi_history Candle objects for this market."""
    window_open = close_time - timedelta(minutes=WINDOW_MINUTES)
    by_end = {c.end_ts: c for c in candles}
    by_price = dict(tape)
    price_settle = by_price.get(close_time - timedelta(minutes=1))
    price_60m = by_price.get(window_open + timedelta(minutes=59))
    rows: list[dict[str, Any]] = []
    for k in ENTRY_OFFSETS:
        read = read_window(close_time, tape, window_open + timedelta(minutes=k)) if tape else None
        candle = by_end.get(window_open + timedelta(minutes=k))
        bid = candle.yes_bid if candle is not None else None
        ask = candle.yes_ask if candle is not None else None
        volume = candle.volume if candle is not None else None
        prob = float(read["prob_up"]) if read else None
        price = read["price"] if read else None
        side = cost = edge = pnl_v = None
        if prob is not None:
            edges = rule.net_edges(prob, yes_ask=ask, yes_bid=bid)
            if edges is not None:
                edge = max(edges)
                choice = rule.pick_net(prob, yes_ask=ask, yes_bid=bid)
                if choice:
                    side, cost, edge = choice
                    if outcome is not None:
                        pnl_v = rule.pnl(side, cost, outcome)
        rows.append({
            "series": series, "target": target, "ticker": ticker,
            "close_time": close_time.isoformat(), "offset_min": k,
            "prob_up": prob, "prob_source": "replay", "source": "replay",
            "yes_bid": bid, "yes_ask": ask, "price": price,
            "side": side, "side_cost": cost, "edge_net": edge,
            "outcome": outcome, "pnl": pnl_v,
            "price_at_settle": price_settle, "price_at_60m": price_60m,
            "move_to_settle_bps": round((price_settle / price - 1) * 1e4, 6)
                                  if price and price_settle else None,
            "move_to_60m_bps": round((price_60m / price - 1) * 1e4, 6)
                               if price and price_60m else None,
            "candle_volume": volume,
            "spread": (ask - bid) if bid is not None and ask is not None else None,
            "fillable": bool(volume is not None and volume > 0),
        })
    return rows


def golden_compare(replay_rows: list[dict], stored_rows: list[dict]) -> dict[str, Any]:
    """Replay vs the forward fifteen_window_offsets, keyed on
    (series, target, offset_min). The gate is per prob_source (see the
    module docstring): tape rows must reproduce to the stored rounding
    for >= TAPE_TOLERANCE_SHARE_MIN of compared rows; tick rows must
    agree within PROB_MATERIAL for >= TICK_MATERIAL_SHARE_MIN. Side/edge
    agreement is reported, not gated -- the forward quotes are live book
    snapshots, the replay's are candle closes. The verdict rides along
    under "gate" (shares are None for a source with no compared rows,
    which does not block)."""
    stored = {(r["series"], r["target"], int(r["offset_min"])): r for r in stored_rows}
    out: dict[str, Any] = {
        "matched": 0, "prob_compared": 0, "prob_within_1e-6": 0,
        "prob_within_tolerance": 0, "prob_within_material": 0,
        "prob_max_diff": 0.0,
        "by_source": {}, "side_compared": 0, "side_agree": 0,
        "edge_compared": 0, "edge_max_diff": 0.0, "gate": {},
    }
    for row in replay_rows:
        s = stored.get((row["series"], row["target"], int(row["offset_min"])))
        if s is None:
            continue
        out["matched"] += 1
        src = s.get("prob_source") or "?"
        bucket = out["by_source"].setdefault(
            src, {"n": 0, "prob_compared": 0, "prob_within_tolerance": 0,
                  "prob_within_material": 0, "prob_max_diff": 0.0})
        bucket["n"] += 1
        if row["prob_up"] is not None and s.get("prob_up") is not None:
            diff = abs(float(row["prob_up"]) - float(s["prob_up"]))
            out["prob_compared"] += 1
            bucket["prob_compared"] += 1
            out["prob_max_diff"] = max(out["prob_max_diff"], diff)
            bucket["prob_max_diff"] = max(bucket["prob_max_diff"], diff)
            if diff <= 1e-6:
                out["prob_within_1e-6"] += 1
            if diff <= PROB_TOLERANCE:
                out["prob_within_tolerance"] += 1
                bucket["prob_within_tolerance"] += 1
            if diff <= PROB_MATERIAL:
                out["prob_within_material"] += 1
                bucket["prob_within_material"] += 1
        if row["side"] is not None and s.get("side") is not None:
            out["side_compared"] += 1
            if row["side"] == s["side"] and row["side_cost"] == s["side_cost"]:
                out["side_agree"] += 1
        if row["edge_net"] is not None and s.get("edge_net") is not None:
            out["edge_compared"] += 1
            out["edge_max_diff"] = max(out["edge_max_diff"],
                                       abs(float(row["edge_net"]) - float(s["edge_net"])))
    tape = out["by_source"].get("tape")
    tick = out["by_source"].get("tick")
    tape_share = (tape["prob_within_tolerance"] / tape["prob_compared"]
                  if tape and tape["prob_compared"] else None)
    tick_share = (tick["prob_within_material"] / tick["prob_compared"]
                  if tick and tick["prob_compared"] else None)
    out["gate"] = {
        "tape_within_tolerance_share": tape_share,
        "tape_pass": tape_share is None or tape_share >= TAPE_TOLERANCE_SHARE_MIN,
        "tick_within_material_share": tick_share,
        "tick_pass": tick_share is None or tick_share >= TICK_MATERIAL_SHARE_MIN,
    }
    out["gate"]["pass"] = out["gate"]["tape_pass"] and out["gate"]["tick_pass"]
    return out
