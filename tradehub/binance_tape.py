"""The Binance XAUUSDT 1-minute tape, cached from the live stream.

Why this exists (2026-11-16): Binance's REST hosts refuse the hub's
VPS egress (HTTP 451; the numbered mirrors redirect to the block page),
so the Binance-tape gold shadow (tradehub/fifteen_binance.py) cannot
pull klines the way its preregistration first assumed. The futures
WEBSOCKET host answers, so a small collector
(scripts/binance_ws_collect.py) subscribes to the same XAUUSDT
1-minute kline stream and keeps the rolling tape in a cache file;
this module is the cache's reader/writer contract. Same tape, same
(open time -> close) convention as the REST klines and the replay's
Binance tape -- only the transport changed (preregistration amendment,
2026-11-16, Kevin's pick).

The reader is deliberately strict: a missing, corrupt, or stale cache
RAISES, so the shadow's fail-soft runner reports a tape outage instead
of recording reads off dead data -- an outage never masquerades as a
read, the same doctrine as the REST fetch it replaces.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

SYMBOL = "XAUUSDT"
DEFAULT_PATH = "/cache/binance/xauusdt-1m.json"
RETAIN = timedelta(hours=48)          # the shadow needs ~3h; keep 2 days
MAX_STALE = timedelta(minutes=10)     # reader: older than this = outage


def cache_path() -> str:
    return os.environ.get("BINANCE_TAPE_CACHE", DEFAULT_PATH)


def empty_state() -> dict:
    return {"symbol": SYMBOL, "klines": {}}  # klines: open_ms -> close


def apply_kline(state: dict, msg: dict, now: datetime) -> bool:
    """Fold one Binance kline stream message into the state. Returns
    True when the tape changed. Only FINAL candles land (Binance marks
    them k.x = true): a provisional close is not a close -- if the
    connection dropped mid-minute, the last provisional update would
    otherwise sit in the cache indefinitely and read_window would
    accept it as that minute's completed close. Malformed frames are
    ignored (one bad frame never kills the feed)."""
    try:
        k = msg["k"]
        if not k.get("x"):
            return False
        open_ms = int(k["t"])
        close = float(k["c"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    key = str(open_ms)
    if state["klines"].get(key) == close:
        return False
    state["klines"][key] = close
    cutoff = int((now - RETAIN).timestamp() * 1000)
    for old in [m for m in state["klines"] if int(m) < cutoff]:
        del state["klines"][old]
    return True


def parse_vision_rows(rows) -> list[tuple[int, float]]:
    """(open_ms, close) pairs from Binance Vision daily-klines CSV rows
    (the archive of this same tape; used to seed the cache at collector
    start so a cold start is hours shorter). Header rows and malformed
    lines are skipped."""
    out = []
    for r in rows:
        try:
            out.append((int(r[0]), float(r[4])))
        except (IndexError, TypeError, ValueError):
            continue
    return out


def seed(state: dict, pairs) -> int:
    """Merge (open_ms, close) pairs into the state; returns how many
    were new. Streamed values always win over seeded ones for the same
    minute (they are the same tape, but the stream is the live edge)."""
    added = 0
    for open_ms, close in pairs:
        key = str(open_ms)
        if key not in state["klines"]:
            state["klines"][key] = close
            added += 1
    return added


def write_cache(path: str, state: dict, now: datetime) -> None:
    """Atomic write (tmp + replace), the house cache pattern. The
    collector's reconnect-gap record rides along when the state
    carries one (Claude's cleanup, 2026-11-17)."""
    payload = {"symbol": state["symbol"],
               "written_at": now.isoformat(),
               "klines": [[int(ms), state["klines"][ms]]
                          for ms in sorted(state["klines"], key=int)],
               "gaps": list(state.get("gaps") or [])}
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(json.dumps(payload))
    os.replace(tmp, path)


def read_gaps(*, path: str | None = None) -> list[dict]:
    """The collector's recorded reconnect gaps [{start, end} ISO], or
    [] when the cache is missing/corrupt or carries none -- a missing
    gap record reads as no recorded gaps, never as an error."""
    p = path or cache_path()
    try:
        payload = json.loads(open(p).read())
        gaps = payload.get("gaps") if isinstance(payload, dict) else None
        return [g for g in gaps if isinstance(g, dict)] if gaps else []
    except (ValueError, OSError, TypeError):
        return []


def read_cached_klines(symbol: str, start: datetime, end: datetime, *,
                       path: str | None = None,
                       now: datetime | None = None,
                       max_stale: timedelta = MAX_STALE
                       ) -> list[tuple[datetime, float]]:
    """[(minute_start_utc, close)] over [start, end) from the cache --
    the same shape and range convention as
    fifteen_binance.binance_klines. Raises RuntimeError on a missing,
    corrupt, wrong-symbol, or stale cache: the caller (the shadow's
    record pass) treats a raise as a tape outage and writes nothing."""
    if symbol != SYMBOL:
        raise RuntimeError(f"the tape cache holds {SYMBOL}, not {symbol}")
    p = path or cache_path()
    try:
        with open(p) as fh:
            payload = json.load(fh)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"binance tape cache unavailable: {exc}") from exc
    if payload.get("symbol") != SYMBOL:
        raise RuntimeError("binance tape cache holds the wrong symbol")
    rows = payload.get("klines") or []
    if not rows:
        raise RuntimeError("binance tape cache is empty")
    newest = datetime.fromtimestamp(int(rows[-1][0]) / 1000, UTC)
    if newest < end - max_stale:
        raise RuntimeError(
            f"binance tape cache is stale: newest candle {newest.isoformat()} "
            f"is more than {int(max_stale.total_seconds() // 60)} minutes "
            f"behind the requested end {end.isoformat()}")
    return [(datetime.fromtimestamp(int(ms) / 1000, UTC), float(close))
            for ms, close in rows
            if start <= datetime.fromtimestamp(int(ms) / 1000, UTC) < end]
