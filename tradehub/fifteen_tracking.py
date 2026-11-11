"""Persisted tracking for the 15-minute trade rule (amendment 2026-11-08, spec
docs/superpowers/specs/2026-11-08-fifteen-rule-edge-gate-amendment.md).

The rule used to exist only as a read-time reconstruction: windows it skipped
left no trace, and the freeze minute was the only entry ever scored. This
module writes the two records Kevin asked for, from the fifteen-minute
runner, additively -- the journal and the tick tape are never touched:

- `fifteen_rule_decisions`: one row per targeted window per series -- the
  gated buy it took, or the skip with its reason named -- upserted on
  (series, target) so repeat passes correct a row instead of doubling it.
- `fifteen_window_offsets`: one row per settled window per minute offset
  0..15 -- the model's chance and, where the per-minute tape captured them,
  Kalshi's real quotes at that minute, the gated edge on offer, what entering
  there would have made, and the underlying's move from that minute to the
  settlement and to an hour after the window opened. The dataset the
  "best entry minute" question is answered from.

A record only: nothing here places an order or changes a forecast.

Amendment 2026-11-09: the passes are generalized over a series set -- the
metals family (tradehub/metals_fifteen_rule.py, its own preregistration)
writes its decisions and offsets through the same functions into the same
tables, which are keyed by series and target. The oil promotion state is
consulted only for the oil family's pass.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from tradehub import oil_fifteen_rule as rule
from tradehub.engines.fifteen_min import SERIES_COINS, WINDOW_MINUTES
from tradehub.journal import store
from tradehub.journal.forecasters.fifteen_min import SERIES as MODEL_SERIES
from tradehub.journal.forecasters.fifteen_min import _candles_or_empty, read_window
from tradehub.journal.kalshi_linked import ticker_of

log = logging.getLogger(__name__)

LOOKBACK = timedelta(days=3)
TAPE_SPAN = timedelta(minutes=150)
OFFSETS = range(0, 16)
TICKS_TABLE = "fifteen_min_ticks"
_BY_NAME = {spec["name"]: spec for spec in MODEL_SERIES}


def _dt(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def fetch_targets(supa, family: str, since: datetime, until: datetime) -> list[dict]:
    """Calendar windows for one fifteen-minute family whose close falls in [since, until]."""
    return store.select_all(
        supa, store.CALENDARS,
        lambda q: q.eq("family", family).eq("cadence", "15min")
                   .gte("cutoff_at", since.isoformat()).lte("cutoff_at", until.isoformat()),
        ("cutoff_at",))


def fetch_ticks(supa, series: str, close_times: list[str]) -> list[dict]:
    """The per-minute tape's rows for one Kalshi series at the given window closes."""
    out = []
    for chunk in store._chunks(sorted(set(close_times))):
        out += store.select_all(
            supa, TICKS_TABLE,
            lambda q, c=chunk: q.eq("series", series).in_("close_time", c), ("close_time",))
    return out


def fetch_tracked_offsets(supa, targets: list[str]) -> dict[str, set[int]]:
    """Which offsets each target already has rows for, so settled windows are written once."""
    out: dict[str, set[int]] = {}
    for chunk in store._chunks(sorted(set(targets))):
        for row in store.select_all(
                supa, rule.OFFSETS_TABLE,
                lambda q, c=chunk: q.in_("target", c), ("target",)):
            out.setdefault(row["target"], set()).add(int(row["offset_min"]))
    return out


def _first_forecasts(supa, name: str, version: str, targets: list[str]) -> dict[str, dict]:
    first: dict[str, dict] = {}
    for r in sorted(store.fetch_forecasts(supa, name, version, targets),
                    key=lambda r: r["frozen_at"]):
        first.setdefault(r["target"], r)  # the freeze the rule acts on is the first one
    return first


def _live_gate(supa) -> tuple[str, datetime | None]:
    """The oil gate's live version, from the shadow variant's promotions log
    (preregistration 2026-11-09, tradehub/fifteen_shadow.py). Any doubt --
    the log not migrated yet, a failed read -- reads as v1: the flip must be
    earned in the data, never assumed."""
    try:
        from tradehub import fifteen_shadow as shadow
        if shadow.current_state(supa) == shadow.LIVE_VERSION:
            at = shadow.promoted_at(supa)
            return shadow.LIVE_VERSION, _dt(at) if at else None
    except Exception:  # noqa: BLE001
        pass
    return "v1", None


