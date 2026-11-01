"""Daily inputs for Workshop tests: adjusted closes (yfinance, already installed; no price keys on the
VPS) and FRED series (the keyed fetcher the journal uses). Fetchers are injectable for tests."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
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


def revision_series(series_id: str, start: date, *, vintages_fn=None, today: date | None = None) -> pd.Series:
    """How far the freshest print has been revised from its first print, known at
    each month-end vintage (phase-2 §5.2). Built from ALFRED vintages on the same
    month-end grid the labor scoreboard uses -- that point-in-time record is the
    measure's data basis. One pass in vintage order, tracking first prints with
    first_prints' rule (the earliest vintage's back history never counts), emitting
    at each vintage the revision-so-far of that vintage's newest month. Monthly
    print series only (PAYEMS and kin): the value is a change minus a first-print
    change, in the series' own units."""
    from tradehub.data.alfred_vintages import fetch_vintages
    from tradehub.engines.labor import add_months, month_end

    def change(vintage: dict, month: date) -> float | None:
        prev = add_months(month, -1)
        return vintage[month] - vintage[prev] if month in vintage and prev in vintage else None

    today = today or date.today()
    grid, day = [], month_end(start)
    while day <= month_end(today):
        grid.append(day)
        day = month_end(add_months(day, 1))
    vintages = (vintages_fn or fetch_vintages)(series_id, grid)
    out: dict[date, float] = {}
    firsts: dict[date, float] = {}
    newest: date | None = None
    for vday in sorted(vintages):
        vintage = vintages[vday]
        if not vintage:
            continue
        top = max(vintage)
        fresh = [top] if newest is None else [m for m in vintage if newest < m <= top]
        for m in fresh:
            c = change(vintage, m)
            if c is not None:
                firsts[m] = c
        current = change(vintage, top)
        if current is not None and top in firsts:
            out[vday] = current - firsts[top]
        newest = top if newest is None else max(newest, top)
    return pd.Series(out, name=f"{series_id}@revision", dtype=float).sort_index()


def rule_series(spec, fred_start: date, *, fred=None, analyst_fn=None, news_fn=None, revision_fn=None) -> dict:
    """Everything a rule reads besides closes: FRED series by id, analyst actions under "<T>@analyst",
    news-tone baskets by name, revision series under "<id>@revision". Option legs add their vol
    indexes and DTB3 (engine.option_series_ids)."""
    from tradehub.workshop.engine import (analyst_tickers, news_series_ids, option_series_ids,
                                          revision_series_ids, rule_series_ids)
    ids = list(dict.fromkeys(rule_series_ids(spec) + option_series_ids(spec)))
    out = {i: (fred or fred_series)(i, fred_start) for i in ids}
    for t in analyst_tickers(spec):
        out[f"{t}@analyst"] = (analyst_fn or analyst)(t)
    if news_series_ids(spec):
        from tradehub.workshop.news import news_tone_series
        for basket in news_series_ids(spec):
            out[basket] = (news_fn or news_tone_series)(basket, fred_start)
    for series_id in revision_series_ids(spec):
        out[f"{series_id}@revision"] = (revision_fn or revision_series)(series_id, fred_start)
    return out


def _yahoo_dividends(ticker: str) -> pd.Series:
    import yfinance as yf
    return yf.Ticker(ticker).dividends


def div_yields(spec, closes: pd.DataFrame, *, fetch=None) -> dict[str, float]:
    """Trailing-12-month dividend yield per option underlying: the year's dividends over
    the test's last close. Best-effort -- a ticker Yahoo won't answer for prices at 0, and
    the run is labelled model prices either way."""
    if not spec.options:
        return {}
    out: dict[str, float] = {}
    for u in dict.fromkeys(leg.underlying for leg in spec.options):
        try:
            divs = (fetch or _yahoo_dividends)(u)
            idx = pd.DatetimeIndex(divs.index)
            idx = idx.tz_localize(None) if idx.tz is not None else idx
            amounts = pd.Series(pd.to_numeric(divs, errors="coerce").to_numpy(), index=idx).sort_index()
            last_close = float(closes[u].dropna().iloc[-1])
            cutoff = closes.index[-1] - pd.Timedelta(days=365)
            out[u] = float(amounts[amounts.index > cutoff].sum()) / last_close if last_close > 0 else 0.0
        except Exception:  # noqa: BLE001 -- a missing yield must not sink the run
            out[u] = 0.0
    return out


KINDS = {"EQUITY": "stock", "ETF": "ETF", "MUTUALFUND": "fund", "INDEX": "index", "CRYPTOCURRENCY": "crypto"}


_NAMES: dict[str, dict] = {}  # only real answers are kept: a throttled Yahoo stub must not stick


