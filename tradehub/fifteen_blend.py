"""The self-weighting blend shadow of the 15-minute trade rule
(preregistration docs/superpowers/specs/2026-11-11-fifteen-blend-shadow-prereg.md,
frozen 2026-11-11 on Kevin's commission of steps 1-2 of the check review,
docs/review-2026-11-11-muse-check-and-fifteen-loop.md Part 3).

Each day, before the first window, each of the six 15-minute series gets
one earned weight from all of its previous days: the slope of
(outcome - market) on (model - market) over settled windows since the
forward record began, contested windows only (market between 10% and 90%),
clamped to [0, 1]. The gate then acts on p = market + w x (model - market)
through the live rule's own evaluate -- same freeze, same quotes, same
fee-netted 0.10 bar, same halt exclusion. When a model stops knowing
anything, w falls toward 0, the blend sits on the price, and the gate
stops firing on its own. What stays fixed: the model formula, the fee
math, the 10-point bar, the halt exclusion, and the live rule itself --
its module and its decisions are never modified here.

The record is a shadow, stamped gate_version 'v2-blend-shadow' in its own
tables, scored on fresh windows only (window open at or after PREREG_AT),
and it promotes itself to the live gate for all six series only when the
frozen criterion is met on that fresh segment:

    PROMOTION CRITERION (all required): n >= 100 fresh shadow trades,
    pooled across all six series; shadow low95 > 0; paired-delta low95 > 0.

The paired delta is per-window (blend PnL - live PnL, a skip scoring 0)
against the live rule's persisted decisions. Promotion writes an audit
row in the blend's own promotions log -- its own log on purpose: the oil
shadow's state reads the newest row of fifteen_promotions, so a blend row
there would corrupt the oil gate. fifteen_tracking reads this log the
same way it reads the oil one, and stamps promoted decisions 'v2-blend'.
One reversal row (`python -m tradehub.fifteen_blend revert`) restores the
raw-model gate for all six series. A record only until it earns the flip:
nothing here places an order or changes a forecast.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from tradehub import fifteen_shadow as shadow
from tradehub import fifteen_tracking as tracking
from tradehub import metals_fifteen_rule as metals
from tradehub import oil_fifteen_rule as rule
from tradehub.journal import store
from tradehub.journal.forecasters.fifteen_min import SERIES as MODEL_SERIES
from tradehub.journal.kalshi_linked import ticker_of

PREREG_AT = "2026-11-12T00:00:00+00:00"
HISTORY_START = "2026-11-04T00:00:00+00:00"
SHADOW_VERSION = "v2-blend-shadow"
LIVE_VERSION = "v2-blend"
DECISIONS_TABLE = "fifteen_blend_decisions"
WEIGHTS_TABLE = "fifteen_blend_weights"
EVALS_TABLE = "fifteen_blend_evals"
PROMOTIONS_TABLE = "fifteen_blend_promotions"
PROMOTION_MIN_TRADES = 100
CONTESTED = (0.10, 0.90)
LOOKBACK = timedelta(days=3)
ALL_SERIES = rule.SERIES + metals.SERIES
_BY_NAME = {spec["name"]: spec for spec in MODEL_SERIES}
_PREREG_DT = datetime.fromisoformat(PREREG_AT)
_HISTORY_DT = datetime.fromisoformat(HISTORY_START)
_mean_low95 = shadow._mean_low95


def _dt(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _read(supa, table: str, build=None) -> list[dict]:
    """A blend table's rows, or [] while the table is not there yet (code
    reaches production before its migration does; an absent table reads as
    an empty record, never an error -- the shadow's convention)."""
    try:
        return store.select_all(supa, table, build or (lambda q: q), ("id",))
    except Exception:  # noqa: BLE001
        return []


