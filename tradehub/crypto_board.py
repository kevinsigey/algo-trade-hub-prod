"""The Crypto research desk's tracked-markets board (phase-3 §5).

What Kalshi's crypto markets are saying right now, read as MARKET DATA --
never as this hub's predictions. Two shapes per coin:

- the hourly above/below ladder (KXBTCD / KXETHD): ~20 strikes per hourly
  event, each "price at or above the strike when the hour closes" against
  the CF Benchmarks real-time index. The board reports the strike whose
  implied probability sits closest to 50% -- the market's coin-flip line --
  beside spot.
- the 15-minute up/down market (KXBTC15M / KXETH15M): one market per
  quarter hour against a floor set at the window's open. The board reports
  its implied probability and the floor beside spot.

Reads go through the hub's existing Kalshi client (tradehub.data.kalshi_live)
with its dollar quotes. Every series is guarded separately: a failed read
nulls its own cell and says why, never the whole board.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import requests

from tradehub.core.crypto_data import KRAKEN_PAIRS
from tradehub.data.kalshi_live import KalshiLive, LiveMarket
from tradehub.edges import Quote

HOURLY_SERIES = {"BTC": "KXBTCD", "ETH": "KXETHD"}
QUARTER_SERIES = {"BTC": "KXBTC15M", "ETH": "KXETH15M"}
KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"


def implied(quote: Quote) -> tuple[float | None, bool]:
    """(implied probability, one_sided). Mid when both sides quote; the
    single side when only one does (flagged, never silently treated as a
    mid); None when the market quotes nothing."""
    bid, ask = quote.yes_bid, quote.yes_ask
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0, False
    if bid is not None:
        return bid, True
    if ask is not None:
        return ask, True
    return None, True


def summarize_ladder(markets: list[LiveMarket], *, now: datetime) -> dict[str, Any] | None:
    """The next hourly event's market line, in whichever shape the book
    actually quotes. When a strike trades near 50% that strike is the
    coin-flip line. But these ladders usually quote as a STEP (verified live
    2026-11-01: every strike below spot at 99c, every strike above at 1c, no
    strike anywhere near 50) -- then the honest summary is the bracket the
    step sits in: the highest strike the market prices as near-certain and
    the lowest it prices as near-impossible."""
    future = [lm for lm in markets if lm.market.close_time > now and lm.market.floor_strike is not None]
    if not future:
        return None
    close = min(lm.market.close_time for lm in future)
    quoted = []
    for lm in future:
        if lm.market.close_time != close:
            continue
        prob, one_sided = implied(lm.quote)
        if prob is not None:
            quoted.append((lm.market.floor_strike, prob, one_sided))
    if not quoted:
        return None
    quoted.sort()
    near = [q for q in quoted if 0.25 <= q[1] <= 0.75]
    if near:
        strike, prob, one_sided = min(near, key=lambda q: abs(q[1] - 0.5))
        return {
            "closes_at": close.isoformat(),
            "shape": "coin_flip",
            "coin_flip_strike": strike,
            "implied_pct": round(prob * 100, 1),
            "one_sided": one_sided,
            "strikes_quoted": len(quoted),
        }
    below = [q[0] for q in quoted if q[1] >= 0.90]
    above = [q[0] for q in quoted if q[1] <= 0.10]
    if below and above and max(below) < min(above):
        return {
            "closes_at": close.isoformat(),
            "shape": "step",
            "bracket": [max(below), min(above)],
            "strikes_quoted": len(quoted),
        }
    return None


def summarize_quarter(markets: list[LiveMarket], *, now: datetime) -> dict[str, Any] | None:
    """The next 15-minute market: its implied probability of finishing at or
    above its floor."""
    future = [lm for lm in markets if lm.market.close_time > now and lm.market.floor_strike is not None]
    if not future:
        return None
    nxt = min(future, key=lambda lm: lm.market.close_time)
    prob, one_sided = implied(nxt.quote)
    if prob is None:
        return None
    return {
        "closes_at": nxt.market.close_time.isoformat(),
        "floor": nxt.market.floor_strike,
        "implied_pct": round(prob * 100, 1),
        "one_sided": one_sided,
    }


def fetch_spot(asset: str) -> float:
    """Kraken spot (last trade) for the asset. Raises on any failure; the
    caller nulls the cell."""
    pair = KRAKEN_PAIRS[asset]
    resp = requests.get(KRAKEN_TICKER_URL, params={"pair": pair}, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("error"):
        raise RuntimeError(f"Kraken error: {payload['error']}")
    result = payload.get("result") or {}
    for key, value in result.items():
        if isinstance(value, dict) and value.get("c"):
            return float(value["c"][0])
    raise RuntimeError(f"Kraken returned no ticker for {pair}")


def live_board(
    *,
    open_markets: Callable[[str], list[LiveMarket]] | None = None,
    spot: Callable[[str], float] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the board from live reads, each guarded separately."""
    now = now or datetime.now(timezone.utc)
    if open_markets is None:
        live = KalshiLive()
        open_markets = live.open_markets
    spot = spot or fetch_spot

    board: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "note": "Kalshi market data, not a prediction. Implied probabilities are quote midpoints "
                "(one-sided quotes are flagged). The hourly ladder usually quotes as a step, so "
                "its line is shown as the bracket the step sits in. Hourly markets settle on the "
                "CF Benchmarks real-time index average, not on spot.",
        "spots": {},
        "hourly": {},
        "quarter": {},
    }
    for asset in ("BTC", "ETH"):
        try:
            board["spots"][asset] = spot(asset)
        except Exception:
            board["spots"][asset] = None
        for kind, series_map, summarize in (
            ("hourly", HOURLY_SERIES, summarize_ladder),
            ("quarter", QUARTER_SERIES, summarize_quarter),
        ):
            try:
                board[kind][asset] = summarize(open_markets(series_map[asset]), now=now)
            except Exception as exc:
                board[kind][asset] = None
                board[kind][f"{asset}_error"] = str(exc)
    return board
