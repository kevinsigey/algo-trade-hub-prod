"""The Binance-tape gold shadow (preregistration
docs/superpowers/specs/2026-11-14-fifteen-binance-gold-shadow-prereg.md,
frozen 2026-11-14; Kevin's tape ruling 2026-11-13).

The 15-minute model for gold, read off the Binance XAUUSDT 1-minute tape
instead of Hyperliquid's. The tape-fit study (2026-11-14) found Binance's
implied outcome matches Kalshi's settlement on gold in 98.10% of paired
windows against Hyperliquid's 93.92% -- the only series where Binance
clearly beats Hyperliquid and passes the cross-venue gate. Everything
else is v1's own machinery, unchanged: the read is the model's
`read_window` evaluated at v1's freeze instant on the Binance tape, and
the gate is the live rule's `evaluate` on that probability with v1's
frozen quotes (the market side is identical; only the model's
probability changes). Same fee netting, same 10-point bar, same halt
exclusion.

A record only, in the shadow's own tables, scored fresh and paired
against the live rule's gold decisions on the same windows. The
promotion bar is evaluated and stored, but nothing here can promote,
feed a demo lane, or place an order: that path is Kevin's word and a
separate commission. Nothing here writes to v1's, the live rule's, the
blend's or the challenger's tables.

Transport amendment (2026-11-16, Kevin's pick; preregistration
amendment in the prereg doc): Binance's REST hosts refuse the hub's
VPS egress (HTTP 451), so the tape is read from the websocket
collector's cache (tradehub/binance_tape.py) instead of a REST pull.
Same XAUUSDT 1-minute tape, same read, same bar -- only the transport
changed. The REST reader below stays for the replay convention and in
case the egress block ever lifts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tradehub import binance_tape
from tradehub import fifteen_blend as blend
from tradehub import fifteen_tracking as tracking
from tradehub import oil_fifteen_rule as rule
from tradehub.backtest.http import default_get_json
from tradehub.engines.fifteen_min import WINDOW_MINUTES
from tradehub.fifteen_volregime import clustered_low95
from tradehub.journal import store
from tradehub.journal.forecasters.fifteen_min import read_window
from tradehub.journal.kalshi_linked import ticker_of

PREREG_AT = "2026-11-16T00:00:00+00:00"
# The prereg's frozen stopping rule: retired as a record at 300 fresh
# trades or 60 days after PREREG_AT (2027-01-15), whichever comes
# first. Enforced in record_binance (Claude's cleanup, 2026-11-17).
STOP_FRESH_TRADES = 300
STOP_AT = datetime(2027, 1, 15, tzinfo=UTC)
SHADOW_VERSION = "v5-binance-gold-shadow"
DECISIONS_TABLE = "fifteen_binance_decisions"
EVALS_TABLE = "fifteen_binance_evals"
NAME, VERSION = "gold_15m", "gold-15m-v1"
SERIES = "KXGOLD15M"
BINANCE_SYMBOL = "XAUUSDT"
BINANCE_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
TAPE_SPAN = timedelta(minutes=150)  # the forecaster's own tape span
_KLINE_LIMIT = 1500  # the klines endpoint's per-call cap
_PREREG_DT = datetime.fromisoformat(PREREG_AT)
_ET = ZoneInfo("America/New_York")
_dt, _read = blend._dt, blend._read


def binance_klines(symbol: str, start: datetime, end: datetime, *,
                   get_json=default_get_json) -> list[tuple[datetime, float]]:
    """[(minute_start_utc, close)] over [start, end) from Binance USD-M
    futures 1-minute klines (public, no key), paginated at the endpoint's
    candle cap. The same (open time -> close) convention as the replay's
    Binance tape (backtest/history_tapes.parse_binance_klines)."""
    out: list[tuple[datetime, float]] = []
    cursor = start
    while cursor < end:
        rows = get_json(BINANCE_KLINES_URL, {
            "symbol": symbol, "interval": "1m",
            "startTime": int(cursor.timestamp() * 1000),
            "endTime": int(end.timestamp() * 1000), "limit": _KLINE_LIMIT})
        if not rows:
            break
        for r in rows:
            t = datetime.fromtimestamp(int(r[0]) / 1000, UTC)
            if start <= t < end:
                out.append((t, float(r[4])))
        last = datetime.fromtimestamp(int(rows[-1][0]) / 1000, UTC)
        if len(rows) < _KLINE_LIMIT or last <= cursor:
            break
        cursor = last + timedelta(minutes=1)
    return sorted(set(out))


def _market_prob(pay: dict) -> float | None:
    bid, ask = pay.get("yes_bid"), pay.get("yes_ask")
    if bid is None or ask is None:
        return None
    return round((float(bid) + float(ask)) / 2, 5)


def _stopped(supa, now: datetime) -> str | None:
    """The prereg's stopping rule, enforced: the reason the shadow has
    retired as a record, or None while it still records. The date arm
    needs no read; the trade arm counts the fresh segment's settled
    trades (the same population the eval grades)."""
    if now >= STOP_AT:
        return "date_stop_2027-01-15"
    # Read directly, not through blend._read (Claude's review of the
    # cleanup PR): _read swallows a failed read to [], which here would
    # count 0 trades and let the stopping rule fail OPEN -- the shadow
    # would keep recording past its stop on a broken read. select_all
    # raises instead, and the runner's fail-soft wrapper writes nothing
    # that pass.
    fresh = [r for r in store.select_all(
        supa, DECISIONS_TABLE, lambda q: q.gte("window_open", PREREG_AT), ("id",))
        if _dt(r["window_open"]) >= _PREREG_DT]
    n = sum(1 for r in fresh if r["action"] == "buy" and r.get("outcome") is not None
            and r.get("pnl") is not None)
    if n >= STOP_FRESH_TRADES:
        return f"fresh_trade_stop_{STOP_FRESH_TRADES}"
    return None


def _tape_gap_totals() -> dict[str, Any]:
    """The collector's reconnect gaps, as the eval reports them
    (Claude's cleanup, 2026-11-17): count and total minutes. The eval
    table has no columns for them, so they ride the eval's returned
    report (and summary) rather than the stored row."""
    gaps = binance_tape.read_gaps()
    minutes = 0.0
    for g in gaps:
        try:
            minutes += max(0.0, (_dt(g["end"]) - _dt(g["start"])).total_seconds() / 60.0)
        except (KeyError, TypeError, ValueError):
            continue
    return {"count": len(gaps), "minutes": round(minutes, 1)}


def record_binance(supa, now: datetime, *, klines_fn=None,
                   lookback: timedelta = blend.LOOKBACK) -> dict[str, Any]:
    """One shadow decision per fresh targeted gold window in the lookback,
    upserted on (series, target). Windows opened before the
    preregistration are never written. A failed tape fetch raises; the
    runner's fail-soft wrapper reports it and nothing is written that
    pass -- an outage never masquerades as a read."""
    stopped = _stopped(supa, now)
    if stopped is not None:
        return {"windows": 0, "buy": 0, "stopped": stopped}
    targets = [t for t in tracking.fetch_targets(supa, NAME, now - lookback, now)
               if _dt(t["cutoff_at"]) - timedelta(minutes=WINDOW_MINUTES) >= _PREREG_DT]
    if not targets:
        return {"windows": 0, "buy": 0}
    names = [t["target"] for t in targets]
    first = tracking._first_forecasts(supa, NAME, VERSION, names)
    settled = store.fetch_settlements(supa, names)
    earliest_open = min(_dt(t["cutoff_at"]) for t in targets) - timedelta(minutes=WINDOW_MINUTES)
    tape = (klines_fn or binance_tape.read_cached_klines)(
        BINANCE_SYMBOL, earliest_open - TAPE_SPAN, now)
    rows: list[dict] = []
    for t in targets:
        target = t["target"]
        close_time = _dt(t["cutoff_at"])
        window_open = close_time - timedelta(minutes=WINDOW_MINUTES)
        frozen = first.get(target)
        outcome = settled.get(target)
        base = {"series": SERIES, "target": target,
                "ticker": ticker_of(target) if target.startswith("kalshi:") else target,
                "window_open": window_open.isoformat(),
                "close_time": close_time.isoformat(),
                "gate_version": SHADOW_VERSION, "evaluated_at": now.isoformat()}
        if frozen is None:
            ref = (window_open + timedelta(minutes=5)).isoformat()
            rows.append({**base, "frozen_at": None, "sigma_1m": None,
                         "model_prob": None, "market_prob": None, "v1_prob": None,
                         "session": "open" if rule.futures_open(ref) else "closed",
                         "action": "skip", "reason": "no_prediction",
                         "side": None, "cost": None,
                         "edge_net": None, "best_edge_net": None,
                         "outcome": outcome, "pnl": None})
            continue
        pay = frozen.get("payload") or {}
        market = _market_prob(pay)
        v1_prob = round(float(frozen["probability"]), 5)
        session = "open" if rule.futures_open(frozen["frozen_at"]) else "closed"
        read = read_window(close_time, tape, _dt(frozen["frozen_at"]))
        if read is None:
            rows.append({**base, "frozen_at": frozen["frozen_at"], "sigma_1m": None,
                         "model_prob": None, "market_prob": market, "v1_prob": v1_prob,
                         "session": session, "action": "skip", "reason": "stale_tape",
                         "side": None, "cost": None, "edge_net": None,
                         "best_edge_net": None, "outcome": outcome, "pnl": None})
            continue
        ev = rule.evaluate(read["prob_up"], yes_ask=pay.get("yes_ask"),
                           yes_bid=pay.get("yes_bid"), frozen_at=frozen["frozen_at"])
        rows.append({**base, "frozen_at": frozen["frozen_at"],
                     "sigma_1m": read["sigma_1m"],
                     "model_prob": round(read["prob_up"], 5),
                     "market_prob": market, "v1_prob": v1_prob,
                     "session": session, "action": ev["action"], "reason": ev["reason"],
                     "side": ev["side"], "cost": ev["cost"],
                     "edge_net": ev["edge_net"], "best_edge_net": ev["best_edge_net"],
                     "outcome": outcome,
                     "pnl": rule.pnl(ev["side"], ev["cost"], outcome)
                            if ev["action"] == "buy" and outcome is not None else None})
    if rows:
        supa.table(DECISIONS_TABLE).upsert(rows, on_conflict="series,target").execute()
    return {"windows": len(rows), "buy": sum(r["action"] == "buy" for r in rows)}


def _et_day(value: Any) -> str:
    return _dt(value).astimezone(_ET).date().isoformat()


def _pnl_or_zero(r: dict) -> float:
    return float(r["pnl"]) if r["action"] == "buy" and r.get("pnl") is not None else 0.0


def _evaluate(supa) -> dict[str, Any]:
    """The fresh-segment read, no writes: the shadow's settled record and
    the per-window paired delta against the live rule's gold decisions."""
    fresh = [r for r in _read(supa, DECISIONS_TABLE, lambda q: q.gte("window_open", PREREG_AT))
             if _dt(r["window_open"]) >= _PREREG_DT]
    trades = [r for r in fresh if r["action"] == "buy" and r.get("outcome") is not None
              and r.get("pnl") is not None]
    n, mean, low = blend._mean_low95([float(r["pnl"]) for r in trades])
    live = {r["target"]: r
            for r in _read(supa, rule.DECISIONS_TABLE,
                           lambda q: q.eq("series", SERIES).gte("window_open", PREREG_AT))}
    deltas = []
    for r in fresh:
        o = live.get(r["target"])
        if r.get("outcome") is None or o is None or o.get("outcome") is None:
            continue
        deltas.append(((SERIES, _et_day(r["window_open"])), _pnl_or_zero(r) - _pnl_or_zero(o)))
    pn, pmean, plow = blend._mean_low95([d for _k, d in deltas])
    clow = clustered_low95([((SERIES, _et_day(r["window_open"])), float(r["pnl"]))
                            for r in trades])
    pclow = clustered_low95(deltas)
    met = blend.criterion_met(n, low, plow)
    return {"windows": len(fresh), "trades": n,
            "tape_gaps": _tape_gap_totals(),
            "net_per_contract": round(mean, 4) if mean is not None else None,
            "low95": round(low, 4) if low is not None else None,
            "win_rate": round(sum(float(r["pnl"]) > 0 for r in trades) / n, 3) if n else None,
            "paired_windows": pn,
            "paired_delta": round(pmean, 4) if pmean is not None else None,
            "paired_low95": round(plow, 4) if plow is not None else None,
            "low95_clustered": round(clow, 4) if clow is not None else None,
            "paired_low95_clustered": round(pclow, 4) if pclow is not None else None,
            "criterion_met": met, "eligible": met}


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
                              "low95_clustered", "paired_low95_clustered",
                              "criterion_met", "eligible")}}).execute()
    return ev


def summary(supa) -> dict[str, Any]:
    """The record's read: fresh record, paired delta, and the bar
    (record only; no promotion path is built)."""
    ev = _evaluate(supa)
    return {"gate_version": SHADOW_VERSION, "prereg_at": PREREG_AT, "series": SERIES,
            "fresh": {**{k: ev[k] for k in ("windows", "trades", "net_per_contract",
                                            "low95", "win_rate")},
                      "clustered_low95": ev["low95_clustered"]},
            "paired": {"windows": ev["paired_windows"], "delta_per_window": ev["paired_delta"],
                       "low95": ev["paired_low95"],
                       "clustered_low95": ev["paired_low95_clustered"]},
            "tape_gaps": ev["tape_gaps"],
            "promotion": {"met": ev["criterion_met"], "eligible": ev["eligible"],
                          "path_built": False,
                          "criterion": {"min_trades": blend.PROMOTION_MIN_TRADES,
                                        "shadow_low95_above": 0, "paired_low95_above": 0}}}