def earned_weight(triples) -> tuple[float | None, int]:
    """(raw slope, contested count) for (model, market, outcome) triples:
    the slope of (outcome - market) on (model - market) over contested
    windows only. None when there is nothing to regress on -- no contested
    windows, or a model that never leaves the market."""
    num = den = 0.0
    n = 0
    for model, market, outcome in triples:
        if market is None or not CONTESTED[0] <= market <= CONTESTED[1]:
            continue
        x = model - market
        num += x * (outcome - market)
        den += x * x
        n += 1
    if n == 0 or den <= 0:
        return None, n
    return num / den, n


def _history_triples(supa, name: str, version: str, before: datetime) -> list[tuple]:
    """Every settled (model, market, outcome) triple for one series from
    the forward record's start up to `before`: the first forecast's frozen
    probability, the mid of its frozen quotes, the settlement."""
    targets = tracking.fetch_targets(supa, name, _HISTORY_DT, before)
    names = [t["target"] for t in targets]
    if not names:
        return []
    first = tracking._first_forecasts(supa, name, version, names)
    settled = store.fetch_settlements(supa, names)
    triples = []
    for target, frozen in first.items():
        if target not in settled:
            continue
        pay = frozen.get("payload") or {}
        bid, ask = pay.get("yes_bid"), pay.get("yes_ask")
        if bid is None or ask is None:
            continue
        triples.append((float(frozen["probability"]),
                        (float(bid) + float(ask)) / 2, settled[target]))
    return triples


def weight_for_day(supa, name: str, version: str, series: str, day,
                   now: datetime) -> float:
    """The series' earned weight for one UTC day, from the days before it
    only. Computed once, persisted with its evidence (the raw slope and
    the contested count), and read back on every later pass."""
    rows = _read(supa, WEIGHTS_TABLE,
                 lambda q: q.eq("series", series).eq("day", day.isoformat()))
    if rows:
        return float(rows[0]["weight"])
    day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    slope, n = earned_weight(_history_triples(supa, name, version, day_start))
    weight = 0.0 if slope is None else min(1.0, max(0.0, slope))
    try:
        supa.table(WEIGHTS_TABLE).upsert([{
            "series": series, "day": day.isoformat(), "weight": weight,
            "raw_slope": slope, "n_contested": n,
            "computed_at": now.isoformat()}], on_conflict="series,day").execute()
    except Exception:  # noqa: BLE001 -- a failed persist never blocks the record
        pass
    return weight


def evaluate_blend(p_model: float, *, weight: float, yes_ask: float | None,
                   yes_bid: float | None, frozen_at: str):
    """One window's blend decision: (evaluation, market, blend_p). The
    market is the frozen quotes' mid; without both quotes there is nothing
    to blend toward, and the live evaluate names the no_quote skip."""
    if yes_ask is None or yes_bid is None:
        return rule.evaluate(p_model, yes_ask=yes_ask, yes_bid=yes_bid,
                             frozen_at=frozen_at), None, None
    market = (float(yes_bid) + float(yes_ask)) / 2
    p = market + weight * (p_model - market)
    return rule.evaluate(p, yes_ask=yes_ask, yes_bid=yes_bid,
                         frozen_at=frozen_at), market, p


