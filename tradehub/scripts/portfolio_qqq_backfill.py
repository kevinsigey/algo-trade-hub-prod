"""One-off backfill: fill portfolio_snapshots.qqq_price for rows written
before the column existed (migration 20261112000003).

Run inside the production container after that migration is applied:

    docker exec stack-tradehub-1 python -m tradehub.scripts.portfolio_qqq_backfill

Each snapshot gets the close of the last QQQ hourly bar that had FULLY
closed at the snapshot's taken_at (bar start + 1h <= taken_at) — no
look-ahead: the value was knowable when the snapshot was written. Rows
with no such bar (before the first bar in range) stay NULL. Idempotent:
only NULL rows are read or written, so a re-run is a no-op once filled.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.portfolio.alpaca_paper import stock_bars
from tradehub.portfolio.service import SNAPSHOTS


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assign_qqq_prices(snapshots: list[dict], bars: list[dict]) -> dict[int, float]:
    """Map snapshot index -> QQQ price: the close of the last hourly bar
    fully closed at the snapshot time. Bars are Alpaca 1Hour bars
    ({t, c}); snapshots carry taken_at. Indexes with no closed bar yet
    are absent from the result."""
    closed = sorted((_ts(b["t"]) + timedelta(hours=1), float(b["c"])) for b in bars)
    out: dict[int, float] = {}
    j = -1
    for i, snap in sorted(enumerate(snapshots), key=lambda p: _ts(p[1]["taken_at"])):
        at = _ts(snap["taken_at"])
        while j + 1 < len(closed) and closed[j + 1][0] <= at:
            j += 1
        if j >= 0:
            out[i] = closed[j][1]
    return out


def read_unfilled(client, page: int = 1000) -> list[dict]:
    """Every snapshot still missing qqq_price, paged -- PostgREST caps a
    read at 1,000 rows (Claude's #514 review)."""
    rows: list[dict] = []
    offset = 0
    while True:
        batch = (client.table(SNAPSHOTS).select("account_number,taken_at")
                 .is_("qqq_price", "null").order("taken_at")
                 .range(offset, offset + page - 1).execute().data) or []
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def main(supa=None) -> int:
    load_local_env()
    client = supa or get_client()
    rows = read_unfilled(client)
    if not rows:
        print(json.dumps({"backfill": "noop", "reason": "no NULL rows"}))
        return 0
    # Ten days back, not two: the last bar fully closed before the
    # earliest snapshot can sit across a weekend or a holiday stretch
    # (a Monday-morning snapshot's bar is Friday's), and a window that
    # starts after it leaves the row NULL on every re-run (CodeRabbit).
    start = (_ts(rows[0]["taken_at"]) - timedelta(days=10)).astimezone(UTC).isoformat()
    end = (_ts(rows[-1]["taken_at"]) + timedelta(days=1)).astimezone(UTC).isoformat()
    bars = stock_bars("QQQ", "1Hour", start, end)
    assigned = assign_qqq_prices(rows, bars)
    updated = 0
    for i, price in assigned.items():
        (client.table(SNAPSHOTS).update({"qqq_price": price})
         .eq("account_number", rows[i]["account_number"])
         .eq("taken_at", rows[i]["taken_at"]).execute())
        updated += 1
    print(json.dumps({"backfill": "done", "null_rows": len(rows), "bars": len(bars),
                      "updated": updated, "left_null": len(rows) - updated}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
