"""Cron entrypoint: one 15-minute-model pass -- freeze, settle and score
for the fifteen_min forecasters only.

Kevin's call 2026-11-04: the model predicts EVERY 15-minute window, not
just the one window per hour the journal's run phase happened to sample.
The journal's own runner does the work (same freeze/settle/score path,
same dedupe), so this script only narrows the roster. It runs on the
VPS's deploy crontab every 5 minutes: the freeze band opens 1.5 minutes
into a window, so the +5 pass lands the freeze and the +10 pass dedupes.
The hourly journal run keeps passing over the same rows harmlessly.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.data.kalshi_live import KalshiLive
from tradehub.journal.forecasters.fifteen_min import build_fifteen_min
from tradehub.journal.runner import run_forecaster


def run(supa, forecasters, now: datetime) -> dict[str, Any]:
    return {f.name: run_forecaster(supa, f, now) for f in forecasters}


def main() -> int:
    load_local_env()
    summary = run(get_client(), build_fifteen_min(KalshiLive()), datetime.now(UTC))
    print(json.dumps(summary, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
