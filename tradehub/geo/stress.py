"""The sensitive Hormuz stress read: continuous per-signal stress in [0, 1]
from the live geo_snapshots, replacing the geo shadow v2's three binary
thresholds (which only move when a line is crossed, and only among k in
{1.0, 1.25, 1.5}). Preregistered 2026-11-04 for the geo2 shadow family.

Each signal compares the latest batch value with its own trailing median
(the snapshot history is young -- batches every 15 minutes since 2026-11-02):

  collapse (flow drying up): stress = clamp01(1 - v / median)
  surge (activity spiking):  stress = clamp01((v / median - 1) / 2),
      so v2's old full-fire line (3x the median) is this scale's 1.0 and
      every step toward it counts. A zero median with v > 0 reads v / 3
      capped at 1 -- a few units from a zero baseline is real but graded.
  exceed (fires at terminals, whose median is usually zero): stress =
      clamp01(v / p95(history)); if the trailing p95 is 0, any v > 0 is 1.

Signals and weights (of 11): tanker gate flow 3, GPS jamming (intraday 2 +
daily 1, averaged into one jamming read), military air (the max of total /
ISR / tanker-aircraft surges) 2, anchored tankers 2, terminal fires 1.
USGS quakes are deliberately excluded: no defensible oil link at this grain.

Aggregation: the weighted mean of the signals that can speak. A signal
needs >= 24 history batches (~6h) and a live current value, else it is
excluded and the read is partial. If the speaking weight is under 6 of 11
the read is insufficient: stress None, k = 1.0 -- the unknown-never-zero
rule: absent evidence never widens sigma, and never narrows it either.

k = 1 + 0.75 * stress, so a true compound extreme (flow stopped, jamming
and military at 3x, tankers piling at anchor) reaches 1.75, above v2's
top tier; ordinary bad days land 1.1-1.4, where v2 sat at 1.0-1.25.
Sigma only -- the mean never moves: geo carries risk, not a sign.
"""

from __future__ import annotations

import statistics
from typing import Any

MIN_HISTORY = 24          # batches (~6h of 15-minute snapshots) before a signal may speak
MIN_SPEAKING_WEIGHT = 6   # of 11 total; below this the read is insufficient
K_SPAN = 0.75             # k = 1 + K_SPAN * stress

# (label, weight, [(feed, metric)], kind)
SIGNALS = (
    ("gate_flow", 3, (("ais", "tankers_gate_entries_1h"),), "collapse"),
    ("jamming", 3, (("adsb_jamming", "jamming_intraday"), ("gpsjam", "jamming_daily")), "surge_avg"),
    ("military", 2, (("adsb", "mil_total"), ("adsb", "mil_isr"), ("adsb", "mil_tanker")), "surge_max"),
    ("anchoring", 2, (("ais", "anchored_tankers"),), "surge"),
    ("terminal_fires", 1, (("firms", "frp_terminals"),), "exceed"),
)
TOTAL_WEIGHT = sum(w for _label, w, _keys, _kind in SIGNALS)


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def _median(values: list[float]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    return statistics.median(clean) if clean else None


def _surge(value: float, median: float) -> float:
    if median > 0:
        return _clamp01((value / median - 1.0) / 2.0)
    return _clamp01(value / 3.0) if value > 0 else 0.0


def _signal_stress(kind: str, legs: list[tuple[float, list[float]]]) -> float | None:
    """legs: (current value, history values) per key of the signal."""
    if kind == "collapse":
        value, history = legs[0]
        median = _median(history)
        if median is None or median <= 0:
            return None  # flow cannot collapse from a zero baseline; the signal cannot speak
        return _clamp01(1.0 - value / median)
    if kind == "surge":
        value, history = legs[0]
        median = _median(history)
        return None if median is None else _surge(value, median)
    if kind in ("surge_avg", "surge_max"):
        parts = []
        for value, history in legs:
            median = _median(history)
            if median is not None:
                parts.append(_surge(value, median))
        if not parts:
            return None
        return sum(parts) / len(parts) if kind == "surge_avg" else max(parts)
    if kind == "exceed":
        value, history = legs[0]
        clean = sorted(float(v) for v in history if v is not None)
        if not clean:
            return None
        p95 = clean[min(len(clean) - 1, int(0.95 * len(clean)))]
        if p95 <= 0:
            return 1.0 if value > 0 else 0.0
        return _clamp01(value / p95)
    raise ValueError(f"unknown signal kind {kind!r}")


def sensitive_stress(current: list[dict], history: list[dict]) -> tuple[float | None, float, dict, bool]:
    """(stress, k, contributions, partial) from snapshot rows shaped like
    geo_snapshots: {feed, metric, value, health}. Pure; tests without a DB."""
    now_by_key = {(r["feed"], r["metric"]): r for r in current}
    past: dict[tuple[str, str], list[float]] = {}
    for r in history:
        if r.get("value") is not None:
            past.setdefault((r["feed"], r["metric"]), []).append(float(r["value"]))

    contributions: dict[str, Any] = {}
    weighted, speaking = 0.0, 0
    partial = False
    for label, weight, keys, kind in SIGNALS:
        legs = []
        for key in keys:
            row = now_by_key.get(key)
            if row is None or row.get("health") != "live" or row.get("value") is None:
                legs = None
                break
            if len(past.get(key, [])) < MIN_HISTORY:
                legs = None
                break
            legs.append((float(row["value"]), past[key]))
        stress = _signal_stress(kind, legs) if legs else None
        if stress is None:
            partial = True
            contributions[label] = "unavailable"
            continue
        contributions[label] = round(stress, 3)
        weighted += weight * stress
        speaking += weight
    if speaking < MIN_SPEAKING_WEIGHT:
        return None, 1.0, contributions, True
    stress = weighted / speaking
    return stress, 1.0 + K_SPAN * stress, contributions, partial
