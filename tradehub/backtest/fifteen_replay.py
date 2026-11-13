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

The golden gate is the three-part check in the plan's Step A0 item 4b
(Claude's ruling, 2026-11-12, after the original single-tolerance check
failed at 20.5% on the Nov 6-12 run): (a) tape-sourced rows -- the
like-for-like test, same engine, same minute tape -- reproduce within
1e-5 for >= 95% of compared rows at EVERY entry minute (copper at
minutes 13-14 is reported separately, not waived); (b) tick-sourced
rows, computed from the underlying's price at the decision second,
agree within 0.01 for >= 99% (the within-1e-5 share is reported);
(c) where both the replay and the stored row trade, they pick the same
side >= 90% of the time. Rows that cannot be compared are counted,
never dropped quietly.

Accepted terms (Claude's ruling on PR #517, 2026-11-13; the replay is a
research dataset on these terms, measured on Nov 6-12, probabilities
covered Nov 9-12):
- (a) passes at offsets 1-13 (96.0%-100%). The one miss is copper at
  minute 14 (offset 14 pooled 94.89%, 130/137; copper 14 alone 94.7%;
  copper 13 95.4%). The cause is the FORWARD record, not the replay:
  on the failing windows the stored prob repeats identically across
  consecutive offsets, the fingerprint of `read_window`'s allowed
  staleness (`effective_now` lets the last completed candle lag the
  decision minute by up to 3 minutes), so the stored minute-14 row
  froze an earlier read while the replay reads the completed tape.
- (b) passes: 99.75% of tick rows within 0.01 (22.6% within 1e-5).
- (c) same-side agreement passes at 99.2% (2,351 / 2,371). This stays
  the hard gate. An earlier comparator counted a side as agreeing only
  when the cost ALSO matched exactly and reported 18.6%; there is no
  quote inversion.
- (c) quote and edge gaps are a stated limit, not a gate: the candle
  close is the book at the minute's end, the stored tick the snapshot
  nearest the decision second, so they differ by about 2c at the
  median (bid and ask both 2.0c against the stored quotes; the edge is
  within 3 points 58.7% of the time, median gap 2.1 points). No candle
  alignment does better than the one used here.
- Adverse selection: the replay takes trades the live book never
  offered (a 10-point edge still showing at the candle close that the
  decision-second tick did not have). Earliest trade per window: the
  replay shows -2.43c per trade on 1,109 trades, the forward record
  +6.67c on 1,326. Where both trade at minute 5 (167 windows) they
  agree (forward +1.07c, replay +1.53c); the gap is the trade SET.
  Hence the replay haircut rule (plan Step A): replay trades fill at
  the candle ask + 1c (REPLAY_HAIRCUT) and count only if the edge
  clears the bar after it; replay and forward are reported side by
  side; a candidate is valid only if both agree in direction, with
  forward deciding the size. Replay results never rank or pick a rule
  alone.

Either way the replay makes no claim to be the forward record: it is a
causal, internally consistent reconstruction for comparing entry
minutes within itself, and the forward rows stay the ground truth for
what the live gate would have traded.

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
# Golden gate (plan Step A0 item 4b, Claude's rulings 2026-11-12/13; see
# the module docstring): (a) tape rows within 1e-5 for >= 95% of compared
# rows at every entry minute; (b) tick rows within 0.01 for >= 99%;
# (c) same side >= 90% where both trade. The (c) edge (within 3 points
# >= 90%) and quote (median within 1c, >= 90% within 2c) bars are
# reported as a stated limit, not gated.
PROB_MATERIAL = 0.01
TAPE_RULING_TOLERANCE = 1e-5
TAPE_RULING_SHARE_MIN = 0.95
TICK_MATERIAL_SHARE_MIN = 0.99
SIDE_AGREE_SHARE_MIN = 0.90
EDGE_WITHIN = 0.03
EDGE_WITHIN_SHARE_MIN = 0.90
QUOTE_MEDIAN_MAX = 0.01
QUOTE_WITHIN = 0.02
QUOTE_WITHIN_SHARE_MIN = 0.90
# Replay haircut rule (plan Step A, Claude's ruling 2026-11-13): a replay
# trade fills at the candle ask + 1c, and counts only if its edge clears
# the bar after that haircut. 0 reproduces the raw candle replay (the
# golden check runs at 0).
REPLAY_HAIRCUT = 0.01


