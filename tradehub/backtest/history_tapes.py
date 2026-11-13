"""Step A0b (Kevin's source choice, Nov 13): 1-minute underlying tapes
beyond Hyperliquid's ~3.5-day retention, in the replay's tape shape
[(minute_start_utc, close), ...] so `fifteen_replay.replay_window` and
`read_window` take them unchanged.

- Binance Vision USD-M perp klines, for the Kalshi era (Jul 31, 2026 on).
  Terms: CC BY-NC-SA 4.0 plus the Binance Vision Dataset Terms (Aug 26,
  2026), which limit backtesting to "purely personal non-production
  research" (s4.1) and bar "live proprietary trading execution" (s4.2).
  Kevin chose the source with those terms in view.
- HistData.com M1 ASCII, for long model-only history on gold, silver,
  WTI and Brent (no gas, no copper). Timestamps are EST with NO daylight
  saving, i.e. a fixed UTC-5, converted here explicitly. HistData has no
  terms-of-use page; its FAQ disclaims any warranty.

Polite by construction: every downloaded file is cached under
`cache_dir` and never fetched twice, pulls are sequential, and HTTP goes
through `backtest.http` (bounded retries, backoff on 429/5xx).
"""

from __future__ import annotations

import csv
import io
import math
import re
import statistics
import time
import zipfile
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import requests

from tradehub.backtest import http

BINANCE_SYMBOLS = {"KXGOLD15M": "XAUUSDT", "KXSILVER15M": "XAGUSDT", "KXWTI15M": "CLUSDT",
                   "KXBRENT15M": "BZUSDT", "KXNATGAS15M": "NATGASUSDT",
                   "KXCOPPER15M": "COPPERUSDT"}
# First daily 1-minute kline file on data.binance.vision (S3 listing, Nov 13).
BINANCE_FIRST_DAY = {"XAUUSDT": date(2025, 12, 11), "XAGUSDT": date(2026, 1, 7),
                     "CLUSDT": date(2026, 4, 1), "BZUSDT": date(2026, 4, 1),
                     "NATGASUSDT": date(2026, 4, 1), "COPPERUSDT": date(2026, 3, 6)}
HISTDATA_SYMBOLS = {"KXGOLD15M": "XAUUSD", "KXSILVER15M": "XAGUSD",
                    "KXWTI15M": "WTIUSD", "KXBRENT15M": "BCOUSD"}
HISTDATA_TZ = timezone(timedelta(hours=-5))  # EST, no DST, all year
BINANCE_URL = "https://data.binance.vision/data/futures/um/daily/klines/{s}/1m/{s}-1m-{d}.zip"
HISTDATA_PAGE = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{p}/{y}"
HISTDATA_GET = "https://www.histdata.com/get.php"
PAUSE_S = 0.5  # between network pulls; cached reads never sleep


def _zip_text(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith((".csv", ".txt")))
        return z.read(name).decode()


def parse_binance_klines(raw: bytes) -> list[tuple[datetime, float]]:
    """A Binance Vision kline zip -> [(open_time_utc, close)]. Newer files
    carry a header row, older ones don't; non-numeric rows are skipped."""
    out = []
    for row in csv.reader(io.StringIO(_zip_text(raw))):
        if row and row[0].isdigit():
            out.append((datetime.fromtimestamp(int(row[0]) / 1000, UTC), float(row[4])))
    return out


def parse_histdata(raw: bytes) -> list[tuple[datetime, float]]:
    """A HistData M1 ASCII zip ('YYYYMMDD HHMMSS;O;H;L;C;V', EST no DST)
    -> [(minute_start_utc, close)]."""
    out = []
    for line in _zip_text(raw).splitlines():
        parts = line.strip().split(";")
        if len(parts) < 5:
            continue
        t = datetime.strptime(parts[0], "%Y%m%d %H%M%S").replace(tzinfo=HISTDATA_TZ)
        out.append((t.astimezone(UTC), float(parts[4])))
    return out


def _cached(path: Path, fetch) -> bytes | None:
    """The file at `path`, fetching it once if absent. A fetch returning
    None (not published) is not cached, so a later run retries it."""
    if path.exists():
        return path.read_bytes()
    raw = fetch()
    if raw is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.rename(path)
    time.sleep(PAUSE_S)
    return raw


def _binance_fetch(url: str) -> bytes | None:
    try:
        return http._get(url, None, None).content
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 404:
            return None  # day not published yet (files lag about a day)
        raise


