"""Step 17 runner: run the anchor replay and write the report where the
research artifacts live ($TRADEHUB_RESEARCH_DIR/anchor_replay.json).

    python -m tradehub.scripts.anchor_replay_run

Reads the settled daily rows (journal_forecasts + journal_settlements),
the 15-minute strikes (fifteen_rule_decisions) and Hyperliquid 1-minute
candles for the two coins, then scores the preregistered replay in
tradehub/research/anchor_replay.py. Read-only; the verdict in the report
is the deliverable.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from tradehub.core.supabase_client import get_client
from tradehub.research.anchor_replay import SERIES, build_report


def _all(client, table: str, columns: str, **filters) -> list[dict]:
    rows, start = [], 0
    while True:
        q = client.table(table).select(columns)
        for key, value in filters.items():
            q = q.eq(key, value)
        page = q.range(start, start + 999).execute().data or []
        rows.extend(page)
        if len(page) < 1000:
            return rows
        start += 1000


def main() -> None:
    client = get_client()
    outcomes = {r["target"]: r["outcome"]
                for r in _all(client, "journal_settlements", "target,outcome")}
    rows_by_series, strikes_by_series, tape_by_series = {}, {}, {}
    for forecaster, spec in SERIES.items():
        raw = _all(client, "journal_forecasts",
                   "target,probability,market_prob,payload,frozen_at",
                   forecaster=forecaster, forecaster_version=spec["version"])
        rows = [{"target": r["target"], "probability": r["probability"],
                 "market_prob": r["market_prob"], "payload": r["payload"],
                 "frozen_at": datetime.fromisoformat(r["frozen_at"]),
                 "outcome": outcomes[r["target"]]}
                for r in raw if r["target"] in outcomes]
        rows_by_series[forecaster] = rows
        decisions = _all(client, "fifteen_rule_decisions", "window_open,ticker",
                         series=spec["fifteen_series"])
        by_open: dict[datetime, str] = {}
        for d in decisions:
            by_open.setdefault(datetime.fromisoformat(d["window_open"]), d["ticker"])
        # Only the windows that are the latest strike for some row's freeze
        # need their strike read off the market (the decisions table stores
        # the ticker, not the strike).
        from bisect import bisect_right

        from tradehub.core.kalshi_feed import fetch_market
        from tradehub.markets import parse_market
        opens = sorted(by_open)
        needed = {opens[bisect_right(opens, r["frozen_at"]) - 1]
                  for r in rows if bisect_right(opens, r["frozen_at"]) > 0}
        strikes = []
        for opened in sorted(needed):
            raw = fetch_market(by_open[opened]) or {}
            market = parse_market(raw.get("market", raw))
            if market.floor_strike is not None:
                strikes.append((opened, float(market.floor_strike)))
        strikes_by_series[forecaster] = strikes
        # The perp leg rides the stored tape: fifteen_window_offsets carries
        # the perp read at every offset minute of every window (prereg
        # amendment 2 -- Hyperliquid no longer serves the era's candles).
        offsets = _all(client, "fifteen_window_offsets", "close_time,offset_min,price",
                       series=spec["fifteen_series"])
        points: dict[datetime, float] = {}
        for o in offsets:
            instant = (datetime.fromisoformat(o["close_time"]) - timedelta(minutes=15)
                       + timedelta(minutes=o["offset_min"]))
            if o["price"] is not None:
                points.setdefault(instant, float(o["price"]))
        tape_by_series[forecaster] = sorted(points.items())
    report = build_report(rows_by_series, strikes_by_series, tape_by_series)
    report["run_at"] = datetime.now().astimezone().isoformat()
    out = Path(os.environ.get("TRADEHUB_RESEARCH_DIR", "/cache/research")) / "anchor_replay.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
