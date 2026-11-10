"""Cron entrypoint: one Level Watcher grading pass (Spec D, Stage 1).

Fills +1/+5-session scores on trigger-log fires (the no-action
counterfactual: the score is the intent-signed return; +5 governs)
and applies the frozen demotion rule — a rule family with 20 graded
triggers and a negative mean demotes one rung, which at Stage 1
auto-disables its watches, once, with an alert. Band-crossing fires
are graded by Spec C's falsifier, not here. Idempotent: filled
horizons are never recomputed. Suggested cadence: nightly, after the
band-crossing grading pass (deploy crontab ~04:52 UTC).
"""

from __future__ import annotations

import sys

from tradehub import level_watcher as lw
from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.screening.sources import DataStore


def main() -> int:
    load_local_env()
    out = lw.grade_fires(get_client(), DataStore())
    print(f"level watcher grading: {out['fires_seen']} fires seen, "
          f"{out['graded']} graded, demoted: {out['demoted'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