def binance_tape(symbol: str, start: datetime, end: datetime,
                 cache_dir: Path) -> list[tuple[datetime, float]]:
    """1-minute closes in [start, end) from the daily kline files."""
    out: list[tuple[datetime, float]] = []
    d = max(start.date(), BINANCE_FIRST_DAY.get(symbol, start.date()))
    while d <= (end - timedelta(microseconds=1)).date():
        url = BINANCE_URL.format(s=symbol, d=d.isoformat())
        raw = _cached(cache_dir / "binance" / symbol / f"{d.isoformat()}.zip",
                      lambda u=url: _binance_fetch(u))
        if raw is not None:
            out.extend(r for r in parse_binance_klines(raw) if start <= r[0] < end)
        d += timedelta(days=1)
    return sorted(out)


def _histdata_fetch(pair: str, year: int, month: int | None) -> bytes | None:
    page_url = HISTDATA_PAGE.format(p=pair.lower(), y=year) + (f"/{month}" if month else "")
    page = requests.get(page_url, timeout=30).text
    tk = re.search(r'id="tk" value="([0-9a-f]+)"', page)
    if not tk:
        return None
    period = f"{year}{month:02d}" if month else str(year)
    resp = requests.post(HISTDATA_GET, timeout=60, headers={"Referer": page_url},
                         data={"tk": tk.group(1), "date": str(year), "datemonth": period,
                               "platform": "ASCII", "timeframe": "M1", "fxpair": pair})
    resp.raise_for_status()
    return resp.content if resp.content[:2] == b"PK" else None


def histdata_tape(pair: str, year: int, month: int | None,
                  cache_dir: Path) -> list[tuple[datetime, float]]:
    """One HistData file's 1-minute closes. Past years come as one yearly
    file (month None); the current year only as monthly files."""
    name = f"{year}" + (f"-{month:02d}" if month else "")
    raw = _cached(cache_dir / "histdata" / pair / f"{name}.zip",
                  lambda: _histdata_fetch(pair, year, month))
    return parse_histdata(raw) if raw is not None else []


def tape_compare(a: list, b: list) -> dict:
    """Two tapes on their common minutes: the correlation of 1-minute log
    returns (both sides need the previous minute too) and the median
    absolute level gap in bps."""
    da, db = dict(a), dict(b)
    common = sorted(set(da) & set(db))
    gaps = [abs(da[t] / db[t] - 1) * 1e4 for t in common]
    ra, rb = [], []
    for t in common:
        p = t - timedelta(minutes=1)
        if p in da and p in db:
            ra.append(math.log(da[t] / da[p]))
            rb.append(math.log(db[t] / db[p]))
    corr = statistics.correlation(ra, rb) if len(ra) > 2 else None
    return {"common_minutes": len(common), "return_pairs": len(ra), "return_corr": corr,
            "median_gap_bps": statistics.median(gaps) if gaps else None}


def synthetic_windows(tape: list) -> dict[datetime, int]:
    """{window close: outcome} for every :00/:15/:30/:45 window whose open
    and settle minutes are both on the tape, by the contract's rule: YES iff
    the close of the minute ending at the window's end is at least the
    close of the minute ending at its open (ties are YES)."""
    d = dict(tape)
    out = {}
    for t in d:
        if t.minute % 15 == 14:  # the settle minute of the window closing at t + 1m
            close = t + timedelta(minutes=1)
            opened = d.get(close - timedelta(minutes=16))
            if opened is not None:
                out[close] = int(d[t] >= opened)
    return out


def main(argv: list[str] | None = None) -> int:
    """Pull HistData's long model-only history for the four series it
    carries and print synthetic-window counts per pair and year."""
    import argparse
    import json
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--cache", default="/cache/research/history")
    ap.add_argument("--first-year", type=int, default=2009)
    ap.add_argument("--last-month", default="2026-10", help="last monthly file of the current year")
    args = ap.parse_args(argv)
    last_year, last_month = (int(x) for x in args.last_month.split("-"))
    cache = Path(args.cache)
    for pair in HISTDATA_SYMBOLS.values():
        counts = {}
        for y in range(args.first_year, last_year + 1):
            months = [None] if y < last_year else range(1, last_month + 1)
            tape = [r for m in months for r in histdata_tape(pair, y, m, cache)]
            if tape:
                counts[y] = len(synthetic_windows(tape))
        print(json.dumps({pair: counts, "total": sum(counts.values())}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
