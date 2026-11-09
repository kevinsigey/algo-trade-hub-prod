"""The event battery (spec 2026-11-08, claim-typed gates amendment): the
relative-grading read for an event study, computed from the per-event rows the
event engine already measures.

Each event contributes its abnormal return over the study's preregistered
window — the name minus the benchmark over the identical window, signed by the
claimed direction — so the context is frozen at event time by construction.
Events, not days, are the sample: significance is the cross-event one-sample t
of that excess, with the hit rate beside it. The matched-peer read (the name
minus the median of the study's other tickers over the same window) is the
counterfactual control and is reported per span, never judged — for the
canonical single-name studies (FOMC drift on SPY) no in-study peer exists, and
a peer verdict leg would grade the study's ticker list, not its claim.

Frozen constants (preregistered in the spec; changing them is a new
preregistration, not an edit):

- MIN_EVENTS 20, MIN_UNSEEN_EVENTS 10: adopted unchanged from the event
  engine's own minimums (events.py, frozen 2026-10-31); a parity test pins the
  two modules together so they cannot drift.
- T_BAR_UNSEEN 2.0: the unseen span's cross-event t must reach the ordinary
  two-sigma bar.
- HIT_MIN_UNSEEN 0.55: at least 55% of unseen events must move the claimed
  way — a mean carried by a few huge wins is not a drift.
- T_BAR_BUILT 1.0: the built span formed the hypothesis; it must point the
  same way (mean > 0) at a lower bar. The verdict bar lives on unseen data.

Grandfathering: this battery is a reported read inside an event run. The run's
own verdict stays the event gate's (random-dates permutation), and the
registry's adjustment treats event runs exactly as before.

Pure: per-event excess arrays in, a battery dict out. events.py owns the rows,
the split and the result shape; this module owns the measurement.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

MIN_EVENTS = 20
MIN_UNSEEN_EVENTS = 10
T_BAR_UNSEEN = 2.0
T_BAR_BUILT = 1.0
HIT_MIN_UNSEEN = 0.55


def span_stats(x: np.ndarray) -> dict:
    """One span of signed per-event excess (in %): count, mean, cross-event t, hit rate."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = int(len(x))
    if n == 0:
        return {"n": 0, "mean": math.nan, "t": math.nan, "hit": math.nan}
    mean = float(np.mean(x))
    if n < 2:
        t = math.inf if mean > 0 else 0.0
    else:
        sd = float(np.std(x, ddof=1))
        t = (math.inf if mean > 0 else 0.0) if sd == 0.0 else float(mean / (sd / math.sqrt(n)))
    return {"n": n, "mean": mean, "t": t, "hit": float(np.mean(x > 0))}


def battery(index_excess: np.ndarray, peer_excess: np.ndarray | None, *, split: int) -> dict:
    """The event verdict over both spans. `index_excess` is the signed per-event
    abnormal return vs the benchmark (all events, in row order); `peer_excess`
    is the signed excess vs the in-study peer median (NaN where an event has no
    peer), or None for a single-name study."""
    spans: dict[str, dict] = {}
    for name, sl in (("built", slice(0, split)), ("unseen", slice(split, len(index_excess)))):
        peer = None
        if peer_excess is not None:
            st = span_stats(peer_excess[sl])
            peer = st if st["n"] else None
        spans[name] = {"index": span_stats(index_excess[sl]), "peer": peer}
    n, n_u = spans["built"]["index"]["n"] + spans["unseen"]["index"]["n"], spans["unseen"]["index"]["n"]
    if n < MIN_EVENTS or n_u < MIN_UNSEEN_EVENTS:
        return {"type": "event",
                "constants": {"min_events": MIN_EVENTS, "min_unseen_events": MIN_UNSEEN_EVENTS,
                              "t_bar_unseen": T_BAR_UNSEEN, "t_bar_built": T_BAR_BUILT,
                              "hit_min_unseen": HIT_MIN_UNSEEN},
                "spans": spans, "p": None, "legs": [],
                "verdict": "NOT ENOUGH DATA"}
    b, u = spans["built"]["index"], spans["unseen"]["index"]
    df = u["n"] - 1
    p = float(stats.t.sf(u["t"], df)) if df > 0 and math.isfinite(u["t"]) else (0.0 if u["t"] > 0 else 1.0)
    legs = [
        {"name": "built_direction", "holds": bool(b["mean"] > 0 and b["t"] >= T_BAR_BUILT),
         "detail": f"built span: mean {b['mean']:+.2f}% over {b['n']} events, t {b['t']:.2f} "
                   f"must be positive with t >= {T_BAR_BUILT}"},
        {"name": "t_unseen", "holds": bool(u["mean"] > 0 and u["t"] >= T_BAR_UNSEEN),
         "detail": f"unseen span: mean {u['mean']:+.2f}% over {u['n']} events, t {u['t']:.2f} "
                   f"must reach {T_BAR_UNSEEN}"},
        {"name": "hit_unseen", "holds": bool(u["hit"] >= HIT_MIN_UNSEEN),
         "detail": f"unseen hit rate {u['hit']:.0%} must be at least {HIT_MIN_UNSEEN:.0%}"},
    ]
    return {"type": "event",
            "constants": {"min_events": MIN_EVENTS, "min_unseen_events": MIN_UNSEEN_EVENTS,
                          "t_bar_unseen": T_BAR_UNSEEN, "t_bar_built": T_BAR_BUILT,
                          "hit_min_unseen": HIT_MIN_UNSEEN},
            "spans": spans, "p": p, "legs": legs,
            "verdict": "PASS" if all(leg["holds"] for leg in legs) else "FAIL"}
