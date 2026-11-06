"""The crypto watcher (Kevin, 2026-11-06): what is happening in BTC and ETH market structure right now, each
signal with a plain explainer, read the way the Hormuz watcher reads shipping.

Every source is free and keyless:
  Hyperliquid  -- perp funding, open interest, premium to the index, mark price, 1h candles, funding history
  Deribit      -- DVOL, the options market's implied volatility (30 days of hourly history)
  DefiLlama    -- total stablecoin supply, daily
  mempool.space -- Bitcoin fee rates

Each signal compares its current value with its own recent history where a free history exists, and turns
that into a stress reading in [0, 1]. The watch stress is the weighted mean of the signals that can speak --
the Hormuz rule: a signal with no history or no current value is excluded, never read as calm. Open
interest has no free history, so it is shown and does not score until our own snapshots build one.

Nothing here forecasts or trades. Server-cached five minutes: the page polls, the upstreams don't scale
with viewers.
"""

from __future__ import annotations

import functools
import itertools
import math
import statistics
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

HYPERLIQUID = "https://api.hyperliquid.xyz/info"
DERIBIT = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
STABLES = "https://stablecoins.llama.fi/stablecoincharts/all"
MEMPOOL = "https://mempool.space/api/v1/fees/recommended"
COINS = ("BTC", "ETH")
CACHE_SECONDS = 300.0
FAIL_CACHE_SECONDS = 60.0  # a failed refresh is served this long, so viewers never hammer the sources
LABELS = ((0.25, "Calm"), (0.5, "Watch"), (math.inf, "Stressed"))
WEIGHTS = {"funding": 2, "premium": 0, "realized_vol": 2, "implied_vol": 2, "open_interest": 0, "stablecoins": 1, "fees": 0}

WHY = {
    "funding": "Perpetual futures never expire, so a funding payment keeps their price near spot. When funding is "
               "high, traders holding leveraged longs pay to stay in: the market is crowded on one side, and "
               "crowded positions unwind fast when price turns.",
    "premium": "How far the perp trades above or below the spot index. A perp trading rich means buyers are "
               "paying up for leverage; a discount means sellers are leaning on it.",
    "realized_vol": "How much the price actually moved in the last 24 hours, scaled to a year, against the last "
                    "30 days. A jump means the market has changed gear.",
    "implied_vol": "DVOL is what the options market charges for protection over the next 30 days. When it rises "
                   "faster than realized moves, traders are paying up for what they expect, not what has happened.",
    "open_interest": "The dollar value of all open perp positions. Rising open interest with a falling price "
                     "means new shorts or trapped longs; it is the fuel for forced liquidations.",
    "stablecoins": "Total dollars held in stablecoins, the cash crypto trades against. Growth is new money "
                   "arriving; a shrinking supply is money leaving the system.",
    "fees": "What it costs to get a Bitcoin transaction into the next block. Spikes mean the chain is busy, "
            "often during sharp market moves or token mints.",
}


class SourceDown(Exception):
    """A source could not be read; only its own signals go unknown."""


def annualized_funding_pct(hourly_rate: float) -> float:
    return round(hourly_rate * 24 * 365 * 100, 2)


def percentile(value: float, history: list[float]) -> float | None:
    """Mid-rank percentile: the share below the value, ties counted half. Hyperliquid funding sits on its
    floor rate most hours, so "at or below" would call an ordinary hour the highest ever."""
    if not history:
        return None
    below = sum(h < value for h in history)
    ties = sum(h == value for h in history)
    return round(100.0 * (below + ties / 2) / len(history), 1)


def realized_vol_pct(closes: list[float]) -> float | None:
    """Annualized standard deviation of hourly log returns, in percent."""
    rets = [math.log(b / a) for a, b in itertools.pairwise(closes) if a > 0 and b > 0]
    if len(rets) < 3:
        return None
    return statistics.pstdev(rets) * math.sqrt(24 * 365) * 100


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _finite(v: float) -> float:
    """Return v if finite; otherwise raise SourceDown so the signal is marked unavailable."""
    if not math.isfinite(v):
        raise SourceDown("non-finite value")
    return v