def _blend_gate(supa) -> datetime | None:
    """The blend gate's flip moment, from its own promotions log
    (preregistration 2026-11-11, tradehub/fifteen_blend.py). Any doubt --
    the log not migrated yet, a failed read -- reads as not flipped: the
    flip must be earned in the data, never assumed."""
    try:
        from tradehub import fifteen_blend as blend
        if blend.current_state(supa) == blend.LIVE_VERSION:
            at = blend.promoted_at(supa)
            return _dt(at) if at else None
    except Exception:  # noqa: BLE001
        pass
    return None


def _blend_decision(supa, name: str, version: str, frozen: dict,
                    window_open: datetime, now: datetime) -> tuple[dict[str, Any], float] | None:
    """The promoted blend gate's decision for one window (preregistration
    2026-11-11): the window's day weight applied to the frozen read, or
    None when the frozen quotes are not there to blend toward -- the v1
    path then names the skip honestly."""
    from tradehub import fifteen_blend as blend
    pay = frozen.get("payload") or {}
    if pay.get("yes_ask") is None or pay.get("yes_bid") is None:
        return None
    series = _BY_NAME[name]["series"]
    w = blend.weight_for_day(supa, name, version, series, window_open.date(), now)
    ev, _market, _p = blend.evaluate_blend(
        float(frozen["probability"]), weight=w, yes_ask=pay.get("yes_ask"),
        yes_bid=pay.get("yes_bid"), frozen_at=frozen["frozen_at"])
    return ev, round(float(frozen["probability"]), 5)


def _promoted_decision(tick: dict | None, *, ref: str) -> tuple[dict[str, Any], float | None]:
    """The promoted oil gate's decision for one window (preregistration
    2026-11-09): the shadow variant's own evaluation of the minute-1 tick at
    its 0.05 bar, or the honest skip when the live read was not there."""
    from tradehub import fifteen_shadow as shadow
    if tick is None or tick.get("prob_up") is None:
        return ({"action": "skip", "reason": "stale_tape", "side": None, "cost": None,
                 "edge_net": None, "best_edge_net": None}, None)
    ev = shadow.evaluate_at(float(tick["prob_up"]), yes_ask=tick.get("yes_ask"),
                            yes_bid=tick.get("yes_bid"), ref=ref, bar=shadow.VARIANT_BAR)
    return ev, round(float(tick["prob_up"]), 5)