def _yahoo_info(ticker: str) -> dict:
    import yfinance as yf
    return yf.Ticker(ticker).info


def ticker_info(ticker: str, *, fetch=None) -> dict | None:
    """What a ticker actually is ({name, kind}), so "GOLD" (a stock) isn't mistaken for gold. None if unknown."""
    if fetch is None and ticker in _NAMES:
        return _NAMES[ticker]
    try:
        info = (fetch or _yahoo_info)(ticker) or {}
    except Exception:
        return None
    name = info.get("longName") or info.get("shortName")
    if not name:
        return None
    kind = info.get("quoteType") or ""
    out = {"name": name, "kind": KINDS.get(kind, kind.lower() or "unknown")}
    if fetch is None and len(_NAMES) < 512:
        _NAMES[ticker] = out
    return out


def earnings_dates(ticker: str, *, fetch=None, cache_dir: Path | None = None, now: datetime | None = None
                   ) -> pd.DataFrame:
    """Reported earnings prints (yfinance get_earnings_dates): columns `time` (New York wall time, naive) and
    `surprise` (%), oldest first; prints after now are dropped. Cached as <T>.earnings.csv, refetched once per
    new complete day. ETFs and funds have none: UnknownSymbol."""
    cutoff = last_complete_day(now or datetime.now(UTC))
    env_dir = os.getenv("TRADEHUB_PRICE_CACHE")
    cache_dir = cache_dir or (Path(env_dir) if env_dir else None)
    path = cache_dir / f"{ticker}.earnings.csv" if cache_dir else None
    if path is not None and path.is_file():
        hit = pd.read_csv(path, parse_dates=["time"])
        if not hit.empty and str(hit["as_of"].iloc[0]) == cutoff.isoformat():
            return hit[["time", "surprise"]]
    if fetch is None:
        import yfinance as yf
        fetch = lambda t: yf.Ticker(t).get_earnings_dates(limit=60)  # noqa: E731
    try:
        raw = fetch(ticker)
    except Exception:  # noqa: BLE001 -- yfinance raises or logs and returns nothing for funds
        raw = None
    if raw is None or len(raw) == 0 or "Reported EPS" not in raw:
        raise UnknownSymbol(f"no earnings dates for {ticker} (ETFs and funds have none, or Yahoo unavailable)")
    idx = pd.DatetimeIndex(raw.index)
    idx = idx.tz_convert(NY).tz_localize(None) if idx.tz is not None else idx
    surprise = (pd.to_numeric(raw["Surprise(%)"], errors="coerce").to_numpy() if "Surprise(%)" in raw
                else np.full(len(raw), np.nan))
    frame = pd.DataFrame({"time": idx, "surprise": surprise,
                          "reported": pd.to_numeric(raw["Reported EPS"], errors="coerce").to_numpy()})
    frame = frame[frame["reported"].notna() & (frame["time"] < pd.Timestamp(cutoff + timedelta(days=1)))]
    frame = frame.sort_values("time").reset_index(drop=True)[["time", "surprise"]]
    if frame.empty:
        raise UnknownSymbol(f"no reported earnings for {ticker}")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f"{ticker}.", suffix=".tmp")
        os.close(fd)
        try:
            frame.assign(as_of=cutoff.isoformat()).to_csv(tmp, index=False)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return frame


FRED_RELEASE_DATES = "https://api.stlouisfed.org/fred/release/dates"


def release_dates(release_id: int, *, get_text=None, api_key: str | None = None) -> pd.DataFrame:
    """The days FRED published a release (101 FOMC press release, 10 CPI, 50 Employment Situation): column `time`."""
    import json

    from tradehub.data.alfred_vintages import FRED_API_KEY_ENV, default_get_text
    key = (api_key if api_key is not None else os.getenv(FRED_API_KEY_ENV, "")).strip()
    if not key:
        raise UnknownSymbol(f"{FRED_API_KEY_ENV} is not set; release calendars need the keyed FRED API")
    params = {"release_id": release_id, "file_type": "json", "api_key": key, "sort_order": "asc", "limit": 10000}
    try:
        body = json.loads((get_text or default_get_text)(FRED_RELEASE_DATES, params, secret=key))
    except Exception as exc:  # noqa: BLE001 -- an outage or a bad body: a readable 422, never the key
        raise UnknownSymbol(f"FRED release calendar {release_id} is unavailable right now; try again later") from exc
    days = sorted({d["date"] for d in body.get("release_dates", [])})
    if not days:
        raise UnknownSymbol(f"no release dates for FRED release {release_id}")
    return pd.DataFrame({"time": pd.to_datetime(days)})
