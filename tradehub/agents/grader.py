"""Grading (feed spec §7): each completed run is scored at +5 and +20 trading days
after its as-of date against the ticker's own closes. Direction hit only; Hold is a
no-call; an exactly flat return is a miss. The record is reported separately from
every model statistic in the hub, and the falsification banner is arithmetic, not
an opinion: 30+ graded non-Hold runs at +5d with a hit rate at or under 50%."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from tradehub.agents import store
from tradehub.agents.schema import DIRECTION, GradeEntry, RunRecord

HORIZONS = (5, 20)
FALSIFY_MIN_RUNS = 30
FALSIFY_MAX_HIT_RATE = 0.5


def grade_run(run: RunRecord, closes: pd.Series, horizon: int, *, graded_at: str) -> GradeEntry | None:
    """None when the horizon hasn't arrived yet (pending, never 0)."""
    if run.decision is None:
        return None
    closes = closes.dropna().sort_index()
    pos = closes.index.get_indexer([pd.Timestamp(run.as_of_date)], method="pad")
    if len(pos) == 0 or pos[0] < 0 or pos[0] + horizon >= len(closes):
        return None
    base = float(closes.iloc[pos[0]])
    end = float(closes.iloc[pos[0] + horizon])
    if base <= 0:
        return None
    ret = (end / base - 1) * 100
    direction = DIRECTION.get(run.decision, 0)
    if direction == 0:
        outcome = "no-call"
    elif ret == 0.0:
        outcome = "miss"  # a flat return is a miss, recorded as such (§7)
    else:
        outcome = "hit" if (ret > 0) == (direction > 0) else "miss"
    return GradeEntry(run_id=run.run_id, horizon=horizon, ret_pct=ret, outcome=outcome,
                      graded_at=graded_at)


def grade_all(*, closes_fn, now: datetime | None = None) -> list[GradeEntry]:
    """Grade every due run/horizon. closes_fn(ticker) -> the ticker's close series."""
    graded_at = (now or datetime.now(UTC)).isoformat()
    done: list[GradeEntry] = []
    have = {(g.run_id, g.horizon) for g in store.load_grades()}
    for run in store.list_runs():
        if run.status != "complete" or run.decision is None:
            continue
        due = [h for h in HORIZONS if (run.run_id, h) not in have]
        if not due:
            continue
        try:
            closes = closes_fn(run.ticker)
        except Exception:  # noqa: BLE001 -- one bad ticker must not stop the rest
            continue
        for horizon in due:
            entry = grade_run(run, closes, horizon, graded_at=graded_at)
            if entry is not None:
                store.upsert_grade(entry)
                done.append(entry)
    return done


def record_summary(grades: list[GradeEntry]) -> dict:
    """The feed header's debate record, per horizon, plus the falsification banner."""
    out: dict = {}
    for horizon in HORIZONS:
        rows = [g for g in grades if g.horizon == horizon]
        calls = [g for g in rows if g.outcome != "no-call"]
        hits = sum(1 for g in calls if g.outcome == "hit")
        out[f"h{horizon}"] = {"graded": len(calls), "hits": hits,
                              "hit_rate": (hits / len(calls)) if calls else None,
                              "no_calls": len(rows) - len(calls)}
    h5 = out["h5"]
    out["banner"] = bool(h5["graded"] >= FALSIFY_MIN_RUNS and h5["hit_rate"] is not None
                         and h5["hit_rate"] <= FALSIFY_MAX_HIT_RATE)
    return out