def label_for(stress: float | None) -> str | None:
    return None if stress is None else next(name for top, name in LABELS if stress < top)


def aggregate(signals: list[dict]) -> dict[str, Any]:
    speaking = [s for s in signals if s.get("stress") is not None and s.get("weight")]
    weight = sum(s["weight"] for s in speaking)
    stress = round(sum(s["stress"] * s["weight"] for s in speaking) / weight, 3) if weight else None
    return {"stress": stress, "label": label_for(stress), "speaking": len(speaking),
            "of": sum(1 for s in signals if s.get("weight"))}


def _signal(key: str, label: str, value: float | None, unit: str, reading: str, *, stress: float | None = None,
            percentile_: float | None = None, normal: str | None = None) -> dict[str, Any]:
    return {"key": key, "label": label, "value": None if value is None else round(value, 2), "unit": unit,
            "percentile": percentile_, "normal": normal, "stress": None if stress is None else round(stress, 3),
            "weight": WEIGHTS[key], "reading": reading, "why": WHY[key]}


def _down(key: str, label: str, unit: str, source: str) -> dict[str, Any]:
    return _signal(key, label, None, unit, f"{source} is unavailable right now, so this signal is left out of the stress read.")


def _coin(coin: str, ctx: dict | None, funding_history, closes, dvol) -> dict[str, Any]:
    signals: list[dict] = []
    price = change = None
    if ctx is None:
        for key, label, unit in (("funding", "Funding rate", "% a year"), ("premium", "Perp premium", "bps")):
            signals.append(_down(key, label, unit, "Hyperliquid"))
    else:
        try:
            price = _finite(float(ctx["markPx"]))
            prev = float(ctx.get("prevDayPx") or 0)
            change = (price / prev - 1) * 100 if prev else None
            rate = _finite(float(ctx["funding"]))
            oi = _finite(float(ctx["openInterest"]))
            bps = _finite(float(ctx.get("premium") or 0)) * 1e4
        except SourceDown:
            for key, label, unit in (("funding", "Funding rate", "% a year"), ("premium", "Perp premium", "bps"),
                                     ("open_interest", "Open interest", "$bn")):
                signals.append(_down(key, label, unit, "Hyperliquid"))
            price = None
        else:
            annual = annualized_funding_pct(rate)
            try:
                hist = [float(h) for h in funding_history(coin)]
            except SourceDown:
                hist = []
            pct = percentile(rate, hist)
            side = "longs pay shorts" if rate >= 0 else "shorts pay longs"
            signals.append(_signal(
                "funding", "Funding rate", annual, "% a year",
                f"{side.capitalize()} {abs(annual):.1f}% a year"
                + (f", higher than {pct:.0f}% of the hours in the last three weeks." if pct is not None else "."),
                stress=None if pct is None else _clamp(abs(pct - 50) / 50), percentile_=pct,
                normal=None if not hist else f"median {annualized_funding_pct(statistics.median(hist)):.1f}% a year"))
            signals.append(_signal(
                "premium", "Perp premium", bps, "bps",
                f"The perp trades {abs(bps):.1f} bps {'above' if bps >= 0 else 'below'} the spot index"
                + (": buyers are paying up for leverage." if bps > 5 else ": sellers are leaning on it." if bps < -5 else ", close to fair."),
                stress=None))
    try:
        c = closes(coin)
        # 30-day value needs 25*24 = 600 closes; 24-hour value needs 25 closes
        if len(c) < 25 * 24 or len(c) < 25:
            raise SourceDown("history too short")
        rv24, rv30 = realized_vol_pct(c[-25:]), realized_vol_pct(c)
        if rv24 is None or not rv30:
            raise SourceDown("too few candles")
        ratio = rv24 / rv30
        signals.append(_signal(
            "realized_vol", "Realized volatility", rv24, "% a year",
            f"The last 24 hours moved like {rv24:.0f}% a year, {ratio:.1f}x the 30-day pace"
            + (" -- the market has changed gear." if ratio >= 1.5 else "."),
            stress=_clamp((ratio - 1) / 2), normal=f"30-day {rv30:.0f}% a year"))
    except SourceDown as e:
        msg = "Hyperliquid's candles" if str(e) == "too few candles" else "Hyperliquid's candles: history is too short"
        signals.append(_down("realized_vol", "Realized volatility", "% a year", msg))
    try:
        d = dvol(coin)
        if not d:
            raise SourceDown("no DVOL")
        # Need at least 20*24 = 480 history points (excluding current one)
        if len(d) < 20 * 24 + 1:
            now_v = d[-1]
            med = statistics.median(d[:-1] or d)
            pct = percentile(now_v, d[:-1])
            signals.append(_signal(
                "implied_vol", "Implied volatility (DVOL)", now_v, "% a year",
                f"Options price {now_v:.0f}% a year of movement, against a 30-day median of {med:.0f}%"
                + (": traders are paying up for protection." if now_v > med * 1.15 else "."),
                stress=None, percentile_=pct, normal=None))
        else:
            now_v, med = d[-1], statistics.median(d[:-1] or d)
            pct = percentile(now_v, d[:-1])
            signals.append(_signal(
                "implied_vol", "Implied volatility (DVOL)", now_v, "% a year",
                f"Options price {now_v:.0f}% a year of movement, against a 30-day median of {med:.0f}%"
                + (": traders are paying up for protection." if now_v > med * 1.15 else "."),
                stress=_clamp((now_v / med - 1) / 0.5) if med else None, percentile_=pct, normal=f"median {med:.0f}%"))
    except SourceDown:
        signals.append(_down("implied_vol", "Implied volatility (DVOL)", "% a year", "Deribit"))
    if ctx is not None and price is not None:
        oi_usd = oi * price / 1e9
        vol = float(ctx.get("dayNtlVlm") or 0) / 1e9
        signals.append(_signal(
            "open_interest", "Open interest", oi_usd, "$bn",
            f"${oi_usd:.2f}bn of open positions on Hyperliquid"
            + (f", {oi_usd / vol:.1f}x a day's volume." if vol else ".") + " Its history is still being built.",
        ))
    elif ctx is None:
        signals.append(_down("open_interest", "Open interest", "$bn", "Hyperliquid"))
    return {"price": price, "change_24h_pct": change, "signals": signals}


