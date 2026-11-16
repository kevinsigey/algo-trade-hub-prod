"""The Binance tape collector: one futures websocket, cached klines only.

Mirrors the Hormuz AIS consumer's shape (geo/ais_consumer.py):
subscribe, keep the rolling state in memory, write it to the cache
file on an interval, reconnect forever with backoff. The raw stream
is never stored -- only the (open time -> close) tape the shadow
reads. Single instance via an flock in the cache directory; the
deploy crontab watcher restarts it after container recreates.

At start it seeds the tape from Binance Vision's daily archive (the
published archive of this same feed) for the two prior UTC days, so a
cold start begins with history instead of an empty cache; the stream
then owns every minute from connect time forward. Seeding is
fail-soft: an unreachable archive never blocks the stream.

Run: python -m tradehub.scripts.binance_ws_collect
"""

from __future__ import annotations

import asyncio
import csv
import fcntl
import io
import json
import os
import urllib.request
import zipfile
from datetime import UTC, datetime, timedelta

import websockets

from tradehub import binance_tape as tape

STREAM = "wss://fstream.binance.com/ws/xauusdt@kline_1m"
VISION_DAILY = ("https://data.binance.vision/data/futures/um/daily/"
                "klines/XAUUSDT/1m/XAUUSDT-1m-{day}.zip")
FLUSH_SECONDS = 20


def _seed_from_vision(state: dict, now: datetime) -> None:
    for days_ago in (1, 2):
        day = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        try:
            with urllib.request.urlopen(  # noqa: S310 - fixed Binance host
                    VISION_DAILY.format(day=day), timeout=30) as resp:
                blob = resp.read()
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                text = zf.read(zf.namelist()[0]).decode()
            tape.seed(state, tape.parse_vision_rows(csv.reader(io.StringIO(text))))
        except Exception:  # noqa: BLE001 -- seeding never blocks the stream
            continue


async def run(path: str) -> None:
    state = tape.empty_state()
    if os.path.exists(path):
        try:
            payload = json.loads(open(path).read())
            state["klines"] = {str(int(ms)): float(close)
                                for ms, close in payload.get("klines") or []}
        except (ValueError, OSError, TypeError):
            pass
    _seed_from_vision(state, datetime.now(UTC))
    backoff = 5
    while True:
        try:
            async with websockets.connect(STREAM, max_size=2**22) as ws:
                backoff = 5
                last_flush = asyncio.get_event_loop().time()
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except TimeoutError:
                        raw = None
                    now = datetime.now(UTC)
                    if raw is not None:
                        try:
                            tape.apply_kline(state, json.loads(raw), now)
                        except (ValueError, TypeError):
                            pass  # one malformed frame never kills the feed
                    tick = asyncio.get_event_loop().time()
                    if tick - last_flush >= FLUSH_SECONDS:
                        tape.write_cache(path, state, now)
                        last_flush = tick
        except Exception:  # noqa: BLE001 -- reconnect forever; staleness shows in the reader
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


def main() -> int:
    path = tape.cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = open(os.path.join(os.path.dirname(path), "binance-ws.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0  # another collector already holds the tape
    asyncio.run(run(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
