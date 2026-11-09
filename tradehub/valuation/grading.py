"""Relative grading (spec section 6). A verdict is graded against the context
frozen at render time: the name's return over the window minus the FROZEN
peer group's median return is the primary grade; the index excess and the
counterfactual peer-median basket ride beside it; entry-path quality
(MFE/MAE, time-to-target-band) and a Brier score on the RELATIVE outcome
complete the record. The same frozen context grades both controls (the
band-rule baseline and the proposer's own pick). The ~40-verdict authority
gate counts relative passes — a verdict's governing grade is its +60 when it
exists, else its +20."""
from __future__ import annotations

import statistics

import pandas as pd

HORIZONS = (20, 60)
AUTHORITY_GATE = 40

_LONG_ZONES = ("buy_zone", "buy_zone_strong")
_SHORT_ZONES = ("short_zone", "short_zone_strong")


def direction_of_zone(zone: str | None) -> str:
    """The band-rule baseline control's direction, read off its zone."""
    if zone in _LONG_ZONES:
        return "long"
    if zone in _SHORT_ZONES:
        return "short"
    return "none"


def _sign(direction: str | None) -> int:
    return {"long": 1, "short": -1}.get(direction or "", 0)


def _window(closes: pd.Series, render_date: str, horizon: int):
    """(entry_close, end_close, window_closes) or None when the horizon has
    not arrived. Trading days are the series' own index (the agents grader's
    convention)."""
    closes = closes.dropna().sort_index()
    pos = closes.index.get_indexer([pd.Timestamp(render_date)], method="pad")
    if len(pos) == 0 or pos[0] < 0 or pos[0] + horizon >= len(closes):
        return None
    start = float(closes.iloc[pos[0]])
    end = float(closes.iloc[pos[0] + horizon])
    window = closes.iloc[pos[0] + 1: pos[0] + horizon + 1]
    return start, end, window


def grade_call(*, direction: str | None, probability: float | None,
               entry_price: float | None, target_price: float | None,
               render_date: str, name_closes: pd.Series,
               peer_entry: dict[str, float], peer_closes: dict[str, pd.Series],
               spy_closes: pd.Series, horizon: int) -> dict | None:
    """One call graded at one horizon. None when the window is immature or
    the relative context cannot be graded (no peer with a full window)."""
    win = _window(name_closes, render_date, horizon)
    if win is None:
        return None
    _start, end, window = win
    if not entry_price or entry_price <= 0:
        return None
    name_ret = (end / entry_price - 1) * 100.0

    peer_rets: list[float] = []
    for ticker, frozen_price in peer_entry.items():
        if not frozen_price or frozen_price <= 0:
            continue
        series = peer_closes.get(ticker)
        if series is None:
            continue
        pwin = _window(series, render_date, horizon)
        if pwin is None:
            continue
        peer_rets.append((pwin[1] / frozen_price - 1) * 100.0)
    if not peer_rets:
        return None
    peer_median = statistics.median(peer_rets)
    peer_excess = name_ret - peer_median

    spy_win = _window(spy_closes, render_date, horizon)
    index_excess = None
    if spy_win is not None and spy_win[0] > 0:
        index_excess = name_ret - (spy_win[1] / spy_win[0] - 1) * 100.0

    sign = _sign(direction)
    relative_pass = None
    brier = None
    if sign != 0:
        relative_pass = bool(peer_excess * sign > 0)
        if probability is not None:
            brier = (float(probability) - (1.0 if relative_pass else 0.0)) ** 2

    closes = [float(c) for c in window]
    hi, lo = max(closes), min(closes)
    if sign < 0:
        mfe = (entry_price - lo) / entry_price * 100.0
        mae = (entry_price - hi) / entry_price * 100.0
    else:
        mfe = (hi - entry_price) / entry_price * 100.0
        mae = (lo - entry_price) / entry_price * 100.0
    time_to_target = None
    if target_price is not None and sign != 0:
        for k, close in enumerate(closes, start=1):
            if (sign > 0 and close >= target_price) or \
                    (sign < 0 and close <= target_price):
                time_to_target = k
                break

    return {
        "horizon": horizon,
        "name_ret_pct": round(name_ret, 4),
        "peer_median_ret_pct": round(peer_median, 4),
        "peer_excess_pct": round(peer_excess, 4),
        "peers_graded": len(peer_rets),
        "index_excess_pct": (round(index_excess, 4)
                             if index_excess is not None else None),
        "basket_ret_pct": round(peer_median, 4),
        "relative_pass": relative_pass,
        "brier": (round(brier, 6) if brier is not None else None),
        "mfe_pct": round(mfe, 4),
        "mae_pct": round(mae, 4),
        "time_to_target_days": time_to_target,
    }


