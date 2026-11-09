"""Cron entrypoint: one relative-grading pass (spec section 6). Every
verdict whose +20/+60 trading-day window has matured accrues its grade —
peer-relative excess (primary), index excess, the counterfactual
peer-median basket, entry-path quality, and the Brier on the relative
outcome — with both controls graded on the same frozen context. Idempotent:
graded horizons are never recomputed. Suggested cadence: nightly
(deploy-side act, noted in the Phase 1 report).
"""

from __future__ import annotations

import sys

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.screening.sources import DataStore
from tradehub.valuation import grading


def main() -> int:
    load_local_env()
    out = grading.run_grading(get_client(), DataStore())
    print(f"valuation grading: {out['grades_written']} grades written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