def record_decisions(supa, now: datetime, *, candles_fn=None, lookback: timedelta = LOOKBACK,
                     series_set=None, live_gate: bool = True) -> dict[str, Any]:
    """One gated decision per targeted window in the lookback: the buy, or the skip and why.

    `series_set` selects the family (default: the oil family's `rule.SERIES`);
    the metals family passes its own SERIES with `live_gate=False` -- the oil
    gate's promotion state is an oil fact and never consulted for metals,
    whose rows are stamped with their own frozen gate version, 'v1'."""
    candles_fn = candles_fn or _candles_or_empty
    rows: list[dict] = []
    gate_version, gate_since = _live_gate(supa) if live_gate else ("v1", None)
    blend_since = _blend_gate(supa)
    for name, version, _label in (rule.SERIES if series_set is None else series_set):
        series = _BY_NAME[name]["series"]
        coin = SERIES_COINS[series]
        targets = fetch_targets(supa, name, now - lookback, now)
        if not targets:
            continue
        names = [t["target"] for t in targets]
        first = _first_forecasts(supa, name, version, names)
        settled = store.fetch_settlements(supa, names)
        promoted = (live_gate and gate_version == "v2-oil" and gate_since is not None
                    and name in ("oil_wti_15m", "oil_brent_15m"))
        tick_buckets: dict[str, dict[int, dict]] = {}
        if promoted:
            by_close: dict[str, list[dict]] = {}
            for tk in fetch_ticks(supa, series, [_iso(t["cutoff_at"]) for t in targets]):
                by_close.setdefault(_iso(tk["close_time"]), []).append(tk)
            tick_buckets = {ct: _tick_buckets(rs) for ct, rs in by_close.items()}
        for t in targets:
            target = t["target"]
            close_time = _dt(t["cutoff_at"])
            window_open = close_time - timedelta(minutes=WINDOW_MINUTES)
            frozen = first.get(target)
            stamp = "v1"
            if blend_since is not None and window_open >= blend_since and frozen is not None:
                # The blend is the live gate from its flip, for every series
                # (preregistration 2026-11-11): the decision is the day's
                # earned weight applied to the frozen read, stamped with
                # its version. Checked before the oil gate's own flip --
                # the blend is the pooled, later gate.
                bev = _blend_decision(supa, name, version, frozen, window_open, now)
                if bev is not None:
                    ev, model_prob = bev
                    outcome = settled.get(target)
                    rows.append({
                        "series": series, "target": target,
                        "ticker": ticker_of(target) if target.startswith("kalshi:") else target,
                        "window_open": window_open.isoformat(), "close_time": close_time.isoformat(),
                        "frozen_at": frozen["frozen_at"],
                        "session": "open" if rule.futures_open(frozen["frozen_at"]) else "closed",
                        "action": ev["action"], "reason": ev["reason"], "side": ev["side"],
                        "cost": ev["cost"], "model_prob": model_prob, "edge_net": ev["edge_net"],
                        "best_edge_net": ev["best_edge_net"], "outcome": outcome,
                        "pnl": rule.pnl(ev["side"], ev["cost"], outcome)
                               if ev["action"] == "buy" and outcome is not None else None,
                        "evaluated_at": now.isoformat(), "gate_version": "v2-blend"})
                    continue
            if promoted and window_open >= gate_since:
                # The variant is the live oil gate from the flip: the decision
                # is read off the minute-1 tick, stamped with its version.
                ref = (frozen["frozen_at"] if frozen is not None
                       else (window_open + timedelta(minutes=5)).isoformat())
                ev, model_prob = _promoted_decision(
                    tick_buckets.get(_iso(t["cutoff_at"]), {}).get(1), ref=ref)
                frozen_at = (window_open + timedelta(minutes=1)).isoformat()
                stamp = "v2-oil"
                outcome = settled.get(target)
                rows.append({
                    "series": series, "target": target,
                    "ticker": ticker_of(target) if target.startswith("kalshi:") else target,
                    "window_open": window_open.isoformat(), "close_time": close_time.isoformat(),
                    "frozen_at": frozen_at,
                    "session": "open" if rule.futures_open(ref) else "closed",
                    "action": ev["action"], "reason": ev["reason"], "side": ev["side"],
                    "cost": ev["cost"], "model_prob": model_prob, "edge_net": ev["edge_net"],
                    "best_edge_net": ev["best_edge_net"], "outcome": outcome,
                    "pnl": rule.pnl(ev["side"], ev["cost"], outcome)
                           if ev["action"] == "buy" and outcome is not None else None,
                    "evaluated_at": now.isoformat(), "gate_version": stamp})
                continue
            if frozen is not None:
                pay = frozen.get("payload") or {}
                ev = rule.evaluate(float(frozen["probability"]), yes_ask=pay.get("yes_ask"),
                                   yes_bid=pay.get("yes_bid"), frozen_at=frozen["frozen_at"])
                ref, model_prob = frozen["frozen_at"], round(float(frozen["probability"]), 5)
                frozen_at = frozen["frozen_at"]
            else:
                # No forecast was frozen. Re-check the tape at the freeze moment to name the
                # gap honestly: a tape that could have read is a forecaster miss, not stale data.
                tape = candles_fn(coin, window_open - TAPE_SPAN, window_open + timedelta(minutes=6))
                read = read_window(close_time, tape, window_open + timedelta(minutes=5)) if tape else None
                ev = {"action": "skip", "reason": "no_prediction" if read else "stale_tape",
                      "side": None, "cost": None, "edge_net": None, "best_edge_net": None}
                ref = (window_open + timedelta(minutes=5)).isoformat()
                model_prob = frozen_at = None
            outcome = settled.get(target)
            rows.append({
                "series": series, "target": target,
                "ticker": ticker_of(target) if target.startswith("kalshi:") else target,
                "window_open": window_open.isoformat(), "close_time": close_time.isoformat(),
                "frozen_at": frozen_at,
                "session": "open" if rule.futures_open(ref) else "closed",
                "action": ev["action"], "reason": ev["reason"], "side": ev["side"],
                "cost": ev["cost"], "model_prob": model_prob, "edge_net": ev["edge_net"],
                "best_edge_net": ev["best_edge_net"], "outcome": outcome,
                "pnl": rule.pnl(ev["side"], ev["cost"], outcome)
                       if ev["action"] == "buy" and outcome is not None else None,
                "evaluated_at": now.isoformat(), "gate_version": stamp})
    if rows:
        supa.table(rule.DECISIONS_TABLE).upsert(rows, on_conflict="series,target").execute()
    by_reason: dict[str, int] = {}
    for r in rows:
        if r["reason"]:
            by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    return {"windows": len(rows), "buy": sum(r["action"] == "buy" for r in rows),
            "skip": sum(r["action"] == "skip" for r in rows), "by_reason": by_reason}


