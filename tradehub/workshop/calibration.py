"""The shipped options calibration (design 2026-10-31 section 2).

Produced by tradehub/scripts/options_calibrate.py from Alpaca's real
option bars: a skew curve fitted on 2024-2025 contracts and checked on
2026 (never re-fitted on years a test judges), typical bid-ask spreads
from live quotes, and the model's median error against real prices per
underlying. The engine prices option legs through the curve and charges
the spreads; verdicts quote the measured error, or say the underlying is
uncalibrated. Regenerate by re-running the script; do not hand-edit.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).with_name("calibration.json")


@lru_cache(maxsize=1)
def load_calibration() -> dict:
    return json.loads(_PATH.read_text())


def for_underlying(ticker: str) -> dict | None:
    """The calibration for one underlying, or None when it was never
    measured -- the run then prices flat-vol and says so."""
    cal = load_calibration()
    entry = (cal.get("underlyings") or {}).get(ticker)
    if entry is None:
        return None
    return {"skew": cal["skew"], "spread_frac": entry["spread_frac"],
            "median_err_check_pct": entry["median_err_check_pct"],
            "n_check": entry["n_check"],
            "fit_window": cal["fit_window"], "check_window": cal["check_window"]}
