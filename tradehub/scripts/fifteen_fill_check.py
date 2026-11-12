"""One-off read: the gas fill check (backlog model item 1, Nov 12).

Marks every settled gated natural-gas trade in fifteen_rule_decisions
with the contracts on offer at its ask (fifteen_min_ticks, PR #472 data)
and prints how many would have filled -- at 1 contract and at the demo
runner's launch size. Read-only; nothing is written anywhere.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from tradehub import fifteen_tracking
from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.fifteen_fill_check import SERIES, mark_trades, summarize
from tradehub.journal import store


def run(supa, now: datetime) -> dict:
    decisions = store.select_all(
        supa, fifteen_tracking.rule.DECISIONS_TABLE,
        lambda q: q.eq("series", SERIES).eq("action", "buy"),
        ("close_time",))
    settled = [d for d in decisions if d.get("pnl") is not None]
    ticks = fifteen_tracking.fetch_ticks(
        supa, SERIES, [str(d["close_time"]) for d in settled])
    marked = mark_trades(settled, ticks)
    return {"as_of": now.isoformat(), **summarize(marked),
            "note": "Depth exists only since PR #472 (2026-11-11); earlier "
                    "trades count as without_depth. would_fill_sized uses "
                    "the demo launch size: 1% of $500 at the frozen quote."}


def main() -> int:
    load_local_env()
    print(json.dumps(run(get_client(), datetime.now(UTC)), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
