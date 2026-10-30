"""A live idea's paper record: its shadow days summed up, and the "claim failing on paper" flag (spec §5)."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from tradehub.workshop.engine import claim_check
from tradehub.workshop.spec import IdeaSpec

FAILING_WINDOW = 63  # rolling 3 months; the flag waits for a full window
STALE_WEEKDAYS = 3


def shadow_summary(spec: IdeaSpec, rows: list[dict], today: date) -> dict:
    if not rows:
        return {"days": 0, "since": None, "as_of": None, "state": "waiting", "return_pct": None,
                "bench_return_pct": None, "claim": None, "failing": False, "curve": []}
    frame = pd.DataFrame(rows)
    idea, bench = np.cumprod(1 + frame["ret"].to_numpy()), np.cumprod(1 + frame["bench"].to_numpy())
    as_of = date.fromisoformat(rows[-1]["day"])
    late = int(np.busday_count(as_of + timedelta(days=1), today)) if today > as_of else 0
    claim = claim_check(spec, frame.iloc[-FAILING_WINDOW:]) if len(rows) >= FAILING_WINDOW else None
    return {
        "days": len(rows), "since": rows[0]["day"], "as_of": rows[-1]["day"],
        "state": "stale" if late > STALE_WEEKDAYS else "live",
        "return_pct": (idea[-1] - 1) * 100, "bench_return_pct": (bench[-1] - 1) * 100,
        "claim": None if claim is None else {k: claim[k] for k in ("holds", "label", "days")},
        "failing": claim is not None and not claim["holds"],
        "curve": [{"t": r["day"], "idea": (i - 1) * 100, "bench": (b - 1) * 100}
                  for r, i, b in zip(rows, idea, bench, strict=True)],
    }
