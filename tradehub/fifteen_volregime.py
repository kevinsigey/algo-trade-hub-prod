"""The volatility-regime challenger to the 15-minute blend (preregistration
docs/superpowers/specs/2026-11-13-fifteen-volregime-shadow-prereg.md, frozen
2026-11-12; review docs/review-2026-11-11-muse-round2-and-regime-challenger.md
Part 2).

The blend with one change: each series gets two daily weights instead of one.
A window is "high" when its frozen sigma_1m -- the trailing 1-minute realized
vol the model scales its move by, persisted in the freeze payload -- is above
that series' median sigma_1m over the 10 days before the window's UTC day,
"low" otherwise. Each regime's weight is the blend's earned-weight slope over
that regime's contested windows from earlier days only, clamped to [0, 1], and
0 under 30 contested windows. Same freeze, quotes, fee netting, 10-point bar
and halt exclusion as the blend (its evaluate is reused, not copied).

A record only, scored on fresh windows and paired against the blend's own
decisions on the same windows. The promotion bar is evaluated and stored, but
nothing here can promote: the challenger may take the gate only after the
blend has been promoted, and that path is a separate commission. Nothing here
places an order, changes a forecast, or writes to the live rule's or the
blend's tables.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tradehub import fifteen_blend as blend
from tradehub import fifteen_tracking as tracking
from tradehub import oil_fifteen_rule as rule
from tradehub.journal import store
from tradehub.journal.kalshi_linked import ticker_of

PREREG_AT = "2026-11-14T00:00:00+00:00"
SHADOW_VERSION = "v3-volregime-shadow"
DECISIONS_TABLE = "fifteen_volregime_decisions"
WEIGHTS_TABLE = "fifteen_volregime_weights"
EVALS_TABLE = "fifteen_volregime_evals"
MIN_CONTESTED = 30
MEDIAN_DAYS = 10
REGIMES = ("low", "high")
_PREREG_DT = datetime.fromisoformat(PREREG_AT)
_ET = ZoneInfo("America/New_York")
_dt, _read = blend._dt, blend._read


def _sigma(frozen: dict) -> float | None:
    value = (frozen.get("payload") or {}).get("sigma_1m")
    return None if value is None else float(value)


def regime_of(sigma: float | None, median: float | None) -> str | None:
    """'high' strictly above the median, 'low' at or below it; no regime
    when either is missing."""
    if sigma is None or median is None:
        return None
    return "high" if sigma > median else "low"


def trailing_median(supa, name: str, version: str, day_start: datetime) -> float | None:
    """The series' median frozen sigma_1m over windows opening in the
    MEDIAN_DAYS before `day_start` -- earlier days only, never the day itself."""
    since = day_start - timedelta(days=MEDIAN_DAYS)
    targets = [t["target"] for t in tracking.fetch_targets(
                   supa, name, since + timedelta(minutes=15), day_start)
               if since <= _dt(t["cutoff_at"]) - timedelta(minutes=15) < day_start]
    if not targets:
        return None
    sigmas = [s for f in tracking._first_forecasts(supa, name, version, targets).values()
              if (s := _sigma(f)) is not None]
    return statistics.median(sigmas) if sigmas else None


def regime_weight(triples) -> tuple[float, float | None, int]:
    """(weight, raw slope, contested count): the blend's slope, clamped to
    [0, 1], and 0 under MIN_CONTESTED contested windows."""
    slope, n = blend.earned_weight(triples)
    if slope is None or n < MIN_CONTESTED:
        return 0.0, slope, n
    return min(1.0, max(0.0, slope)), slope, n


def weights_for_day(supa, name: str, version: str, series: str, day,
                    now: datetime) -> tuple[float | None, dict[str, float]]:
    """(median, {regime: weight}) for one series and UTC day, computed once
    from earlier days only and persisted with the evidence. Read strictly and
    persisted unswallowed, like the blend's: a failed read must never look
    like an absent day (a recompute could rewrite it), and an unpersisted
    weight never stamps a decision. Failures raise; the runner is fail-soft."""
    rows = store.select_all(
        supa, WEIGHTS_TABLE,
        lambda q: q.eq("series", series).eq("day", day.isoformat()), ("id",))
    if {r["regime"] for r in rows} >= set(REGIMES):
        median = rows[0].get("median_sigma")
        return (None if median is None else float(median)), \
            {r["regime"]: float(r["weight"]) for r in rows}
    day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    median = trailing_median(supa, name, version, day_start)
    # One history read per series per day, split by regime in memory.
    tagged = [] if median is None else blend._history_triples(
        supa, name, version, day_start, tag=lambda f: regime_of(_sigma(f), median))
    out: dict[str, float] = {}
    persist = []
    for regime in REGIMES:
        if median is None:
            weight, slope, n = 0.0, None, 0
        else:
            weight, slope, n = regime_weight([t[:3] for t in tagged if t[3] == regime])
        out[regime] = weight
        persist.append({"series": series, "day": day.isoformat(), "regime": regime,
                        "median_sigma": median, "weight": weight, "raw_slope": slope,
                        "n_contested": n, "computed_at": now.isoformat()})
    supa.table(WEIGHTS_TABLE).upsert(persist, on_conflict="series,day,regime").execute()
    return median, out


def record_volregime(supa, now: datetime, *,
                     lookback: timedelta = blend.LOOKBACK) -> dict[str, Any]:
    """One challenger decision per fresh targeted window in the lookback,
    for all six series, upserted on (series, target). Windows opened before
    the preregistration are never written."""
    rows: list[dict] = []
    for name, version, _label in blend.ALL_SERIES:
        series = blend._BY_NAME[name]["series"]
        targets = [t for t in tracking.fetch_targets(supa, name, now - lookback, now)
                   if _dt(t["cutoff_at"]) - timedelta(minutes=15) >= _PREREG_DT]
        if not targets:
            continue
        names = [t["target"] for t in targets]
        first = tracking._first_forecasts(supa, name, version, names)
        settled = store.fetch_settlements(supa, names)
        days: dict[Any, tuple] = {}
        for t in targets:
            target = t["target"]
            close_time = _dt(t["cutoff_at"])
            window_open = close_time - timedelta(minutes=15)
            day = window_open.date()
            if day not in days:
                days[day] = weights_for_day(supa, name, version, series, day, now)
            median, weights = days[day]
            frozen = first.get(target)
            outcome = settled.get(target)
            base = {"series": series, "target": target,
                    "ticker": ticker_of(target) if target.startswith("kalshi:") else target,
                    "window_open": window_open.isoformat(),
                    "close_time": close_time.isoformat(),
                    "gate_version": SHADOW_VERSION, "median_sigma": median,
                    "evaluated_at": now.isoformat()}
            if frozen is None:
                ref = (window_open + timedelta(minutes=5)).isoformat()
                rows.append({**base, "frozen_at": None, "sigma_1m": None, "regime": None,
                             "weight": 0.0,
                             "session": "open" if rule.futures_open(ref) else "closed",
                             "action": "skip", "reason": "no_prediction",
                             "side": None, "cost": None, "model_prob": None,
                             "market_prob": None, "blend_prob": None,
                             "edge_net": None, "best_edge_net": None,
                             "outcome": outcome, "pnl": None})
                continue
            sigma = _sigma(frozen)
            regime = regime_of(sigma, median)
            w = weights.get(regime, 0.0) if regime else 0.0
            pay = frozen.get("payload") or {}
            model = float(frozen["probability"])
            ev, market, p = blend.evaluate_blend(
                model, weight=w, yes_ask=pay.get("yes_ask"),
                yes_bid=pay.get("yes_bid"), frozen_at=frozen["frozen_at"])
            rows.append({**base, "frozen_at": frozen["frozen_at"], "sigma_1m": sigma,
                         "regime": regime, "weight": w,
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


def _et_day(value: Any) -> str:
    return _dt(value).astimezone(_ET).date().isoformat()


def clustered_low95(items: list[tuple[Any, float]]) -> float | None:
    """Informational, not part of the frozen bar: the low end of the mean
    per item with windows clustered by (series, ET day) -- the cluster-robust
    standard error of a mean, mean - 1.96 * sqrt(k/(k-1) * sum_c (T_c - mean
    * n_c)^2) / n over k clusters with totals T_c of n_c items. Same-day
    windows move together, so this is the honest width; None under 2 days."""
    n = len(items)
    totals: dict[Any, list[float]] = defaultdict(lambda: [0.0, 0])
    for key, x in items:
        totals[key][0] += x
        totals[key][1] += 1
    k = len(totals)
    if k < 2:
        return None
    mean = sum(x for _k, x in items) / n
    var = k / (k - 1) * sum((t - mean * c) ** 2 for t, c in totals.values())
    return mean - 1.96 * var ** 0.5 / n


def _pnl_or_zero(r: dict) -> float:
    return float(r["pnl"]) if r["action"] == "buy" and r.get("pnl") is not None else 0.0


def _evaluate(supa) -> dict[str, Any]:
    """The fresh-segment read, no writes: the challenger's settled record
    and the per-window paired delta against the blend's decisions."""
    fresh = [r for r in _read(supa, DECISIONS_TABLE, lambda q: q.gte("window_open", PREREG_AT))
             if _dt(r["window_open"]) >= _PREREG_DT]
    trades = [r for r in fresh if r["action"] == "buy" and r.get("outcome") is not None
              and r.get("pnl") is not None]
    n, mean, low = blend._mean_low95([float(r["pnl"]) for r in trades])
    other = {(r["series"], r["target"]): r
             for r in _read(supa, blend.DECISIONS_TABLE, lambda q: q.gte("window_open", PREREG_AT))}
    deltas = []
    for r in fresh:
        b = other.get((r["series"], r["target"]))
        if r.get("outcome") is None or b is None or b.get("outcome") is None:
            continue
        deltas.append(((r["series"], _et_day(r["window_open"])), _pnl_or_zero(r) - _pnl_or_zero(b)))
    pn, pmean, plow = blend._mean_low95([d for _k, d in deltas])
    clow = clustered_low95([((r["series"], _et_day(r["window_open"])), float(r["pnl"]))
                            for r in trades])
    pclow = clustered_low95(deltas)
    met = blend.criterion_met(n, low, plow)
    blend_promoted = blend.current_state(supa) == blend.LIVE_VERSION
    return {"windows": len(fresh), "trades": n,
            "net_per_contract": round(mean, 4) if mean is not None else None,
            "low95": round(low, 4) if low is not None else None,
            "win_rate": round(sum(float(r["pnl"]) > 0 for r in trades) / n, 3) if n else None,
            "paired_windows": pn,
            "paired_delta": round(pmean, 4) if pmean is not None else None,
            "paired_low95": round(plow, 4) if plow is not None else None,
            "low95_clustered": round(clow, 4) if clow is not None else None,
            "paired_low95_clustered": round(pclow, 4) if pclow is not None else None,
            "criterion_met": met, "blend_promoted": blend_promoted,
            "eligible": met and blend_promoted}


