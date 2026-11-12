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
                    window_open: datetime, now: datetime) -> tuple[dict[str, Any], float]:
    """The promoted blend gate's decision for one window (preregistration
    2026-11-11): the window's day weight applied to the frozen read. The
    blend gate owns its windows outright once flipped, so its gaps are
    named, never delegated: missing quotes read as the live evaluate's
    no_quote, and a day weight that cannot be read or persisted reads as
    a no_weight skip rather than a decision stamped with a weight no
    record holds."""
    from tradehub import fifteen_blend as blend
    pay = frozen.get("payload") or {}
    series = _BY_NAME[name]["series"]
    try:
        w = blend.weight_for_day(supa, name, version, series, window_open.date(), now)
    except Exception:  # noqa: BLE001 -- a named gap, never a borrowed gate
        return ({"action": "skip", "reason": "no_weight", "side": None, "cost": None,
                 "edge_net": None, "best_edge_net": None},
                round(float(frozen["probability"]), 5))
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


_SKIP_NO_READ = {"side": None, "cost": None, "edge_net": None, "best_edge_net": None}


def _oil_promoted(name: str, live_gate: bool, gate_version: str, gate_since) -> bool:
    return (live_gate and gate_version == "v2-oil" and gate_since is not None
            and name in ("oil_wti_15m", "oil_brent_15m"))


def gate_branch(window_open: datetime, *, promoted: bool, gate_since: datetime | None,
                blend_since: datetime | None) -> str:
    """Which gate owns a window: the blend from its flip -- checked first, it is
    the pooled, later gate and owns its windows outright (preregistration
    2026-11-11) -- then the promoted oil gate from its flip (2026-11-09), else v1."""
    if blend_since is not None and window_open >= blend_since:
        return "v2-blend"
    if promoted and window_open >= gate_since:
        return "v2-oil"
    return "v1"


def _minute1_ticks(supa, series: str, targets: list[dict]) -> dict[str, dict]:
    """close_time -> the minute-1 tick the promoted oil gate reads, per window."""
    by_close: dict[str, list[dict]] = {}
    for tk in fetch_ticks(supa, series, [_iso(t["cutoff_at"]) for t in targets]):
        by_close.setdefault(_iso(tk["close_time"]), []).append(tk)
    return {ct: b[1] for ct, rs in by_close.items() if 1 in (b := _tick_buckets(rs))}


def decide_window(supa, name: str, version: str, t: dict, *, branch: str,
                  frozen: dict | None, tick: dict | None, outcome: int | None,
                  now: datetime, candles_fn) -> dict[str, Any]:
    """One window's gated decision row under the gate that owns it: the buy, or
    the skip and why. The single decision both the record pass and the demo
    runner act on, so what is traded is what is recorded."""
    series = _BY_NAME[name]["series"]
    target = t["target"]
    close_time = _dt(t["cutoff_at"])
    window_open = close_time - timedelta(minutes=WINDOW_MINUTES)
    freeze_ref = (window_open + timedelta(minutes=5)).isoformat()
    if branch == "v2-blend":
        # The decision is the day's earned weight applied to the frozen read.
        # A window with no forecast is the blend's own no_prediction skip,
        # never a fall-through to a superseded gate.
        if frozen is not None:
            ev, model_prob = _blend_decision(supa, name, version, frozen, window_open, now)
            ref = frozen_at = frozen["frozen_at"]
        else:
            ev = {"action": "skip", "reason": "no_prediction", **_SKIP_NO_READ}
            ref, model_prob, frozen_at = freeze_ref, None, None
    elif branch == "v2-oil":
        # The variant is the live oil gate from the flip: the decision is read
        # off the minute-1 tick.
        ref = frozen["frozen_at"] if frozen is not None else freeze_ref
        ev, model_prob = _promoted_decision(tick, ref=ref)
        frozen_at = (window_open + timedelta(minutes=1)).isoformat()
    elif frozen is not None:
        pay = frozen.get("payload") or {}
        ev = rule.evaluate(float(frozen["probability"]), yes_ask=pay.get("yes_ask"),
                           yes_bid=pay.get("yes_bid"), frozen_at=frozen["frozen_at"])
        ref, model_prob = frozen["frozen_at"], round(float(frozen["probability"]), 5)
        frozen_at = frozen["frozen_at"]
    else:
        # No forecast was frozen. Re-check the tape at the freeze moment to name the
        # gap honestly: a tape that could have read is a forecaster miss, not stale data.
        tape = candles_fn(SERIES_COINS[series], window_open - TAPE_SPAN,
                          window_open + timedelta(minutes=6))
        read = read_window(close_time, tape, window_open + timedelta(minutes=5)) if tape else None
        ev = {"action": "skip", "reason": "no_prediction" if read else "stale_tape",
              **_SKIP_NO_READ}
        ref, model_prob, frozen_at = freeze_ref, None, None
    return {
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
        "evaluated_at": now.isoformat(), "gate_version": branch}


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
        targets = fetch_targets(supa, name, now - lookback, now)
        if not targets:
            continue
        names = [t["target"] for t in targets]
        first = _first_forecasts(supa, name, version, names)
        settled = store.fetch_settlements(supa, names)
        promoted = _oil_promoted(name, live_gate, gate_version, gate_since)
        ticks = _minute1_ticks(supa, series, targets) if promoted else {}
        for t in targets:
            window_open = _dt(t["cutoff_at"]) - timedelta(minutes=WINDOW_MINUTES)
            branch = gate_branch(window_open, promoted=promoted, gate_since=gate_since,
                                 blend_since=blend_since)
            rows.append(decide_window(
                supa, name, version, t, branch=branch, frozen=first.get(t["target"]),
                tick=ticks.get(_iso(t["cutoff_at"])), outcome=settled.get(t["target"]),
                now=now, candles_fn=candles_fn))
    if rows:
        supa.table(rule.DECISIONS_TABLE).upsert(rows, on_conflict="series,target").execute()
    by_reason: dict[str, int] = {}
    for r in rows:
        if r["reason"]:
            by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    return {"windows": len(rows), "buy": sum(r["action"] == "buy" for r in rows),
            "skip": sum(r["action"] == "skip" for r in rows), "by_reason": by_reason}


