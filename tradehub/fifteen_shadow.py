"""The oil minute-1 x 0.05-bar shadow variant of the 15-minute trade rule
(preregistration docs/superpowers/specs/2026-11-09-fifteen-shadow-oil-minute1-prereg.md,
frozen 2026-11-09 on Kevin's authorization).

The variant, from two studies on the Nov 7-9 forward segment
(research/fifteen_bar/, research/fifteen_timing/): for WTI and Brent only,
decide at minute 1 of the window on the live tick read, at a 0.05 net-of-fee
bar. The discovery segment both suggested and scored it, so it is tested
here on fresh windows only -- window open at or after PREREG_AT -- as a
shadow record beside the live rule, and it promotes itself to the live oil
gate only when the frozen criterion is met on that fresh segment:

    PROMOTION CRITERION (all required): n >= 150 fresh shadow trades;
    shadow low95 > 0; paired-delta low95 > 0.

The paired delta is per-window (shadow policy PnL - live policy PnL, a skip
scoring 0) against the live rule's persisted decisions. Promotion writes an
audit row (fifteen_promotions), flips the live oil decisions to the variant
from that timestamp (stamped gate_version 'v2-oil' by fifteen_tracking), and
surfaces in the fifteen-rule endpoint's `shadow` block. One reversal row
(`python -m tradehub.fifteen_shadow revert`) restores gate v1 for oil.

Segmentation is structural: the live rule module is never modified, the v1
read paths never read these tables, and the 300-trade go-live bar keeps
counting gate-v1 freeze trades only. A record only: nothing here places an
order or changes a forecast.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from tradehub import fifteen_tracking as tracking
from tradehub import oil_fifteen_rule as rule
from tradehub.journal import store
from tradehub.journal.forecasters.fifteen_min import SERIES as MODEL_SERIES

PREREG_AT = "2026-11-09T19:00:00+00:00"
SHADOW_VERSION = "v2-oil-shadow"
LIVE_VERSION = "v2-oil"
SHADOW_TABLE = "fifteen_shadow_decisions"
EVALS_TABLE = "fifteen_shadow_evals"
PROMOTIONS_TABLE = "fifteen_promotions"
VARIANT_OFFSET = 1
VARIANT_BAR = 0.05
GRID_OFFSETS = (1, 2, 3, 4, 5)
GRID_BARS = (0.05, 0.10)
OIL_SERIES = tuple(s for s in rule.SERIES if s[0] in ("oil_wti_15m", "oil_brent_15m"))
PROMOTION_MIN_TRADES = 150
LOOKBACK = timedelta(days=3)
_BY_NAME = {spec["name"]: spec for spec in MODEL_SERIES}
_PREREG_DT = datetime.fromisoformat(PREREG_AT)


def _dt(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _read(supa, table: str, build=None) -> list[dict]:
    """A shadow table's rows, or [] while the table is not there yet (code
    reaches production before its migration does; an absent table reads as
    an empty record, never an error -- the live rule's convention)."""
    try:
        return store.select_all(supa, table, build or (lambda q: q), ("id",))
    except Exception:  # noqa: BLE001
        return []


def _pick_at(p: float, *, yes_ask: float | None, yes_bid: float | None,
             bar: float) -> tuple[str, float, float] | None:
    """`rule.pick_net` at an arbitrary bar: (side, cost, net edge) when the
    better side's fee-netted edge clears `bar`, else None."""
    edges = rule.net_edges(p, yes_ask=yes_ask, yes_bid=yes_bid)
    if edges is None:
        return None
    yes_edge, no_edge = edges
    if max(yes_edge, no_edge) < bar - 1e-9:
        return None
    return (("yes", round(yes_ask, 4), yes_edge) if yes_edge >= no_edge
            else ("no", round(1 - yes_bid, 4), no_edge))


def evaluate_at(p: float, *, yes_ask: float | None, yes_bid: float | None,
                ref: str, bar: float) -> dict[str, Any]:
    """One grid cell's decision: the live rule's `evaluate` at a stated bar --
    a buy with side, cost and net edge, or a skip with the reason named."""
    base: dict[str, Any] = {"side": None, "cost": None, "edge_net": None, "best_edge_net": None}
    if rule.in_halt(ref):
        return {"action": "skip", "reason": "halt", **base}
    edges = rule.net_edges(p, yes_ask=yes_ask, yes_bid=yes_bid)
    if edges is None:
        return {"action": "skip", "reason": "no_quote", **base}
    best = max(edges)
    if best < bar - 1e-9:
        return {"action": "skip", "reason": "no_edge", **base, "best_edge_net": best}
    side, cost, edge = _pick_at(p, yes_ask=yes_ask, yes_bid=yes_bid, bar=bar)
    return {"action": "buy", "reason": None, "side": side, "cost": cost,
            "edge_net": edge, "best_edge_net": best}


