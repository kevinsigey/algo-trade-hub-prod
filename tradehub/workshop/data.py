"""Daily inputs for Workshop tests: adjusted closes (yfinance, already installed; no price keys on the
VPS) and FRED series (the keyed fetcher the journal uses). Fetchers are injectable for tests."""

from __future__ import annotations

import os
import tempfile
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


def bars(tickers: list[str], start: date, *, download=None, cache_dir: Path | None = None,
         now: datetime | None = None) -> dict[str, pd.DataFrame]:
    """Daily open/high/low/close/volume per ticker (intraday exits, VWAP rules), with the same last-complete-day cut
    and cache rules as closes(). Cached as <T>.ohlcv.csv, beside (never replacing) the closes cache; the step 5
    <T>.ohlc.csv (no volume) is ignored."""
    cutoff = last_complete_day(now or datetime.now(UTC))
    env_dir = os.getenv("TRADEHUB_PRICE_CACHE")
    cache_dir = cache_dir or (Path(env_dir) if env_dir else None)
    out: dict[str, pd.DataFrame] = {}
    missing = []
    for t in dict.fromkeys(tickers):
        path = cache_dir / f"{t}.ohlcv.csv" if cache_dir else None
        if path is not None and path.is_file():
            hit = pd.read_csv(path, index_col=0, parse_dates=True)
            if (not hit.empty and hit.index[0].date() <= start + timedelta(days=7)
                    and hit.index[-1].date() >= _weekday_on_or_before(cutoff)):
                out[t] = hit
                continue
        missing.append(t)
    if missing:
        if download is None:
            import yfinance as yf
            download = yf.download
        raw = download(missing, start=start.isoformat(), auto_adjust=True, progress=False)
        for t in missing:
            if raw is None or raw.empty or ("Close", t) not in raw:
                raise UnknownSymbol(f"no daily prices for {t}")
            frame = pd.DataFrame({k.lower(): raw[(k, t)] for k in ("Open", "High", "Low", "Close", "Volume")})
            frame = frame.dropna(subset=["open", "high", "low", "close"])  # a missing volume only blanks VWAP
            frame.index = pd.DatetimeIndex(frame.index).tz_localize(None)
            frame = frame[frame.index <= pd.Timestamp(cutoff)]
            if frame.empty:
                raise UnknownSymbol(f"no daily prices for {t}")
            out[t] = frame
            if cache_dir:
                cache_dir.mkdir(parents=True, exist_ok=True)
                frame.to_csv(cache_dir / f"{t}.ohlcv.csv")
    return {t: f[(f.index >= pd.Timestamp(start)) & (f.index <= pd.Timestamp(cutoff))] for t, f in out.items()}


def add_bars(closes: pd.DataFrame, bars_by_ticker: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Closes plus <T>.open / .high / .low / .volume columns, the shape the engine reads for bars."""
    extra = {f"{t}.{k}": b[k] for t, b in bars_by_ticker.items() for k in ("open", "high", "low", "volume") if k in b}
    return closes.join(pd.DataFrame(extra), how="left")


def with_rule_bars(spec, prices: pd.DataFrame, start: date, *, bars_fn=None) -> pd.DataFrame:
    """Attach daily bars for the leg when the idea's exits run during the day, and for every VWAP rule's ticker;
    otherwise return prices unchanged."""
    need = [(spec.hold or spec.short)[0]] if spec.exits.mode == "intraday" and spec.exits.any() else []
    if spec.rules is not None:
        groups = [spec.rules.enter] + ([spec.rules.exit] if spec.rules.exit else [])
        need += [c.series for g in groups for c in g.conditions if c.measure == "vs_vwap"]
    if not need:
        return prices
    return add_bars(prices, (bars_fn or bars)(list(dict.fromkeys(need)), start))


ACTIONS = ("up", "down", "main", "init", "reit")


def analyst(ticker: str, *, fetch=None, cache_dir: Path | None = None, now: datetime | None = None) -> pd.DataFrame:
    """Dated analyst actions for a stock (yfinance upgrades_downgrades): index = tz-naive action time, columns
    action (up/down/main/init/reit) and target (the price target set, NaN when none). Actions after the last
    complete day are dropped; cached as <T>.analyst.csv and refetched once per new complete day.
    ETFs and funds have none: UnknownSymbol."""
    cutoff = last_complete_day(now or datetime.now(UTC))
    env_dir = os.getenv("TRADEHUB_PRICE_CACHE")
    cache_dir = cache_dir or (Path(env_dir) if env_dir else None)
    path = cache_dir / f"{ticker}.analyst.csv" if cache_dir else None
    hit = pd.read_csv(path, index_col=0, parse_dates=True) if path is not None and path.is_file() else None
    if hit is not None and not hit.empty and str(hit["as_of"].iloc[0]) == cutoff.isoformat():
        return hit[["action", "target"]]
    if fetch is None:
        import yfinance as yf
        fetch = lambda t: yf.Ticker(t).upgrades_downgrades  # noqa: E731
    try:
        raw = fetch(ticker)
    except Exception:  # yfinance logs a 404 and returns nothing for funds; a rate limit can raise
        raw = None
    if raw is None or len(raw) == 0 or "Action" not in raw:
        if hit is not None and not hit.empty:  # Yahoo is down or rate-limiting: yesterday's actions still hold
            return hit[["action", "target"]]
        raise UnknownSymbol(f"no analyst data for {ticker} (ETFs and funds have none, or Yahoo unavailable)")
    idx = pd.DatetimeIndex(raw.index)
    idx = idx.tz_localize(None) if idx.tz is not None else idx
    target = pd.to_numeric(raw.get("currentPriceTarget"), errors="coerce") if "currentPriceTarget" in raw else None
    frame = pd.DataFrame({"action": raw["Action"].astype(str).str.lower().to_numpy(),
                          "target": target.where(target > 0).to_numpy() if target is not None else float("nan")},
                         index=idx).sort_index()
    frame = frame[frame["action"].isin(ACTIONS) & (frame.index < pd.Timestamp(cutoff + timedelta(days=1)))]
    if frame.empty:
        raise UnknownSymbol(f"no analyst data for {ticker} (ETFs and funds have none)")
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=cache_dir, prefix=f"{ticker}.", suffix=".tmp")
        os.close(fd)
        try:  # the API and a job may read or refresh it at the same moment
            frame.assign(as_of=cutoff.isoformat()).to_csv(tmp)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return frame


def rule_series(spec, fred_start: date, *, fred=None, analyst_fn=None) -> dict:
    """Everything a rule reads besides closes: FRED series by id, analyst actions under "<T>@analyst"."""
    from tradehub.workshop.engine import analyst_tickers, rule_series_ids
    out = {i: (fred or fred_series)(i, fred_start) for i in rule_series_ids(spec)}
    for t in analyst_tickers(spec):
        out[f"{t}@analyst"] = (analyst_fn or analyst)(t)
    return out
