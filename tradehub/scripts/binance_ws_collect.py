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

Reconnect gaps are lost minutes, and they are said out loud: each one
is logged with its start and end and recorded in the cache payload
(`gaps`) for the shadow's eval to report. The reconnect backoff
carries jitter and resets only after a stream has stayed up for
STABLE_SECONDS -- a connect that dies instantly earns no reset.

Run: python -m tradehub.scripts.binance_ws_collect
"""

from __future__ import annotations

import asyncio
import csv
import fcntl
import io
import json
import os
import random
import urllib.request
import zipfile
from datetime import UTC, datetime, timedelta

import websockets

from tradehub import binance_tape as tape

STREAM = "wss://fstream.binance.com/market/ws/xauusdt@kline_1m"
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


def _restored_klines(path: str) -> dict:
    """The klines a previous run of the collector saved, or {} when the
    cache is missing, unreadable, not a mapping, or holds another
    symbol's tape -- a foreign file must never be relabeled as this
    symbol's by the next flush (CodeRabbit on PR #544)."""
    if not os.path.exists(path):
        return {}
    try:
        payload = json.loads(open(path).read())
        if not isinstance(payload, dict) or payload.get("symbol") != tape.SYMBOL:
            return {}
        return {str(int(ms)): float(close)
                for ms, close in payload.get("klines") or []}
    except (ValueError, OSError, TypeError):
        return {}


STABLE_SECONDS = 60  # a stream that lives this long earns a backoff reset
_GAP_CAP = 200  # recorded reconnect gaps kept in the cache payload


def _restored_gaps(path: str) -> list[dict]:
    """The gap record a previous run saved in the cache payload, or []
    -- the same fail-soft shape as _restored_klines."""
    if not os.path.exists(path):
        return []
    try:
        payload = json.loads(open(path).read())
        if not isinstance(payload, dict) or payload.get("symbol") != tape.SYMBOL:
            return []
        return [g for g in payload.get("gaps") or [] if isinstance(g, dict)]
    except (ValueError, OSError, TypeError):
        return []


def _note_gap(state: dict, start: datetime, end: datetime) -> float:
    """Record one reconnect gap (Claude's cleanup, 2026-11-17): the
    minutes the stream was down are minutes the tape does not have, so
    each gap is logged with its start and end and kept in the state
    (and thus the cache payload) for the shadow's eval to report.
    Returns the gap's minutes."""
    minutes = max(0.0, (end - start).total_seconds() / 60.0)
    gaps = state.setdefault("gaps", [])
    gaps.append({"start": start.isoformat(), "end": end.isoformat()})
    del gaps[:-_GAP_CAP]
    print(f"binance_ws_collect: gap {start.isoformat()} .. "
          f"{end.isoformat()} ({minutes:.1f} min)", flush=True)
    return minutes


def _next_backoff(current: float, *, stable: bool) -> float:
    """The backoff after a drop: reset only when the stream proved
    stable (Claude's cleanup, 2026-11-17) -- a connect that dies
    instantly must not earn the reset the old code granted on connect."""
    return 5 if stable else min(current * 2, 60)


def _sleep_seconds(backoff: float) -> float:
    """Backoff with jitter, so a fleet of drops never resynchronizes."""
    return backoff * random.uniform(0.75, 1.25)


async def run(path: str) -> None:
    state = tape.empty_state()
    state["klines"] = _restored_klines(path)
    state["gaps"] = _restored_gaps(path)
    _seed_from_vision(state, datetime.now(UTC))
    backoff = 5
    down_since: datetime | None = None
    while True:
        connected_at = datetime.now(UTC)
        try:
            async with websockets.connect(STREAM, max_size=2**22) as ws:
                last_flush = asyncio.get_event_loop().time()
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except TimeoutError:
                        raw = None
                    now = datetime.now(UTC)
                    if raw is not None:
                        if down_since is not None:
                            _note_gap(state, down_since, now)
                            down_since = None
                            tape.write_cache(path, state, now)
                        try:
                            tape.apply_kline(state, json.loads(raw), now)
                        except (ValueError, TypeError):
                            pass  # one malformed frame never kills the feed
                    tick = asyncio.get_event_loop().time()
                    if tick - last_flush >= FLUSH_SECONDS:
                        tape.write_cache(path, state, now)
                        last_flush = tick
        except Exception:  # noqa: BLE001 -- reconnect forever; staleness shows in the reader
            if down_since is None:
                down_since = datetime.now(UTC)
            stable = (datetime.now(UTC) - connected_at).total_seconds() >= STABLE_SECONDS
            await asyncio.sleep(_sleep_seconds(backoff))
            backoff = _next_backoff(backoff, stable=stable)


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