def record_blend(supa, now: datetime, *, lookback: timedelta = LOOKBACK) -> dict[str, Any]:
    """One blend decision per fresh targeted window in the lookback, for
    all six series, upserted on (series, target) so repeat passes correct,
    never double. Windows opened before the preregistration are never
    written."""
    rows: list[dict] = []
    for name, version, _label in ALL_SERIES:
        series = _BY_NAME[name]["series"]
        targets = [t for t in tracking.fetch_targets(supa, name, now - lookback, now)
                   if _dt(t["cutoff_at"]) - timedelta(minutes=15) >= _PREREG_DT]
        if not targets:
            continue
        names = [t["target"] for t in targets]
        first = tracking._first_forecasts(supa, name, version, names)
        settled = store.fetch_settlements(supa, names)
        weights: dict[Any, float] = {}
        for t in targets:
            target = t["target"]
            close_time = _dt(t["cutoff_at"])
            window_open = close_time - timedelta(minutes=15)
            day = window_open.date()
            if day not in weights:
                weights[day] = weight_for_day(supa, name, version, series, day, now)
            w = weights[day]
            frozen = first.get(target)
            outcome = settled.get(target)
            base = {"series": series, "target": target,
                    "ticker": ticker_of(target) if target.startswith("kalshi:") else target,
                    "window_open": window_open.isoformat(),
                    "close_time": close_time.isoformat(),
                    "gate_version": SHADOW_VERSION, "weight": w,
                    "evaluated_at": now.isoformat()}
            if frozen is None:
                ref = (window_open + timedelta(minutes=5)).isoformat()
                rows.append({**base, "frozen_at": None,
                             "session": "open" if rule.futures_open(ref) else "closed",
                             "action": "skip", "reason": "no_prediction",
                             "side": None, "cost": None, "model_prob": None,
                             "market_prob": None, "blend_prob": None,
                             "edge_net": None, "best_edge_net": None,
                             "outcome": outcome, "pnl": None})
                continue
            pay = frozen.get("payload") or {}
            model = float(frozen["probability"])
            ev, market, p = evaluate_blend(
                model, weight=w, yes_ask=pay.get("yes_ask"),
                yes_bid=pay.get("yes_bid"), frozen_at=frozen["frozen_at"])
            rows.append({**base, "frozen_at": frozen["frozen_at"],
                         "session": "open" if rule.futures_open(frozen["frozen_at"]) else "closed",
                         "action": ev["action"], "reason": ev["reason"],
                         "side": ev["side"], "cost": ev["cost"],
                         "model_prob": round(model, 5),
                         "market_prob": round(market, 5) if market is not None else None,
                         "blend_prob": round(p, 5) if p is not None else None,
                         "edge_net": ev["edge_net"], "best_edge_net": ev["best_edge_net"],
                         "outcome": outcome,
                         "pnl": rule.pnl(ev["side"], ev["cost"], outcome)
                                if ev["action"] == "buy" and outcome is not None else None})
    if rows:
        supa.table(DECISIONS_TABLE).upsert(rows, on_conflict="series,target").execute()
    return {"windows": len(rows), "buy": sum(r["action"] == "buy" for r in rows)}


def criterion_met(n: int, low95: float | None, paired_low95: float | None) -> bool:
    """The frozen promotion criterion: every leg must hold, and an
    unmeasurable leg never passes."""
    return (n >= PROMOTION_MIN_TRADES and low95 is not None and low95 > 0
            and paired_low95 is not None and paired_low95 > 0)


def _evaluate(supa) -> dict[str, Any]:
    """The fresh-segment read, no writes: the blend's own settled record
    and the policy-paired delta against the live rule's decisions (any
    stamp but the blend's own live stamp -- a promoted row is the blend
    itself, not its opponent)."""
    fresh = [r for r in _read(supa, DECISIONS_TABLE)
             if _dt(r["window_open"]) >= _PREREG_DT]
    trades = [r for r in fresh if r["action"] == "buy" and r.get("outcome") is not None
              and r.get("pnl") is not None]
    n, mean, low = _mean_low95([float(r["pnl"]) for r in trades])
    live = {(r["series"], r["target"]): r for r in _read(supa, rule.DECISIONS_TABLE)
            if (r.get("gate_version") or "v1") != LIVE_VERSION}
    deltas = []
    for r in fresh:
        if r.get("outcome") is None:
            continue
        other = live.get((r["series"], r["target"]))
        if other is None or other.get("outcome") is None:
            continue
        mine = float(r["pnl"]) if r["action"] == "buy" and r.get("pnl") is not None else 0.0
        theirs = (float(other["pnl"]) if other["action"] == "buy" and other.get("pnl") is not None
                  else 0.0)
        deltas.append(mine - theirs)
    pn, pmean, plow = _mean_low95(deltas)
    return {"windows": len(fresh), "trades": n,
            "net_per_contract": round(mean, 4) if mean is not None else None,
            "low95": round(low, 4) if low is not None else None,
            "win_rate": round(sum(float(r["pnl"]) > 0 for r in trades) / n, 3) if n else None,
            "paired_windows": pn,
            "paired_delta": round(pmean, 4) if pmean is not None else None,
            "paired_low95": round(plow, 4) if plow is not None else None,
            "criterion_met": criterion_met(n, low, plow)}


