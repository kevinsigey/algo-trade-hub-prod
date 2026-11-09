"""Cron entrypoint: one 15-minute-model pass -- freeze, settle and score
for the fifteen_min forecasters only.

Kevin's call 2026-11-04: the model predicts EVERY 15-minute window, not
just the one window per hour the journal's run phase happened to sample.
The journal's own runner does the work (same freeze/settle/score path,
same dedupe), so this script only narrows the roster. It runs on the
VPS's deploy crontab every 5 minutes: the freeze band opens 1.5 minutes
into a window, so the +5 pass lands the freeze and the +10 pass dedupes.
The hourly journal run keeps passing over the same rows harmlessly.

Amendment 2026-11-08: after the journal passes, the same run also writes
the trade rule's tracking (tradehub/fifteen_tracking.py) -- one persisted
decision per targeted window and the per-offset shadow track for settled
windows. Same invocation, no new arguments; a tracking failure is reported
in the summary, never allowed to fail the freeze pass it rides on.

Amendment 2026-11-09: the same run also writes the oil minute-1 shadow
variant's grid and its once-a-day promotion evaluation
(tradehub/fifteen_shadow.py, preregistration
docs/superpowers/specs/2026-11-09-fifteen-shadow-oil-minute1-prereg.md),
under the same fail-soft rule.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

from tradehub import fifteen_shadow, fifteen_tracking
from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.data.kalshi_live import KalshiLive
from tradehub.journal.forecasters.fifteen_min import build_fifteen_min
from tradehub.journal.runner import run_forecaster


def run(supa, forecasters, now: datetime) -> dict[str, Any]:
    summary = {f.name: run_forecaster(supa, f, now) for f in forecasters}
    for key, fn in (("fifteen_decisions", fifteen_tracking.record_decisions),
                    ("fifteen_offsets", fifteen_tracking.record_offsets),
                    ("fifteen_shadow", fifteen_shadow.record_shadow),
                    ("fifteen_shadow_eval", fifteen_shadow.evaluate_daily)):
        try:
            summary[key] = fn(supa, now)
        except Exception as exc:  # noqa: BLE001 -- tracking reports, it never blocks the freeze
            summary[key] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    return summary


def main() -> int:
    load_local_env()
    summary = run(get_client(), build_fifteen_min(KalshiLive()), datetime.now(UTC))
    print(json.dumps(summary, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
