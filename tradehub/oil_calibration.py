"""Calibration for the WTI hourly best-strike picker (picker v2).

Spec: docs/superpowers/specs/2026-11-09-hourly-best-strike-picker-v2-amendment.md.
The hourly model's stated probabilities run hot — the frozen record
audited 2026-11-09 claims 44.3% and realizes 31.4% — and the picker had
no correction step at all. This module fits the correction on the
picker's own evidence: the settled journal rows of the live ladder's
forecaster version (``wti-hourly-v4-hl-shadow``, the same model on the
same Hyperliquid feed the ladder prices from), following the 15-minute
family's pattern of bucketing stated probabilities against realized
frequencies, fitted walk-forward on settled rows.

The map: fixed 10-point buckets over the stated YES probability; a
bucket's value is its realized frequency pulled toward its own mean
stated probability by a pseudocount of 20, so thin buckets barely move
and full ones speak; values are made monotone across buckets (PAVA) and
applied piecewise-linearly. Below the bucket floors the preregistered
fallback is a least-squares linear shrinkage toward the training base
rate; below that, identity. Fitting is walk-forward by construction:
callers pass only samples whose event closed before the freeze's event
(``pairs_before``), and the map's version string names what it trained
on (kind, constants, training-through event close, row count).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from tradehub.engines.oil_hourly import event_hour
from tradehub.journal.store import fetch_forecasts, fetch_settlements

log = logging.getLogger(__name__)

FORECASTER = "oil_wti_hourly"
FORECASTER_VERSION = "wti-hourly-v4-hl-shadow"
PSEUDOCOUNT = 20.0
MIN_BUCKET_ROWS = 1000
MIN_BUCKET_EVENTS = 40
MIN_SHRINKAGE_ROWS = 5


@dataclass(frozen=True)
class CalSample:
    prob: float
    hit: bool
    event_close: datetime


@dataclass(frozen=True)
class CalibMap:
    kind: str  # "buckets" | "shrinkage" | "identity"
    knots: tuple[tuple[float, float], ...] = ()
    base_rate: float = 0.0
    slope: float = 1.0
    n_rows: int = 0
    n_events: int = 0
    through: datetime | None = None
    version: str = "oilcal-identity-n0"


def pairs_before(samples: list[CalSample], cutoff: datetime) -> list[CalSample]:
    """The walk-forward filter: only samples from events that closed
    strictly before ``cutoff`` may train a map used at ``cutoff``."""
    return [s for s in samples if s.event_close < cutoff]


def _pava(values: list[float], weights: list[float]) -> list[float]:
    """Weighted pool-adjacent-violators: the nondecreasing fit."""
    blocks: list[list] = []  # [weighted mean, total weight, size]
    for value, weight in zip(values, weights):
        blocks.append([float(value), float(weight), 1])
        while len(blocks) >= 2 and blocks[-2][0] > blocks[-1][0]:
            v2, w2, c2 = blocks.pop()
            v1, w1, c1 = blocks.pop()
            blocks.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
    out: list[float] = []
    for value, _weight, size in blocks:
        out.extend([value] * size)
    return out


def fit_map(samples: list[CalSample]) -> CalibMap:
    samples = list(samples)
    n = len(samples)
    closes = {s.event_close for s in samples}
    through = max(closes) if closes else None
    stamp = through.strftime("%Y%m%dT%H%MZ") if through else "NA"
    if n >= MIN_BUCKET_ROWS and len(closes) >= MIN_BUCKET_EVENTS:
        buckets: list[list[CalSample]] = [[] for _ in range(10)]
        for s in samples:
            buckets[min(9, max(0, int(s.prob * 10)))].append(s)
        raw: list[float] = []
        weights: list[float] = []
        for i, rows in enumerate(buckets):
            if rows:
                mean_stated = sum(r.prob for r in rows) / len(rows)
                hits = sum(1 for r in rows if r.hit)
                raw.append((hits + PSEUDOCOUNT * mean_stated) / (len(rows) + PSEUDOCOUNT))
            else:
                raw.append(0.05 + 0.1 * i)  # no evidence: anchor at the bucket's centre
            weights.append(len(rows) + PSEUDOCOUNT)
        knots = tuple((0.05 + 0.1 * i, round(v, 6)) for i, v in enumerate(_pava(raw, weights)))
        return CalibMap("buckets", knots, n_rows=n, n_events=len(closes), through=through,
                        version=f"oilcal-buckets10-k{int(PSEUDOCOUNT)}-thru{stamp}-n{n}")
    if n >= MIN_SHRINKAGE_ROWS:
        base = sum(1 for s in samples if s.hit) / n
        sxx = sum((s.prob - base) ** 2 for s in samples)
        sxy = sum((s.prob - base) * ((1.0 if s.hit else 0.0) - base) for s in samples)
        slope = min(2.0, max(0.0, sxy / sxx)) if sxx > 0 else 0.0
        return CalibMap("shrinkage", base_rate=base, slope=slope, n_rows=n,
                        n_events=len(closes), through=through,
                        version=f"oilcal-shrink-thru{stamp}-n{n}")
    return CalibMap("identity", n_rows=n, n_events=len(closes), through=through,
                    version=f"oilcal-identity-n{n}")


def apply_map(m: CalibMap, p: float) -> float:
    p = min(1.0, max(0.0, float(p)))
    if m.kind == "buckets":
        knots = m.knots
        if p <= knots[0][0]:
            return knots[0][1]
        if p >= knots[-1][0]:
            return knots[-1][1]
        for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
            if x0 <= p <= x1:
                return round(y0 + (y1 - y0) * (p - x0) / (x1 - x0), 6)
        return knots[-1][1]
    if m.kind == "shrinkage":
        return round(min(1.0, max(0.0, m.base_rate + m.slope * (p - m.base_rate))), 6)
    return p


def load_samples(supa) -> list[CalSample]:
    """Every settled row of the live ladder's forecaster version, as
    (stated probability, outcome, event close). The event comes from
    the target ticker (``KXWTIH-26NOV0913-T88.5`` -> the 0913 event);
    rows whose event cannot be parsed are skipped, never guessed."""
    forecasts = fetch_forecasts(supa, FORECASTER, FORECASTER_VERSION)
    settlements = fetch_settlements(supa, [f["target"] for f in forecasts])
    out: list[CalSample] = []
    for f in forecasts:
        outcome = settlements.get(f["target"])
        parts = str(f["target"]).split("-")
        if outcome is None or len(parts) < 3:
            continue
        try:
            close = event_hour(f"{parts[0]}-{parts[1]}")
        except ValueError:
            continue
        out.append(CalSample(float(f["probability"]), bool(outcome), close))
    return out