def build_watch(*, ctx: Callable[[], dict], funding_history: Callable[[str], list], closes: Callable[[str], list],
                dvol: Callable[[str], list], stablecoins: Callable[[], list], fees: Callable[[], dict]) -> dict[str, Any]:
    try:
        ctxs = ctx()
    except SourceDown:
        ctxs = {}
    coins = {c: _coin(c, ctxs.get(c), funding_history, closes, dvol) for c in COINS}
    market: list[dict] = []
    try:
        s = stablecoins()
        if len(s) < 8:
            raise SourceDown("short series")
        chg = (s[-1] / s[-8] - 1) * 100
        market.append(_signal(
            "stablecoins", "Stablecoin supply", s[-1] / 1e9, "$bn",
            f"${s[-1] / 1e9:.1f}bn in stablecoins, {'+' if chg >= 0 else '−'}{abs(chg):.2f}% in a week: "
            + ("new money arriving." if chg > 0.3 else "money leaving." if chg < -0.3 else "flat."),
            stress=_clamp(-chg / 3), normal=f"a week ago ${s[-8] / 1e9:.1f}bn"))
    except SourceDown:
        market.append(_down("stablecoins", "Stablecoin supply", "$bn", "DefiLlama"))
    try:
        f = fees()
        fast = float(f["fastestFee"])
        market.append(_signal(
            "fees", "Bitcoin fees", fast, "sat/vB",
            f"Next-block fee {fast:.0f} sat/vB" + (": the chain is busy." if fast >= 30 else ": the chain is quiet.")))
    except (SourceDown, KeyError, TypeError, ValueError):
        market.append(_down("fees", "Bitcoin fees", "sat/vB", "mempool.space"))
    every = [s for c in coins.values() for s in c["signals"]] + market
    return {"as_of": datetime.now(UTC).isoformat(), "coins": coins, "market": market, "stress": aggregate(every)}