def evaluate_daily(supa, now: datetime) -> dict[str, Any]:
    """Once per UTC day: the trail row. Records the bar; never promotes."""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if _read(supa, EVALS_TABLE, lambda q: q.gte("evaluated_at", day_start)):
        return {"skipped": "already_evaluated_today"}
    ev = _evaluate(supa)
    supa.table(EVALS_TABLE).insert({
        "evaluated_at": now.isoformat(),
        **{k: ev[k] for k in ("windows", "trades", "net_per_contract", "low95",
                              "paired_windows", "paired_delta", "paired_low95",
                              "low95_clustered", "paired_low95_clustered", "criterion_met",
                              "blend_promoted", "eligible")}}).execute()
    return ev


def summary(supa) -> dict[str, Any]:
    """The endpoint's read: fresh record, paired delta, latest weights per
    series and regime, and the bar (record only)."""
    ev = _evaluate(supa)
    weights: dict[str, dict] = {}
    for r in _read(supa, WEIGHTS_TABLE):
        cur = weights.get(r["series"])
        if cur is None or str(r["day"]) > cur["day"]:
            cur = weights[r["series"]] = {"day": str(r["day"]), "median_sigma": r.get("median_sigma")}
        if str(r["day"]) == cur["day"]:
            cur[r["regime"]] = {"weight": r["weight"], "n_contested": r.get("n_contested")}
    return {"gate_version": SHADOW_VERSION, "prereg_at": PREREG_AT,
            "fresh": {**{k: ev[k] for k in ("windows", "trades", "net_per_contract", "low95",
                                            "win_rate")},
                      "clustered_low95": ev["low95_clustered"]},
            "paired": {"windows": ev["paired_windows"], "delta_per_window": ev["paired_delta"],
                       "low95": ev["paired_low95"], "clustered_low95": ev["paired_low95_clustered"]},
            "weights": weights,
            "promotion": {"met": ev["criterion_met"], "blend_promoted": ev["blend_promoted"],
                          "eligible": ev["eligible"], "path_built": False,
                          "criterion": {"min_trades": blend.PROMOTION_MIN_TRADES,
                                        "shadow_low95_above": 0, "paired_low95_above": 0}}}