def authority_summary(grade_rows: list[dict], *, gate: int = AUTHORITY_GATE) -> dict:
    """The authority gate over grade rows (any horizon mix): each verdict's
    governing grade is its +60 when present, else +20; no-calls (relative_pass
    None) are not graded verdicts."""
    by_verdict: dict[int, dict] = {}
    for row in grade_rows:
        current = by_verdict.get(row["verdict_id"])
        if current is None or row["horizon"] > current["horizon"]:
            by_verdict[row["verdict_id"]] = row
    graded = [r for r in by_verdict.values()
              if r.get("verdict_relative_pass") is not None]
    passes = sum(1 for r in graded if r["verdict_relative_pass"])
    briers = [r["verdict_brier"] for r in graded
              if r.get("verdict_brier") is not None]
    return {
        "gate": gate,
        "graded_verdicts": len(graded),
        "relative_passes": passes,
        "pass_rate": (round(passes / len(graded), 4) if graded else None),
        "mean_brier": (round(sum(briers) / len(briers), 4) if briers else None),
        "status": "display_only" if passes < gate else "authority_gate_met",
    }


# ---------------------------------------------------------------------------
# The grading job: mature verdicts accrue grades automatically.
# ---------------------------------------------------------------------------

def _closes_from_frame(frame: pd.DataFrame, ticker: str) -> pd.Series | None:
    if frame is None or ticker not in frame.columns:
        return None
    return frame[ticker].dropna()


def grade_verdict_row(client, ds, verdict: dict, *, now=None) -> list[dict]:
    """Grade one stored verdict at every matured, ungraded horizon (verdict +
    both controls on the same frozen context) and upsert the grade rows.
    Returns the rows written."""
    from tradehub.valuation import verdict_store

    existing = {(g["verdict_id"], g["horizon"])
                for g in verdict_store.grades_for(client, verdict["id"])}
    frozen = verdict.get("frozen_peers") or {}
    peer_entry = {m["ticker"]: m.get("price")
                  for m in frozen.get("members") or []}
    tickers = [verdict["ticker"]] + [t for t in peer_entry
                                     if t != verdict["ticker"]] + ["SPY"]
    try:
        frame = ds.prices(tickers, years=3)
    except Exception:  # noqa: BLE001 -- a failed price pull defers the grade
        return []
    name_closes = _closes_from_frame(frame, verdict["ticker"])
    spy_closes = _closes_from_frame(frame, "SPY")
    if name_closes is None or spy_closes is None:
        return []
    peer_closes = {t: _closes_from_frame(frame, t) for t in peer_entry}
    peer_closes = {t: s for t, s in peer_closes.items() if s is not None}

    verdict_pick = verdict.get("verdict") or {}
    proposer_pick = verdict.get("proposer_pick") or {}
    calls = {
        "verdict": (verdict_pick.get("direction"),
                    verdict_pick.get("probability")),
        "baseline": (direction_of_zone(verdict.get("baseline_verdict")), None),
        "proposer": (proposer_pick.get("direction"),
                     proposer_pick.get("probability")),
    }
    written: list[dict] = []
    for horizon in HORIZONS:
        if (verdict["id"], horizon) in existing:
            continue
        grades: dict[str, dict | None] = {}
        for who, (direction, probability) in calls.items():
            grades[who] = grade_call(
                direction=direction, probability=probability,
                entry_price=verdict.get("price"),
                target_price=verdict.get("target_price"),
                render_date=str(verdict["rendered_at"])[:10],
                name_closes=name_closes, peer_entry=peer_entry,
                peer_closes=peer_closes, spy_closes=spy_closes,
                horizon=horizon)
        if grades["verdict"] is None:
            continue  # immature, or the relative context cannot be graded yet
        row = {"verdict_id": verdict["id"], "horizon": horizon}
        for who in ("verdict", "baseline", "proposer"):
            g = grades[who] or {}
            row[f"{who}_relative_pass"] = g.get("relative_pass")
            row[f"{who}_brier"] = g.get("brier")
        main = grades["verdict"]
        for key in ("name_ret_pct", "peer_median_ret_pct", "peer_excess_pct",
                    "peers_graded", "index_excess_pct", "basket_ret_pct",
                    "mfe_pct", "mae_pct", "time_to_target_days"):
            row[key] = main.get(key)
        verdict_store.upsert_grade(client, row)
        written.append(row)
    return written


def run_grading(client, ds, *, now=None) -> dict:
    """One grading pass over every stored verdict. Scheduled (see
    tradehub/scripts/valuation_grade_run.py); idempotent — graded horizons
    are never recomputed."""
    from tradehub.valuation import verdict_store

    written = 0
    for verdict in verdict_store.all_verdicts(client):
        written += len(grade_verdict_row(client, ds, verdict))
    return {"grades_written": written}