def record_shadow(supa, now: datetime, *, lookback: timedelta = LOOKBACK) -> dict[str, Any]:
    """The grid for every fresh oil window in the lookback: offsets 1..5 x
    bars {0.05, 0.10}, from the live tick read only, upserted on
    (series, target, offset_min, bar) so repeat passes correct, never double."""
    rows: list[dict] = []
    windows = 0
    for name, version, _label in OIL_SERIES:
        series = _BY_NAME[name]["series"]
        since = max(now - lookback, _PREREG_DT)
        targets = [t for t in tracking.fetch_targets(supa, name, since, now)
                   if _dt(t["cutoff_at"]) - timedelta(minutes=15) >= _PREREG_DT]
        if not targets:
            continue
        names = [t["target"] for t in targets]
        first = tracking._first_forecasts(supa, name, version, names)
        settled = store.fetch_settlements(supa, names)
        ticks_by_close: dict[str, list[dict]] = {}
        for tk in tracking.fetch_ticks(supa, series, [_iso(t["cutoff_at"]) for t in targets]):
            ticks_by_close.setdefault(_iso(tk["close_time"]), []).append(tk)
        for t in targets:
            target = t["target"]
            close_time = _dt(t["cutoff_at"])
            window_open = close_time - timedelta(minutes=15)
            frozen = first.get(target)
            ref = frozen["frozen_at"] if frozen is not None else (window_open + timedelta(minutes=5)).isoformat()
            session = "open" if rule.futures_open(ref) else "closed"
            outcome = settled.get(target)
            buckets = tracking._tick_buckets(ticks_by_close.get(_iso(t["cutoff_at"]), []))
            windows += 1
            for k in GRID_OFFSETS:
                tick = buckets.get(k)
                for bar in GRID_BARS:
                    if tick is None or tick.get("prob_up") is None:
                        ev = {"action": "skip", "reason": "no_tick", "side": None, "cost": None,
                              "edge_net": None, "best_edge_net": None}
                        model_prob = None
                    else:
                        model_prob = round(float(tick["prob_up"]), 5)
                        ev = evaluate_at(float(tick["prob_up"]), yes_ask=tick.get("yes_ask"),
                                         yes_bid=tick.get("yes_bid"), ref=ref, bar=bar)
                    rows.append({
                        "series": series, "target": target,
                        "ticker": tracking.ticker_of(target) if target.startswith("kalshi:") else target,
                        "window_open": window_open.isoformat(), "close_time": close_time.isoformat(),
                        "offset_min": k, "bar": bar, "gate_version": SHADOW_VERSION,
                        "session": session, "action": ev["action"], "reason": ev["reason"],
                        "side": ev["side"], "cost": ev["cost"], "model_prob": model_prob,
                        "edge_net": ev["edge_net"], "best_edge_net": ev["best_edge_net"],
                        "outcome": outcome,
                        "pnl": rule.pnl(ev["side"], ev["cost"], outcome)
                               if ev["action"] == "buy" and outcome is not None else None,
                        "evaluated_at": now.isoformat()})
    if rows:
        supa.table(SHADOW_TABLE).upsert(rows, on_conflict="series,target,offset_min,bar").execute()
    return {"windows": windows, "rows": len(rows),
            "buy": sum(r["action"] == "buy" for r in rows)}


def _mean_low95(xs: list[float]) -> tuple[int, float | None, float | None]:
    """(n, mean, low95) in the record's standing convention: low95 is the
    mean minus 1.96 standard errors, None when it cannot be measured."""
    n = len(xs)
    if not n:
        return 0, None, None
    mean = sum(xs) / n
    if n == 1:
        return n, mean, None
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    return n, mean, mean - 1.96 * sd / math.sqrt(n)


def criterion_met(n: int, low95: float | None, paired_low95: float | None) -> bool:
    """The frozen promotion criterion: every leg must hold, and an
    unmeasurable leg never passes."""
    return (n >= PROMOTION_MIN_TRADES and low95 is not None and low95 > 0
            and paired_low95 is not None and paired_low95 > 0)


