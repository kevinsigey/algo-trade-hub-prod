"""Step A0 runner (docs/plan-2026-11-12-fifteen-rule-v4.md): pull settled
15-minute markets and their 1-minute candles from Kalshi's public history,
pull the underlyings' 1-minute tapes from Hyperliquid, replay the live
forecaster (tradehub/backtest/fifteen_replay.py) and write the rows as
JSONL the Step A study can consume straight away.

    python -m tradehub.scripts.fifteen_replay_backfill \
        --out /cache/research --from 2026-11-06 --to 2026-11-12

Read-only against both APIs: no orders, no writes anywhere but --out.
Resumable: a `<out>/.done` file lists finished tickers; a re-run skips
them. The replay goes to a file because the fifteen_replay_offsets table
needs Kevin's go through Claude (the SQL is in the PR, unapplied).

Coverage limit: Hyperliquid serves only the last ~3.5 days of 1-minute
candles, so markets older than the tape's first candle replay with
prob_up None (quotes and outcomes only). The run prints a tape_coverage
line naming the tape's actual span; a range far outside it is wasted
Kalshi pulls, not a deeper study.

--golden <stored.json> additionally compares the replay for the pulled
range against exported fifteen_window_offsets rows and prints the
golden-check verdict (the three-part gate of plan Step A0 item 4b:
tape probability fidelity per entry minute, tick material agreement,
quotes and sides).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tradehub.backtest.fifteen_replay import golden_compare, replay_window
from tradehub.backtest.kalshi_history import KalshiHistoryClient
from tradehub.data.hyperliquid import hyperliquid_candles
from tradehub.engines.fifteen_min import SERIES_COINS, WINDOW_MINUTES

SERIES = ["KXNATGAS15M", "KXWTI15M", "KXBRENT15M", "KXGOLD15M", "KXSILVER15M", "KXCOPPER15M"]
TAPE_PAD_BEFORE = timedelta(minutes=200)
TAPE_PAD_AFTER = timedelta(minutes=70)
TAPE_CHUNK = timedelta(days=3)


def _parse_day(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _market_close(market: dict) -> datetime | None:
    raw = market.get("close_time")
    if not raw:
        return None
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def _outcome(market: dict) -> int | None:
    result = str(market.get("result") or "").lower()
    return 1 if result == "yes" else 0 if result == "no" else None


def _tape(coin: str, start: datetime, end: datetime) -> list:
    """The coin's 1-minute closes over [start, end), pulled in chunks
    (one candleSnapshot call caps out well under a hundred days)."""
    out: list = []
    t = start
    while t < end:
        nxt = min(end, t + TAPE_CHUNK)
        out.extend(hyperliquid_candles(coin, t, nxt))
        t = nxt
    return sorted(set(out))


def write_tapes(tapes: dict[str, list], tape_out: Path) -> list[str]:
    """Dump each coin's 1-minute tape as one JSON file per UTC day
    (<tape_out>/<coin>-<YYYY-MM-DD>.json, [[iso, close], ...]). This is
    the archive that outlives Hyperliquid's ~3.5-day 1-minute retention:
    a daily run (fifteen_replay_archive) rewrites the trailing days
    while they are still served, so the raw tape -- not just today's
    replay of it -- is ours to re-run future engines against. Files are
    written atomically (tmp + rename); a day file is complete only once
    the day has ended, and later runs keep rewriting it until then."""
    tape_out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for coin, tape in sorted(tapes.items()):
        by_day: dict[str, list] = {}
        for t, close in tape:
            by_day.setdefault(t.date().isoformat(), []).append(
                [t.isoformat(), close])
        safe = coin.replace(":", "_").replace("/", "_")
        for day, rows in sorted(by_day.items()):
            path = tape_out / f"{safe}-{day}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(rows))
            tmp.rename(path)
            written.append(str(path))
    return written


def run(out_dir: Path, start: datetime, end: datetime, *,
        series: list[str], sleep_s: float = 0.05,
        tape_out: Path | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "fifteen_replay_offsets.jsonl"
    done_path = out_dir / ".done"
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    client = KalshiHistoryClient()
    stats = {"markets": 0, "skipped_done": 0, "no_outcome": 0, "rows": 0}
    tapes: dict[str, list] = {}
    with rows_path.open("a") as rows_f, done_path.open("a") as done_f:
        for s in series:
            markets = [m for m in client.settled_markets(s)
                       if (c := _market_close(m)) is not None and start <= c < end
                       and m.get("ticker")]
            markets.sort(key=lambda m: _market_close(m) or start)
            coin = SERIES_COINS[s]
            if coin not in tapes:
                tapes[coin] = _tape(coin, start - TAPE_PAD_BEFORE, end + TAPE_PAD_AFTER)
                span = tapes[coin]
                print(json.dumps({"tape_coverage": {
                    "coin": coin,
                    "first": span[0][0].isoformat() if span else None,
                    "last": span[-1][0].isoformat() if span else None,
                    "candles": len(span)}}), flush=True)
            tape = tapes[coin]
            for m in markets:
                ticker = m["ticker"]
                stats["markets"] += 1
                if ticker in done:
                    stats["skipped_done"] += 1
                    continue
                outcome = _outcome(m)
                if outcome is None:
                    stats["no_outcome"] += 1
                    done_f.write(ticker + "\n")
                    continue
                close_time = _market_close(m)
                window_open = close_time - timedelta(minutes=WINDOW_MINUTES)
                candles = client.merged_candles(
                    ticker, window_open - timedelta(minutes=1),
                    close_time + timedelta(minutes=2),
                    market_settled_at=close_time + timedelta(minutes=1),
                    period_minutes=1, series_ticker=s)
                rows = replay_window(
                    series=s, target=f"kalshi:{ticker}", ticker=ticker,
                    close_time=close_time, outcome=outcome, tape=tape, candles=candles)
                for r in rows:
                    rows_f.write(json.dumps(r) + "\n")
                stats["rows"] += len(rows)
                done_f.write(ticker + "\n")
                done_f.flush()
                if sleep_s:
                    time.sleep(sleep_s)
                if stats["markets"] % 500 == 0:
                    print(json.dumps({"progress": stats}), flush=True)
    if tape_out is not None:
        written = write_tapes(tapes, tape_out)
        print(json.dumps({"tapes_written": len(written)}), flush=True)
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="/cache/research")
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--series", action="append", choices=SERIES)
    ap.add_argument("--golden", help="path to exported fifteen_window_offsets rows (JSON)")
    ap.add_argument("--tape-out", help="also dump the underlyings' 1-minute tapes, one JSON file per coin per day")
    args = ap.parse_args(argv)
    start, end = _parse_day(args.start), _parse_day(args.end) + timedelta(days=1)
    stats = run(Path(args.out), start, end, series=args.series or SERIES,
                tape_out=Path(args.tape_out) if args.tape_out else None)
    print(json.dumps({"backfill": stats}))
    if args.golden:
        replay_rows = [json.loads(line) for line in
                       (Path(args.out) / "fifteen_replay_offsets.jsonl").read_text().splitlines()
                       if line.strip()]
        stored = json.loads(Path(args.golden).read_text())
        print(json.dumps({"golden": golden_compare(replay_rows, stored)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
