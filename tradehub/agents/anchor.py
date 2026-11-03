"""Market facts for debates, fetched hub-side from yfinance -- never from the
framework, whose narrative prices Kevin caught drifting from the tape
(2026-11-03). Two reads, both fail-soft (any error -> None / missing, the
card then shows no anchor rather than a wrong one):

- market_anchor: the numbers at debate time, stored on the run record.
- current_prices: the live read for the feed, cached 60s per ticker.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

_TIMEOUT_S = 8.0
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_S = 60.0


def _fetch(ticker: str) -> dict | None:
    import yfinance as yf

    info = yf.Ticker(ticker).fast_info

    def pick(*names: str) -> float | None:
        for name in names:
            try:
                value = info[name]
            except Exception:  # noqa: BLE001 -- fast_info key spelling varies by version
                value = getattr(info, name, None)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    price = pick("lastPrice", "last_price")
    if price is None or price <= 0:
        return None
    return {"price": price,
            "prev_close": pick("previousClose", "previous_close"),
            "year_high": pick("yearHigh", "year_high"),
            "year_low": pick("yearLow", "year_low")}


def _guarded(ticker: str) -> dict | None:
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_fetch, ticker).result(timeout=_TIMEOUT_S)
    except Exception:  # noqa: BLE001 -- a hung or broken feed means no anchor, never a stalled debate
        return None


def market_anchor(ticker: str, *, now: datetime) -> dict | None:
    """The anchor stored on a run: the fetched facts plus their timestamp."""
    facts = _guarded(ticker)
    if facts is None:
        return None
    return {**facts, "at": now.isoformat()}


def current_prices(tickers: set[str], *, now: datetime | None = None) -> dict[str, dict]:
    """{ticker: {price, at}} for the feed's live column; 60s cache per ticker."""
    now = now or datetime.now().astimezone()
    out: dict[str, dict] = {}
    for ticker in sorted(tickers):
        hit = _CACHE.get(ticker)
        if hit and time.monotonic() - hit[0] < _CACHE_TTL_S:
            out[ticker] = hit[1]
            continue
        facts = _guarded(ticker)
        if facts is not None:
            entry = {"price": facts["price"], "at": now.isoformat()}
            _CACHE[ticker] = (time.monotonic(), entry)
            out[ticker] = entry
    return out