def _tick_buckets(ticks: list[dict]) -> dict[int, dict]:
    """One tick per whole-minute offset: the one whose elapsed time sits closest to it."""
    out: dict[int, dict] = {}
    for tk in ticks:
        elapsed = tk.get("elapsed_min")
        if elapsed is None:
            continue
        k = min(15, max(0, round(float(elapsed))))
        if k not in out or abs(float(elapsed) - k) < abs(float(out[k]["elapsed_min"]) - k):
            out[k] = tk
    return out


def record_offsets(supa, now: datetime, *, candles_fn=None, lookback: timedelta = LOOKBACK,
                   series_set=None) -> dict[str, Any]:
    """The per-offset shadow track for every settled window in the lookback not yet tracked.
    `series_set` selects the family, exactly as in record_decisions."""
    candles_fn = candles_fn or _candles_or_empty
    rows: list[dict] = []
    windows = 0
    for name, version, _label in (rule.SERIES if series_set is None else series_set):
        series = _BY_NAME[name]["series"]
        coin = SERIES_COINS[series]
        targets = [t for t in fetch_targets(supa, name, now - lookback, now)]
        if not targets:
            continue
        names = [t["target"] for t in targets]
        settled = store.fetch_settlements(supa, names)
        todo = [t for t in targets if t["target"] in settled]
        if not todo:
            continue
        tracked = fetch_tracked_offsets(supa, [t["target"] for t in todo])
        ticks_by_close: dict[str, list[dict]] = {}
        for tk in fetch_ticks(supa, series, [_iso(t["cutoff_at"]) for t in todo]):
            ticks_by_close.setdefault(_iso(tk["close_time"]), []).append(tk)
        for t in todo:
            target = t["target"]
            if len(tracked.get(target, ())) >= len(OFFSETS):
                continue  # already written in full; a window's track is written once
            close_time = _dt(t["cutoff_at"])
            window_open = close_time - timedelta(minutes=WINDOW_MINUTES)
            outcome = settled[target]
            tape = candles_fn(coin, window_open - TAPE_SPAN, window_open + timedelta(minutes=61))
            by_price = dict(tape)
            price_settle = by_price.get(close_time - timedelta(minutes=1))
            price_60m = by_price.get(window_open + timedelta(minutes=59))
            buckets = _tick_buckets(ticks_by_close.get(_iso(t["cutoff_at"]), []))
            for k in OFFSETS:
                tick = buckets.get(k)
                if tick is not None:
                    prob, source = tick.get("prob_up"), "tick"
                    bid, ask, price = tick.get("yes_bid"), tick.get("yes_ask"), tick.get("price")
                else:
                    read = read_window(close_time, tape, window_open + timedelta(minutes=k)) if tape else None
                    prob, source = (read["prob_up"] if read else None), "tape"
                    bid = ask = None
                    price = read["price"] if read else None
                side = cost = edge = pnl_v = None
                if prob is not None:
                    edges = rule.net_edges(float(prob), yes_ask=ask, yes_bid=bid)
                    if edges is not None:
                        edge = max(edges)
                        choice = rule.pick_net(float(prob), yes_ask=ask, yes_bid=bid)
                        if choice:
                            side, cost, edge = choice
                            pnl_v = rule.pnl(side, cost, outcome)
                rows.append({
                    "series": series, "target": target,
                    "ticker": ticker_of(target) if target.startswith("kalshi:") else target,
                    "close_time": close_time.isoformat(), "offset_min": k,
                    "prob_up": round(float(prob), 5) if prob is not None else None,
                    "prob_source": source, "yes_bid": bid, "yes_ask": ask, "price": price,
                    "side": side, "side_cost": cost, "edge_net": edge,
                    "outcome": outcome, "pnl": pnl_v,
                    "price_at_settle": price_settle, "price_at_60m": price_60m,
                    "move_to_settle_bps": round((price_settle / price - 1) * 1e4, 6)
                                          if price and price_settle else None,
                    "move_to_60m_bps": round((price_60m / price - 1) * 1e4, 6)
                                       if price and price_60m else None})
            windows += 1
    if rows:
        supa.table(rule.OFFSETS_TABLE).upsert(rows, on_conflict="series,target,offset_min").execute()
    return {"windows": windows, "rows": len(rows)}
