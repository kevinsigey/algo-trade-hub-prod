"""Trailing baselines for geo metrics: the plan's rule is that a value
only means something against OUR OWN trailing median (14-30 days of our
snapshots), never against a vendor's idea of normal. Pure functions --
the read API feeds them snapshot rows.
"""
from __future__ import annotations

import statistics


def trailing_median(values: list[float]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return round(statistics.median(clean), 4)


def with_baselines(current: list[dict], history: list[dict]) -> list[dict]:
    """current: the latest snapshot's rows (feed, metric, value, health).
    history: earlier rows with numeric values. Returns one entry per
    current measure (the 'health' pseudo-metric rows are excluded -- feed
    health rides on the entries themselves), each carrying its trailing
    median and the delta against it. A metric with no history yet gets
    baseline None -- named, never invented."""
    past: dict[tuple[str, str], list[float]] = {}
    for row in history:
        if row.get("value") is not None:
            past.setdefault((row["feed"], row["metric"]), []).append(float(row["value"]))
    out: list[dict] = []
    for row in current:
        if row.get("metric") == "health":
            continue
        baseline = trailing_median(past.get((row["feed"], row["metric"]), []))
        value = row.get("value")
        delta_pct = None
        if baseline not in (None, 0) and value is not None:
            delta_pct = round((float(value) / baseline - 1) * 100, 1)
        out.append({"feed": row["feed"], "metric": row["metric"], "value": value,
                    "health": row.get("health"), "baseline": baseline,
                    "delta_pct": delta_pct,
                    "baseline_n": len(past.get((row["feed"], row["metric"]), []))})
    return out


def feed_health(current: list[dict]) -> dict[str, str]:
    """Per-feed health from the latest batch: the explicit health row when
    present, else the health stamped on the feed's measure rows."""
    health: dict[str, str] = {}
    for row in current:
        if row.get("metric") == "health" and row.get("health"):
            health[row["feed"]] = row["health"]
    for row in current:
        if row["feed"] not in health and row.get("health"):
            health[row["feed"]] = row["health"]
    return health