def _fresh_variant_rows(supa) -> list[dict]:
    return [r for r in _read(supa, SHADOW_TABLE)
            if r.get("gate_version") == SHADOW_VERSION
            and int(r["offset_min"]) == VARIANT_OFFSET
            and abs(float(r["bar"]) - VARIANT_BAR) < 1e-6
            and _dt(r["window_open"]) >= _PREREG_DT]


def _evaluate(supa) -> dict[str, Any]:
    """The fresh-segment read, no writes: the variant's own settled record,
    the policy-paired delta against the live rule's decisions, and the
    closed-session slice of that delta."""
    variant = _fresh_variant_rows(supa)
    trades = [r for r in variant if r["action"] == "buy" and r.get("outcome") is not None
              and r.get("pnl") is not None]
    n, mean, low = _mean_low95([float(r["pnl"]) for r in trades])
    live = {(r["series"], r["target"]): r for r in _read(supa, rule.DECISIONS_TABLE)
            if (r.get("gate_version") or "v1") == "v1"}
    deltas, closed = [], []
    for r in variant:
        if r.get("outcome") is None:
            continue
        other = live.get((r["series"], r["target"]))
        if other is None or other.get("outcome") is None:
            continue
        mine = float(r["pnl"]) if r["action"] == "buy" and r.get("pnl") is not None else 0.0
        theirs = (float(other["pnl"]) if other["action"] == "buy" and other.get("pnl") is not None
                  else 0.0)
        deltas.append(mine - theirs)
        if r.get("session") == "closed":
            closed.append(mine - theirs)
    pn, pmean, plow = _mean_low95(deltas)
    cn, cmean, clow = _mean_low95(closed)
    return {"windows": len(variant), "trades": n,
            "net_per_contract": round(mean, 4) if mean is not None else None,
            "low95": round(low, 4) if low is not None else None,
            "win_rate": round(sum(float(r["pnl"]) > 0 for r in trades) / n, 3) if n else None,
            "paired_windows": pn,
            "paired_delta": round(pmean, 4) if pmean is not None else None,
            "paired_low95": round(plow, 4) if plow is not None else None,
            "closed_windows": cn,
            "closed_delta": round(cmean, 4) if cmean is not None else None,
            "closed_low95": round(clow, 4) if clow is not None else None,
            "criterion_met": criterion_met(n, low, plow)}


def current_state(supa) -> str:
    """The live oil gate's version: the newest promotion-log row's target,
    or 'v1' when the log is empty (or not there yet)."""
    rows = _read(supa, PROMOTIONS_TABLE)
    if not rows:
        return "v1"
    latest = max(rows, key=lambda r: (str(r.get("created_at") or ""), r.get("id") or 0))
    return str(latest["to_version"])


def promoted_at(supa) -> str | None:
    """When the live oil gate flipped to the variant, or None while v1 rules."""
    rows = _read(supa, PROMOTIONS_TABLE)
    if not rows:
        return None
    latest = max(rows, key=lambda r: (str(r.get("created_at") or ""), r.get("id") or 0))
    return str(latest["created_at"]) if latest["to_version"] == LIVE_VERSION else None


def evaluate_promotion(supa, now: datetime) -> dict[str, Any]:
    """One evaluation of the frozen criterion on the fresh segment. When it
    is met and the gate has not already flipped, this pass promotes: the
    audit row is the flip -- the decisions pass reads its state from the
    same log."""
    ev = _evaluate(supa)
    promoted = False
    if ev["criterion_met"] and current_state(supa) != LIVE_VERSION:
        evidence = {"trades": ev["trades"], "net_per_contract": ev["net_per_contract"],
                    "low95": ev["low95"], "paired_windows": ev["paired_windows"],
                    "paired_delta": ev["paired_delta"], "paired_low95": ev["paired_low95"],
                    "closed_windows": ev["closed_windows"], "closed_delta": ev["closed_delta"],
                    "closed_low95": ev["closed_low95"], "windows": ev["windows"]}
        supa.table(PROMOTIONS_TABLE).insert({
            "created_at": now.isoformat(), "kind": "promotion",
            "from_version": "v1", "to_version": LIVE_VERSION, "evidence": evidence}).execute()
        promoted = True
    return {**ev, "promoted": promoted}