def current_state(supa) -> str:
    """The live gate's blend state: the newest promotion-log row's target,
    or 'v1' while the log is empty (or not there yet)."""
    rows = _read(supa, PROMOTIONS_TABLE)
    if not rows:
        return "v1"
    latest = max(rows, key=lambda r: (str(r.get("created_at") or ""), r.get("id") or 0))
    return str(latest["to_version"])


def promoted_at(supa) -> str | None:
    """When the live gate flipped to the blend, or None while v1 rules."""
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
                    "windows": ev["windows"]}
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
        "paired_low95": ev["paired_low95"], "criterion_met": ev["criterion_met"],
        "promoted": ev["promoted"]}).execute()
    return ev


def revert_promotion(supa, now: datetime, *, reason: str = "") -> dict[str, Any]:
    """The one-action reversal: a single log row restores the raw-model
    gate for all six series from this moment. Rows already stamped
    'v2-blend' stay as written."""
    if current_state(supa) != LIVE_VERSION:
        return {"reverted": False, "state": current_state(supa)}
    supa.table(PROMOTIONS_TABLE).insert({
        "created_at": now.isoformat(), "kind": "reversal",
        "from_version": LIVE_VERSION, "to_version": "v1",
        "evidence": {"reason": reason}}).execute()
    return {"reverted": True, "state": "v1"}


def summary(supa) -> dict[str, Any]:
    """The endpoint's read: the blend's fresh record, the latest daily
    weight per series, and the promotion flag with its frozen criterion
    and (once flipped) evidence."""
    ev = _evaluate(supa)
    weights: dict[str, dict] = {}
    for r in _read(supa, WEIGHTS_TABLE):
        cur = weights.get(r["series"])
        if cur is None or str(r["day"]) > str(cur["day"]):
            weights[r["series"]] = {"day": r["day"], "weight": r["weight"],
                                    "raw_slope": r.get("raw_slope"),
                                    "n_contested": r.get("n_contested")}
    state = current_state(supa)
    promo_row = None
    for r in _read(supa, PROMOTIONS_TABLE):
        if r.get("kind") == "promotion":
            if promo_row is None or str(r["created_at"]) > str(promo_row["created_at"]):
                promo_row = r
    return {
        "gate_version": SHADOW_VERSION, "prereg_at": PREREG_AT,
        "variant": {"series": ["Natural gas", "WTI", "Brent", "Gold", "Silver", "Copper"],
                    "rule": ("Each day, gate on the model blended toward the market by the "
                             "weight it has earned from all previous days (contested windows "
                             "only, clamped to 0-1), at the live rule's own 10-point "
                             "fee-netted bar. A shadow record until the frozen criterion "
                             "promotes it.")},
        "fresh": {"windows": ev["windows"], "trades": ev["trades"],
                  "net_per_contract": ev["net_per_contract"], "low95": ev["low95"],
                  "win_rate": ev["win_rate"]},
        "paired": {"windows": ev["paired_windows"], "delta_per_window": ev["paired_delta"],
                   "low95": ev["paired_low95"]},
        "weights": weights,
        "promotion": {"state": state, "met": ev["criterion_met"],
                      "criterion": {"min_trades": PROMOTION_MIN_TRADES,
                                    "shadow_low95_above": 0, "paired_low95_above": 0},
                      "promoted_at": promoted_at(supa),
                      "evidence": promo_row.get("evidence") if promo_row else None}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fifteen_blend")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("evaluate", help="run one promotion evaluation now")
    rev = sub.add_parser("revert", help="restore the raw-model gate (one action)")
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
