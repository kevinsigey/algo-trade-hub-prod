"""Cron entrypoint: one snapshot of the Alpaca paper account (Trading HQ step 1).

Run at :05 every hour by the VPS `tradehub-portfolio.timer`; it writes only on weekdays 08:00-15:59 CT,
so the curve is market hours plus the 15:05 near-close point. No holiday calendar (ponytail: a holiday
snapshot repeats the last equity; add one if it ever shows on the curve).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.portfolio.service import take_snapshot

CT = ZoneInfo("America/Chicago")


def in_market_hours(now: datetime) -> bool:
    ct = now.astimezone(CT)
    return ct.weekday() < 5 and 8 <= ct.hour <= 15


def main(now: datetime | None = None, supa=None) -> int:
    now = now or datetime.now(UTC)
    if not in_market_hours(now):
        print(json.dumps({"snapshot": "skipped", "reason": "outside market hours"}))
        return 0
    load_local_env()
    try:
        row = take_snapshot(supa or get_client(), now)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"snapshot": "failed", "error": str(exc)}))
        return 1
    if row is None:
        print(json.dumps({"snapshot": "skipped", "reason": "paper account not connected"}))
        return 0
    print(json.dumps({"snapshot": "ok", "taken_at": row["taken_at"], "equity": row["equity"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
