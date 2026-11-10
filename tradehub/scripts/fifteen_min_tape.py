"""Cron entrypoint, every minute: record the 15-minute markets' live read (Kevin, 2026-11-05).

The journal freezes each window once, about 5 minutes in. Testing a rule that waits for the right moment --
"buy the first time the model beats the price by X points" -- needs the model's chance and Kalshi's quotes
at every minute of the window, so this saves one row per open market per run into `fifteen_min_ticks`.
It is the same read the Oil page shows (`oil_live.fifteen_live`). A record only: nothing here trades.
Outcomes come from the journal's settlements for the same window, joined on the close time later.

Since 2026-11-10 each row also carries the contracts on offer at the best ask on each side
(`yes_ask_size`, `no_ask_size`), read from Kalshi's public order book. The 15-minute rule's record
assumes a fill at the quoted ask; these two numbers say how many contracts that ask could have filled.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client

from tradehub.backtest.http import default_get_json
from tradehub.backtest.kalshi_history import KALSHI_PUBLIC_BASE

TABLE = "fifteen_min_ticks"
FIELDS = ("series", "ticker", "close_time", "elapsed_min", "prob_up", "yes_bid", "yes_ask", "price", "open_price")


def _top_size(levels: list | None) -> float | None:
    """Contracts resting at the highest-priced bid of one side's book (levels are [price, size])."""
    if not levels:
        return None
    return float(max(levels, key=lambda level: float(level[0]))[1])


def book_sizes(ticker: str, get_json: Callable[..., Any] = default_get_json) -> tuple[float | None, float | None]:
    """(contracts on offer at the YES ask, contracts on offer at the NO ask).

    Kalshi's book lists bids only. Buying YES lifts the best NO bid, and buying NO lifts the best YES
    bid, so each side's ask size is the other side's top bid size.
    """
    book = get_json(f"{KALSHI_PUBLIC_BASE}/markets/{ticker}/orderbook").get("orderbook_fp") or {}
    return _top_size(book.get("no_dollars")), _top_size(book.get("yes_dollars"))


def run(supa, now: datetime, *, read: Callable[[datetime], dict] | None = None,
        book: Callable[[str], tuple[float | None, float | None]] = book_sizes) -> dict[str, Any]:
    if read is None:
        from tradehub.oil_live import fifteen_live as read
    try:
        markets = read(now).get("markets") or []
    except Exception as exc:  # noqa: BLE001 -- a missed minute is logged, never retried into a later one
        return {"recorded": 0, "error": f"{type(exc).__name__}: {exc}"[:200]}
    rows = [{**{k: m.get(k) for k in FIELDS}, "at": now.isoformat()} for m in markets if m.get("state") == "live"]
    for row in rows:
        try:  # a missing book never costs the minute's quote row
            row["yes_ask_size"], row["no_ask_size"] = book(row["ticker"])
        except Exception:  # noqa: BLE001
            row["yes_ask_size"], row["no_ask_size"] = None, None
    if rows:
        supa.table(TABLE).insert(rows).execute()
    return {"recorded": len(rows), "skipped": len(markets) - len(rows)}


def main() -> int:
    load_local_env()
    print(json.dumps(run(get_client(), datetime.now(UTC))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