def evaluate_daily(supa, now: datetime) -> dict[str, Any]:
    """The scheduled daily evaluation: the first pass of a UTC day runs it
    and persists the trail row; later passes the same day stand down."""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if _read(supa, EVALS_TABLE, lambda q: q.gte("evaluated_at", day_start)):
        return {"skipped": "already_evaluated_today"}
    ev = evaluate_promotion(supa, now)
    supa.table(EVALS_TABLE).insert({
        "evaluated_at": now.isoformat(), "windows": ev["windows"], "trades": ev["trades"],
        "net_per_contract": ev["net_per_contract"], "low95": ev["low95"],
        "paired_windows": ev["paired_windows"], "paired_delta": ev["paired_delta"],
        "paired_low95": ev["paired_low95"], "closed_windows": ev["closed_windows"],
        "closed_delta": ev["closed_delta"], "closed_low95": ev["closed_low95"],
        "criterion_met": ev["criterion_met"], "promoted": ev["promoted"]}).execute()
    return ev


def revert_promotion(supa, now: datetime, *, reason: str = "") -> dict[str, Any]:
    """The one-action reversal: a single log row restores gate v1 for oil
    from this moment. Rows already stamped 'v2-oil' stay as written."""
    if current_state(supa) != LIVE_VERSION:
        return {"reverted": False, "state": current_state(supa)}
    supa.table(PROMOTIONS_TABLE).insert({
        "created_at": now.isoformat(), "kind": "reversal",
        "from_version": LIVE_VERSION, "to_version": "v1",
        "evidence": {"reason": reason}}).execute()
    return {"reverted": True, "state": "v1"}


def summary(supa) -> dict[str, Any]:
    """The endpoint's read: the shadow's fresh record, the grid, and the
    promotion flag with its frozen criterion and (once flipped) evidence."""
    ev = _evaluate(supa)
    grid = []
    cells: dict[tuple[int, float], list[dict]] = {}
    for r in _read(supa, SHADOW_TABLE):
        if _dt(r["window_open"]) >= _PREREG_DT:
            cells.setdefault((int(r["offset_min"]), round(float(r["bar"]), 2)), []).append(r)
    for (k, bar) in sorted(cells):
        g = cells[(k, bar)]
        settled = [r for r in g if r["action"] == "buy" and r.get("pnl") is not None]
        gn, gmean, glow = _mean_low95([float(r["pnl"]) for r in settled])
        grid.append({"offset_min": k, "bar": bar, "windows": len(g), "trades": gn,
                     "net_per_contract": round(gmean, 4) if gmean is not None else None,
                     "low95": round(glow, 4) if glow is not None else None})
    state = current_state(supa)
    promo_row = None
    for r in _read(supa, PROMOTIONS_TABLE):
        if r.get("kind") == "promotion":
            if promo_row is None or str(r["created_at"]) > str(promo_row["created_at"]):
                promo_row = r
    return {
        "gate_version": SHADOW_VERSION, "prereg_at": PREREG_AT,
        "variant": {"series": ["WTI", "Brent"], "offset_min": VARIANT_OFFSET, "bar": VARIANT_BAR,
                    "rule": ("Oil only, decided at minute 1 on the live tick read: buy the side "
                             "whose chance beats its price by 5 points or more after Kalshi's "
                             "taker fee, hold to the close. A shadow record until the frozen "
                             "criterion promotes it.")},
        "fresh": {"windows": ev["windows"], "trades": ev["trades"],
                  "net_per_contract": ev["net_per_contract"], "low95": ev["low95"],
                  "win_rate": ev["win_rate"]},
        "paired": {"windows": ev["paired_windows"], "delta_per_window": ev["paired_delta"],
                   "low95": ev["paired_low95"]},
        "closed_session": {"windows": ev["closed_windows"], "delta_per_window": ev["closed_delta"],
                           "low95": ev["closed_low95"]},
        "grid": grid,
        "promotion": {"state": state, "met": ev["criterion_met"],
                      "criterion": {"min_trades": PROMOTION_MIN_TRADES, "shadow_low95_above": 0,
                                    "paired_low95_above": 0},
                      "promoted_at": promoted_at(supa),
                      "evidence": promo_row.get("evidence") if promo_row else None}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fifteen_shadow")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("evaluate", help="run one promotion evaluation now")
    rev = sub.add_parser("revert", help="restore gate v1 for oil (one action)")
    rev.add_argument("--reason", default="")
    args = parser.parse_args(argv)
    from tradehub.core.env import load_local_env
    from tradehub.core.supabase_client import get_client
    load_local_env()
    supa = get_client()
    now = datetime.now(UTC)
    out = (evaluate_promotion(supa, now) if args.cmd == "evaluate"
           else revert_promotion(supa, now, reason=args.reason))
    print(json.dumps(out, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