def haircut_quote(yes_bid: float | None, yes_ask: float | None,
                  haircut: float) -> tuple[float | None, float | None]:
    """The quote a haircut fill trades against: the yes ask `haircut`
    higher and the yes bid `haircut` lower, so both sides' cost (a yes at
    the ask, a no at 1 - yes_bid) rises by exactly `haircut`. A shifted
    quote that leaves the rule's 0.02-0.98 band is untradeable, so the
    haircut can only remove trades, never add them."""
    if yes_bid is None or yes_ask is None or not haircut:
        return yes_bid, yes_ask
    return round(yes_bid - haircut, 6), round(yes_ask + haircut, 6)


def replay_window(*, series: str, target: str, ticker: str | None,
                  close_time: datetime, outcome: int | None,
                  tape: list, candles: list,
                  haircut: float = 0.0) -> list[dict[str, Any]]:
    """One settled window's replay rows, offsets 1..14, shaped like
    fifteen_window_offsets plus source/candle_volume/spread/fillable.

    `tape` is the underlying's (minute_start, close) list covering the
    window (read_window wants the trailing span too); `candles` are
    kalshi_history Candle objects for this market. `haircut` (dollars,
    see REPLAY_HAIRCUT) prices the trade at the candle ask + haircut; the
    row's yes_bid/yes_ask stay the raw candle quote."""
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
        fill_bid, fill_ask = haircut_quote(bid, ask, haircut)
        if prob is not None:
            edges = rule.net_edges(prob, yes_ask=fill_ask, yes_bid=fill_bid)
            if edges is not None:
                edge = max(edges)
                choice = rule.pick_net(prob, yes_ask=fill_ask, yes_bid=fill_bid)
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
            "haircut": haircut,
        })
    return rows


def _replay_cost_of(row: dict, side: str) -> float | None:
    """The replay's cost of `side` from its candle quote: the yes ask for
    a yes, 1 - yes_bid for a no (the shared rule's own convention)."""
    bid, ask = row.get("yes_bid"), row.get("yes_ask")
    if bid is None or ask is None:
        return None
    return float(ask) if side == "yes" else 1.0 - float(bid)


