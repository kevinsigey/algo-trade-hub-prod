"""Daily inputs for Workshop tests: adjusted closes (yfinance, already installed; no price keys on the
VPS) and FRED series (the keyed fetcher the journal uses). Fetchers are injectable for tests."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from tradehub.data.fred_daily import fetch_fred_daily


class UnknownSymbol(ValueError):
    """A ticker or series with no data: the API answers 422 naming it."""


NY = ZoneInfo("America/New_York")


def last_complete_day(now: datetime) -> date:
    """The latest day whose close is final: today only after 17:00 New York, so an intraday bar never counts."""
    ny = now.astimezone(NY)
    return ny.date() if ny.hour >= 17 else ny.date() - timedelta(days=1)


def _weekday_on_or_before(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _cached(path: Path, start: date, cutoff: date) -> pd.Series | None:
    if not path.is_file():
        return None
    s = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
    if s.empty or s.index[0].date() > start + timedelta(days=7) or s.index[-1].date() < _weekday_on_or_before(cutoff):
        return None
    return s


def closes(tickers: list[str], start: date, *, download=None, cache_dir: Path | None = None,
           now: datetime | None = None) -> pd.DataFrame:
    """Daily closes up to the last completed day. Rows after it (yfinance's in-progress bar) are dropped before
    anything is cached or returned."""
    cutoff = last_complete_day(now or datetime.now(UTC))
    env_dir = os.getenv("TRADEHUB_PRICE_CACHE")
    cache_dir = cache_dir or (Path(env_dir) if env_dir else None)
    out: dict[str, pd.Series] = {}
    missing = []
    for t in dict.fromkeys(tickers):
        hit = _cached(cache_dir / f"{t}.csv", start, cutoff) if cache_dir else None
        if hit is None:
            missing.append(t)
        else:
            out[t] = hit
    if missing:
        if download is None:
            import yfinance as yf
            download = yf.download
        raw = download(missing, start=start.isoformat(), auto_adjust=True, progress=False)
        frame = raw["Close"] if raw is not None and not raw.empty else pd.DataFrame()
        for t in missing:
            s = frame[t].dropna() if t in frame else pd.Series(dtype=float)
            if s.empty:
                raise UnknownSymbol(f"no daily prices for {t}")
            s.index = pd.DatetimeIndex(s.index).tz_localize(None)
            s = s[s.index <= pd.Timestamp(cutoff)]
            out[t] = s.rename(t)
            if cache_dir:
                cache_dir.mkdir(parents=True, exist_ok=True)
                s.to_frame(t).to_csv(cache_dir / f"{t}.csv")
    df = pd.DataFrame({t: out[t] for t in dict.fromkeys(tickers)})
    return df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(cutoff))]


def fred_series(series_id: str, start: date, *, fetch=fetch_fred_daily) -> pd.Series:
    try:
        values = fetch(series_id, start)
    except RuntimeError as exc:
        if "FRED_API_KEY" in str(exc):
            raise
        raise UnknownSymbol(f"no FRED data for {series_id} ({exc})") from exc
    if not values:
        raise UnknownSymbol(f"no FRED data for {series_id}")
    s = pd.Series(values, dtype=float).sort_index()
    s.index = pd.DatetimeIndex(s.index)
    # ponytail: only daily series until first-release dates (ALFRED) are wired in. A weekly or monthly value is
    # dated by its period but published days to weeks later, so using it by its date would leak the future.
    if len(s) > 2 and s.index.to_series().diff().dt.days.median() > 4:
        raise UnknownSymbol(f"{series_id} is not a daily series; weekly and monthly FRED series aren't supported yet "
                            "(their release dates aren't wired in, so a test could see numbers before they were public)")
    return s.rename(series_id)