OPEN_BUFFER = timedelta(seconds=60)  # the demo runner's cutoff: orders die a minute before close


def _blend_weight_persisted(supa, series: str, day) -> bool:
    """Whether the blend's day weight is already frozen. Read-only: an open
    window never computes (and so never persists) a weight."""
    from tradehub import fifteen_blend as blend
    try:
        return bool(store.select_all(
            supa, blend.WEIGHTS_TABLE,
            lambda q: q.eq("series", series).eq("day", day.isoformat()), ("id",)))
    except Exception:  # noqa: BLE001 -- unknown is not ready
        return False


def open_decisions(supa, now: datetime, *, series_set=None,
                   live_gate: bool = True) -> list[dict]:
    """The decision the record pass will later write, for every calendar window
    still open -- close in (now + 60s, now + 15 min] -- whose read is already
    frozen. Read-only, nothing is written.

    The record pass only writes a window once it has closed (fetch_targets up
    to `now`), so a reader of `fifteen_rule_decisions` can never see an open
    window's decision; this is that decision, made at freeze time through the
    same `gate_branch` and `decide_window`. A window with no frozen read yet
    (no first forecast; for the promoted oil gate, no settled minute-1 tick;
    for the blend, no persisted day weight) is not a decision and is omitted
    -- never reported as the record pass's no_prediction/stale_tape skip."""
    out: list[dict] = []
    gate_version, gate_since = _live_gate(supa) if live_gate else ("v1", None)
    blend_since = _blend_gate(supa)
    lo, hi = now + OPEN_BUFFER, now + timedelta(minutes=WINDOW_MINUTES)
    for name, version, _label in (rule.SERIES if series_set is None else series_set):
        series = _BY_NAME[name]["series"]
        targets = [t for t in fetch_targets(supa, name, lo, hi) if _dt(t["cutoff_at"]) > lo]
        if not targets:
            continue
        first = _first_forecasts(supa, name, version, [t["target"] for t in targets])
        promoted = _oil_promoted(name, live_gate, gate_version, gate_since)
        ticks = _minute1_ticks(supa, series, targets) if promoted else {}
        for t in targets:
            window_open = _dt(t["cutoff_at"]) - timedelta(minutes=WINDOW_MINUTES)
            branch = gate_branch(window_open, promoted=promoted, gate_since=gate_since,
                                 blend_since=blend_since)
            frozen = first.get(t["target"])
            tick = ticks.get(_iso(t["cutoff_at"]))
            if branch == "v2-oil":
                # Ticks at elapsed [0.5, 1.5) compete for minute 1: before 1.5
                # a later, closer tick could still change the read.
                if (now < window_open + timedelta(minutes=1.5)
                        or tick is None or tick.get("prob_up") is None):
                    continue
            elif frozen is None:
                continue
            elif branch == "v2-blend" and not _blend_weight_persisted(
                    supa, series, window_open.date()):
                continue
            out.append(decide_window(supa, name, version, t, branch=branch, frozen=frozen,
                                     tick=tick, outcome=None, now=now,
                                     candles_fn=_candles_or_empty))
    return out


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