def golden_compare(replay_rows: list[dict], stored_rows: list[dict]) -> dict[str, Any]:
    """Replay vs the forward fifteen_window_offsets, keyed on
    (series, target, offset_min), under the three-part gate of plan
    Step A0 item 4b (see the module docstring). The stored rows carry
    no bid/ask of their own, so part (c)'s quote comparison uses the
    one quote the stored row does carry -- its side_cost -- against
    the replay's cost of that same side. Tape-sourced stored rows
    never carry a quote at all (record_offsets writes bid/ask None on
    the tape path), so (c) is measurable only where the stored row
    traded, which is always a tick row. Matched rows that cannot be
    compared on a given measure are counted under "uncomparable",
    never dropped quietly. A gate part with no compared rows reports
    None shares and does not block."""
    stored = {(r["series"], r["target"], int(r["offset_min"])): r for r in stored_rows}
    out: dict[str, Any] = {
        "matched": 0, "prob_compared": 0, "prob_within_1e-6": 0,
        "prob_within_tolerance": 0, "prob_within_1e_5": 0,
        "prob_within_material": 0, "prob_max_diff": 0.0,
        "by_source": {}, "tape_by_offset": {}, "copper_13_14": {},
        "quote_compared": 0, "quote_median_abs_diff": None,
        "quote_within_share": None,
        "side_compared": 0, "side_agree": 0, "side_share": None,
        "edge_compared": 0, "edge_within": 0, "edge_share": None,
        "edge_max_diff": 0.0,
        "uncomparable": {"prob": 0, "quote": 0},
        "gate": {},
    }
    quote_diffs: list[float] = []
    for row in replay_rows:
        s = stored.get((row["series"], row["target"], int(row["offset_min"])))
        if s is None:
            continue
        out["matched"] += 1
        src = s.get("prob_source") or "?"
        bucket = out["by_source"].setdefault(
            src, {"n": 0, "prob_compared": 0, "prob_within_tolerance": 0,
                  "prob_within_1e_5": 0, "prob_within_material": 0,
                  "prob_max_diff": 0.0})
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
            if diff <= TAPE_RULING_TOLERANCE:
                out["prob_within_1e_5"] += 1
                bucket["prob_within_1e_5"] += 1
            if diff <= PROB_MATERIAL:
                out["prob_within_material"] += 1
                bucket["prob_within_material"] += 1
            if src == "tape":
                k = int(row["offset_min"])
                ob = out["tape_by_offset"].setdefault(
                    k, {"compared": 0, "within": 0, "share": None})
                ob["compared"] += 1
                if diff <= TAPE_RULING_TOLERANCE:
                    ob["within"] += 1
                if row["series"] == "KXCOPPER15M" and k in (13, 14):
                    cb = out["copper_13_14"].setdefault(
                        k, {"compared": 0, "within": 0, "share": None})
                    cb["compared"] += 1
                    if diff <= TAPE_RULING_TOLERANCE:
                        cb["within"] += 1
        else:
            out["uncomparable"]["prob"] += 1
        if s.get("side") is not None:
            rc = _replay_cost_of(row, s["side"])
            if rc is None or s.get("side_cost") is None:
                out["uncomparable"]["quote"] += 1
            else:
                quote_diffs.append(abs(rc - float(s["side_cost"])))
        if row["side"] is not None and s.get("side") is not None:
            out["side_compared"] += 1
            if row["side"] == s["side"]:
                out["side_agree"] += 1
                if row["edge_net"] is not None and s.get("edge_net") is not None:
                    out["edge_compared"] += 1
                    d = abs(float(row["edge_net"]) - float(s["edge_net"]))
                    out["edge_max_diff"] = max(out["edge_max_diff"], d)
                    if d <= EDGE_WITHIN:
                        out["edge_within"] += 1
    for ob in list(out["tape_by_offset"].values()) + list(out["copper_13_14"].values()):
        ob["share"] = ob["within"] / ob["compared"] if ob["compared"] else None
    if quote_diffs:
        quote_diffs.sort()
        n = len(quote_diffs)
        out["quote_compared"] = n
        out["quote_median_abs_diff"] = (quote_diffs[n // 2] if n % 2
                                        else (quote_diffs[n // 2 - 1] + quote_diffs[n // 2]) / 2)
        out["quote_within_share"] = (sum(1 for d in quote_diffs if d <= QUOTE_WITHIN) / n)
    if out["side_compared"]:
        out["side_share"] = out["side_agree"] / out["side_compared"]
    if out["edge_compared"]:
        out["edge_share"] = out["edge_within"] / out["edge_compared"]
    tick = out["by_source"].get("tick")
    offset_shares = {k: ob["share"] for k, ob in out["tape_by_offset"].items()
                     if ob["share"] is not None}
    a_pass = all(v >= TAPE_RULING_SHARE_MIN for v in offset_shares.values())
    tick_material = (tick["prob_within_material"] / tick["prob_compared"]
                     if tick and tick["prob_compared"] else None)
    tick_1e_5 = (tick["prob_within_1e_5"] / tick["prob_compared"]
                 if tick and tick["prob_compared"] else None)
    b_pass = tick_material is None or tick_material >= TICK_MATERIAL_SHARE_MIN
    c_side = out["side_share"] is None or out["side_share"] >= SIDE_AGREE_SHARE_MIN
    c_quote = (out["quote_compared"] == 0
               or (out["quote_median_abs_diff"] <= QUOTE_MEDIAN_MAX
                   and out["quote_within_share"] >= QUOTE_WITHIN_SHARE_MIN))
    c_edge = out["edge_share"] is None or out["edge_share"] >= EDGE_WITHIN_SHARE_MIN
    out["gate"] = {
        "a_tape": {"pass": a_pass, "by_offset_share": offset_shares,
                   "min_offset_share": min(offset_shares.values()) if offset_shares else None,
                   "copper_13_14_share": {k: ob["share"] for k, ob in out["copper_13_14"].items()}},
        "b_tick": {"pass": b_pass, "within_material_share": tick_material,
                   "within_1e_5_share": tick_1e_5},
        # Claude's 2026-11-13 ruling: same side is the hard gate; the
        # quote and edge bars are a stated limit, reported not gated.
        "c_quotes_sides": {"pass": c_side,
                           "quote_edge_within_limits": c_quote and c_edge,
                           "side_share": out["side_share"],
                           "quote_median_abs_diff": out["quote_median_abs_diff"],
                           "quote_within_share": out["quote_within_share"],
                           "edge_within_share": out["edge_share"]},
    }
    out["gate"]["pass"] = a_pass and b_pass and out["gate"]["c_quotes_sides"]["pass"]
    return out
