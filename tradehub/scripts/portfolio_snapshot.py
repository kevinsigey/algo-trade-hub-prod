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
from tradehub.portfolio import books
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
    client = supa or get_client()
    out: dict = {}
    code = 0
    for name in books.names():  # one snapshot per book; snapshots are keyed by account number
        try:
            row = take_snapshot(client, now, book_name=name)
        except Exception as exc:  # noqa: BLE001 -- one book failing never stops the other
            out[name] = {"snapshot": "failed", "error": str(exc)}
            code = 1
            continue
        out[name] = ({"snapshot": "skipped", "reason": "paper account not connected"} if row is None
                     else {"snapshot": "ok", "taken_at": row["taken_at"], "equity": row["equity"]})
    print(json.dumps(out))
    return code


if __name__ == "__main__":
    sys.exit(main())
