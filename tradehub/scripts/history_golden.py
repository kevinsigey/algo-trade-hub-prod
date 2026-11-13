"""A0b golden check: Binance Vision tape vs Hyperliquid on an overlap.

    python -m tradehub.scripts.history_golden --cache /cache/research/history \
        --from 2026-11-09T16:00 --to 2026-11-12

Per series: 1-minute return correlation and median level gap (bps); the
replay probability (read_window, offsets 1-14) on each tape, compared
with the A0 (a) within-1e-5 and (b) within-0.01 bars (the Hyperliquid
replay stands in for the forward record, which A0 matched at 97.9% /
99.75%); and the share of windows whose synthetic outcome on each tape
equals Kalshi's settled result. Read-only; writes only under --cache.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tradehub.backtest import history_tapes as ht
from tradehub.backtest.kalshi_history import KalshiHistoryClient
from tradehub.engines.fifteen_min import SERIES_COINS
from tradehub.journal.forecasters.fifteen_min import read_window
from tradehub.scripts.fifteen_replay_backfill import _market_close, _outcome, _tape


def series_golden(binance: list, hl: list, results: dict) -> dict:
    """results: {close_time: 0/1} from Kalshi."""
    tapes = {"binance": dict(binance), "hl": dict(hl)}
    agree = {k: [0, 0] for k in tapes}
    diffs = []
    for ct, y in results.items():
        op = ct - timedelta(minutes=15)
        for k, d in tapes.items():
            a, z = d.get(op - timedelta(minutes=1)), d.get(ct - timedelta(minutes=1))
            if a and z:
                agree[k][1] += 1
                agree[k][0] += int((z >= a) == bool(y))
        for m in range(1, 15):
            rb = read_window(ct, binance, op + timedelta(minutes=m))
            rh = read_window(ct, hl, op + timedelta(minutes=m))
            if rb and rh:
                diffs.append(abs(rb["prob_up"] - rh["prob_up"]))
    n = len(diffs)
    return {**ht.tape_compare(binance, hl), "windows": len(results), "prob_rows": n,
            "a_within_1e5": sum(d <= 1e-5 for d in diffs) / n if n else None,
            "b_within_0_01": sum(d <= 0.01 for d in diffs) / n if n else None,
            "median_prob_diff": sorted(diffs)[n // 2] if n else None,
            "outcome_agree": {k: (v[0] / v[1] if v[1] else None) for k, v in agree.items()}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", default="/cache/research/history")
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    args = ap.parse_args(argv)
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    pad = timedelta(minutes=200)
    client, out = KalshiHistoryClient(), {}
    for series, symbol in ht.BINANCE_SYMBOLS.items():
        binance = ht.binance_tape(symbol, start - pad, end, Path(args.cache))
        hl = _tape(SERIES_COINS[series], start - pad, end)
        results = {c: _outcome(m) for m in client.settled_markets(series)
                   if (c := _market_close(m)) and start <= c < end and _outcome(m) is not None}
        out[series] = series_golden(binance, hl, results)
        print(series, json.dumps(out[series]), flush=True)
    passed = all(r["a_within_1e5"] and r["a_within_1e5"] >= 0.95 and r["b_within_0_01"] >= 0.99
                 for r in out.values())
    print(json.dumps({"golden_pass": passed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