def _post(body: dict) -> Any:
    try:
        r = httpx.post(HYPERLIQUID, json=body, timeout=15)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceDown("hyperliquid") from exc


def _get(url: str, params: dict | None = None) -> Any:
    try:
        r = httpx.get(url, params=params, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceDown(url) from exc


def _shape(fn):
    """A reply of the wrong shape is that source down, never an exception that escapes the cache."""
    @functools.wraps(fn)
    def wrapped(*args):
        try:
            return fn(*args)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise SourceDown(fn.__name__) from exc
    return wrapped


@_shape
def _live_ctx() -> dict:
    meta, ctxs = _post({"type": "metaAndAssetCtxs"})
    names = [u["name"] for u in meta["universe"]]
    return {c: ctxs[names.index(c)] for c in COINS if c in names}


def _ms(days: int) -> int:
    return int((datetime.now(UTC) - timedelta(days=days)).timestamp() * 1000)


@_shape
def _live_funding(coin: str) -> list:
    return [row["fundingRate"] for row in _post({"type": "fundingHistory", "coin": coin, "startTime": _ms(30)})]


@_shape
def _live_closes(coin: str) -> list:
    rows = _post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": _ms(30),
                                                    "endTime": int(time.time() * 1000)}})
    return [float(c["c"]) for c in sorted(rows, key=lambda c: c["t"])]


@_shape
def _live_dvol(coin: str) -> list:
    body = _get(DERIBIT, {"currency": coin, "start_timestamp": _ms(30), "end_timestamp": int(time.time() * 1000),
                          "resolution": 3600})
    return [float(row[4]) for row in body["result"]["data"]]


@_shape
def _live_stables() -> list:
    rows = _get(STABLES)
    return [float(r["totalCirculatingUSD"]["peggedUSD"]) for r in rows[-40:]]


_cache: dict[str, Any] = {"at": 0.0, "payload": None, "ttl": CACHE_SECONDS}
_refresh = threading.Lock()


def watch() -> dict[str, Any]:
    """Cached: one refresh at a time. TTL starts after refresh finishes.
    Stale-while-refresh: if cached payload exists but expired and lock is held, return stale immediately.
    With no cached payload, wait for lock at most 25s; on timeout return unavailable without caching."""
    # Fast path: fresh cache
    now_s = time.monotonic()
    if _cache["payload"] is not None and now_s - _cache["at"] < _cache["ttl"]:
        return _cache["payload"]

    # Try to acquire lock
    have_cache = _cache["payload"] is not None
    if have_cache:
        # Cache exists but expired: try non-blocking acquire
        if not _refresh.acquire(blocking=False):
            # Another request is refreshing, return stale payload
            return _cache["payload"]
    else:
        # No cache: wait for lock up to 25 seconds
        if not _refresh.acquire(timeout=25):
            return {"state": "unavailable"}

    try:
        # We have the lock, do the refresh
        try:
            payload = build_watch(ctx=_live_ctx, funding_history=_live_funding, closes=_live_closes,
                                  dvol=_live_dvol, stablecoins=_live_stables,
                                  fees=_shape(lambda: _get(MEMPOOL)))
            ttl = CACHE_SECONDS
        except Exception:  # noqa: BLE001 -- served as unavailable for a minute; the route never 500s
            payload, ttl = {"state": "unavailable"}, FAIL_CACHE_SECONDS
        # Record TTL start AFTER build_watch returns
        _cache.update(at=time.monotonic(), payload=payload, ttl=ttl)
        return payload
    finally:
        _refresh.release()
