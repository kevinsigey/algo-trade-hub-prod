"""Thesis tracker grader: grade every due forecast card from Alpaca
daily bars, refresh the Claim A/C falsifier states, and stamp
tracker_health (design docs/superpowers/specs/
2026-11-16-thesis-tracker-design.md, PR 4).

Run by the deploy crontab daily after the close:

    python -m tradehub.scripts.thesis_grade_run

Daily (not just weekdays) on purpose: the sizing fork reads the
health stamp's freshness (< 26h), so a weekday-only cadence would
drop the event-lab unit to the $1,500 fallback every Monday morning
even with the grader healthy. A weekend run grades nothing new and
re-stamps.

Claim C's fire nets are wired from trade_links P&L in PR 5 (the
placement writes do not exist yet); until then the run passes an
empty list and Claim C's progress reads zero fires.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime

import requests

from tradehub.core.supabase_client import get_client
from tradehub.portfolio import alpaca_paper
from tradehub.tracker import grader
from tradehub.tracker.grading import ET


def daily_closes(symbol: str, start: date, end: date, *,
                 session=requests) -> list[tuple[date, float]]:
    """(session date, close) pairs from Alpaca daily bars, the same
    host/keys/feed as the level watcher's feed. adjustment=all so a
    split or a SPY dividend inside a grading window does not print as
    a return."""
    params = {"timeframe": "1Day",
              "start": datetime(start.year, start.month, start.day,
                                tzinfo=UTC).isoformat(),
              "end": datetime(end.year, end.month, end.day, tzinfo=UTC)
              .isoformat(),
              "feed": "iex", "adjustment": "all", "limit": 10000,
              "sort": "asc"}
    out: list[tuple[date, float]] = []
    while True:
        resp = session.get(
            alpaca_paper.DATA_BASE + f"/v2/stocks/{symbol}/bars",
            params=params, headers=alpaca_paper._headers("main"),
            timeout=15)
        resp.raise_for_status()
        body = resp.json() or {}
        for b in body.get("bars") or []:
            day = datetime.fromisoformat(
                str(b["t"]).replace("Z", "+00:00")).astimezone(ET).date()
            out.append((day, float(b["c"])))
        token = body.get("next_page_token")
        if not token:
            return out
        params["page_token"] = token


def main() -> None:
    client = get_client()
    now = datetime.now(UTC)
    try:
        summary = grader.grade_run(client, daily_closes, now,
                                   fire_nets=())
    except Exception as exc:  # noqa: BLE001 -- the stamp is the alarm
        try:
            grader.stamp_health(client, now, ok=False)
        except Exception:  # noqa: BLE001
            pass
        print(f"thesis_grade_run: FAILED {type(exc).__name__}: {exc}")
        sys.exit(1)
    print(json.dumps({"thesis_grade_run": summary}, default=str))


if __name__ == "__main__":
    main()
