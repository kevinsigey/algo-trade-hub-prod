"""Cron entrypoint: one band-crossing grading pass (Spec C falsifier).

Fills +5/+20-session outcomes on entry crossings (starter / add /
short_put_spread) whose windows have matured, exactly as frozen: the
entry's return minus the same-name unconditional control, per unit of
risk. Idempotent — graded horizons are never recomputed. LOG-ONLY: this
writes grades, never orders. Suggested cadence: nightly, after the
valuation grading pass (deploy crontab 04:37 UTC).
"""

from __future__ import annotations

import sys

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.screening.sources import DataStore
from tradehub.valuation import band_crossing as bc


def main() -> int:
    load_local_env()
    out = bc.grade_crossings(get_client(), DataStore())
    print(f"band crossing grading: {out['entries_seen']} entries seen, "
          f"{out['rows_graded']} rows graded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