MONITOR_SOURCES = (("live", rule.DECISIONS_TABLE), ("blend", blend.DECISIONS_TABLE),
                   ("volregime", DECISIONS_TABLE))


def decline_monitor(supa, now: datetime, *, days: int = 14) -> list[dict]:
    """Per ET day and series: settled trades and P&L per trade (after fees)
    for the live rule, the blend and the challenger, side by side. Read only;
    an absent table reads as no trades."""
    labels = {blend._BY_NAME[name]["series"]: label for name, _v, label in blend.ALL_SERIES}
    # Whole ET days only: start at New York midnight `days` days back.
    start = datetime.combine(now.astimezone(_ET).date() - timedelta(days=days),
                             datetime.min.time(), tzinfo=_ET)
    since = start.astimezone(UTC).isoformat()
    cells: dict[tuple, dict] = defaultdict(lambda: {k: [] for k, _t in MONITOR_SOURCES})
    for key, table in MONITOR_SOURCES:
        for r in _read(supa, table, lambda q: q.gte("window_open", since)):
            if r.get("series") not in labels or not r.get("window_open"):
                continue
            cell = cells[(_et_day(r["window_open"]), labels[r["series"]])]
            if r.get("action") == "buy" and r.get("pnl") is not None:
                cell[key].append(float(r["pnl"]))
    out = []
    for (day, series), cell in sorted(cells.items(), reverse=True):
        row: dict[str, Any] = {"day": day, "series": series}
        for key, pnls in cell.items():
            row[key] = {"trades": len(pnls),
                        "pnl_per_trade": round(sum(pnls) / len(pnls), 4) if pnls else None}
        out.append(row)
    return out
