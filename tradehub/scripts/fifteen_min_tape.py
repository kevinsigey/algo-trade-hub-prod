"""Cron entrypoint, every minute: record the 15-minute markets' live read (Kevin, 2026-11-05).

The journal freezes each window once, about 5 minutes in. Testing a rule that waits for the right moment --
"buy the first time the model beats the price by X points" -- needs the model's chance and Kalshi's quotes
at every minute of the window, so this saves one row per open market per run into `fifteen_min_ticks`.
It is the same read the Oil page shows (`oil_live.fifteen_live`). A record only: nothing here trades.
Outcomes come from the journal's settlements for the same window, joined on the close time later.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client

TABLE = "fifteen_min_ticks"
FIELDS = ("series", "ticker", "close_time", "elapsed_min", "prob_up", "yes_bid", "yes_ask", "price", "open_price")


def run(supa, now: datetime, *, read: Callable[[datetime], dict] | None = None) -> dict[str, Any]:
    if read is None:
        from tradehub.oil_live import fifteen_live as read
    try:
        markets = read(now).get("markets") or []
    except Exception as exc:  # noqa: BLE001 -- a missed minute is logged, never retried into a later one
        return {"recorded": 0, "error": f"{type(exc).__name__}: {exc}"[:200]}
    rows = [{**{k: m.get(k) for k in FIELDS}, "at": now.isoformat()} for m in markets if m.get("state") == "live"]
    if rows:
        supa.table(TABLE).insert(rows).execute()
    return {"recorded": len(rows), "skipped": len(markets) - len(rows)}


def main() -> int:
    load_local_env()
    print(json.dumps(run(get_client(), datetime.now(UTC))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
