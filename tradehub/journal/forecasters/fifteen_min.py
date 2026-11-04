"""Kalshi 15-minute direction markets (KXWTI15M / KXBRENT15M / KXNATGAS15M), as journal shadows.

One contract per 15-minute window: YES iff the settlement source's 1-minute
candle closes the window at or above its open (Pyth PYTHOIL / BRENT / NATGAS;
rules verified live 2026-11-04). The model is the drift-scaled random walk in
`engines/fifteen_min.py` (preregistered there): the move already in the window,
scaled by the trailing 1-minute realized vol over the minutes remaining. The
anchor tape is Hyperliquid's (free, live); Pyth itself is gated on Kevin's
trial key, so the perp-vs-index basis is part of what the record grades.

Cadence honesty: the journal runs hourly and its freezes land at minutes
15-22, so the sampled window is the one opening at :15 each hour, frozen with
roughly 1.5-7 minutes elapsed. The other three windows each hour are never
frozen -- a gap in coverage, stated here, not a selection made on outcomes.

Strictness (the crypto rule): a missing window-open candle, a stale tape, or
a too-thin sigma tape skips the freeze. The method is never silently swapped,
because a swapped method would corrupt the record the model is graded on.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.pyth import HyperliquidUnavailable, hyperliquid_candles
from tradehub.engines.fifteen_min import SERIES_COINS, WINDOW_MINUTES, prob_up, realized_sigma_1m
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.kalshi_linked import (
    KalshiImplied,
    entry_for,
    kalshi_target,
    quote_mid,
    quote_payload,
    settle_on_kalshi,
)

CADENCE = "15min"
FREEZE_MIN_ELAPSED = 1.5    # the open candle must exist and some move must be in
FREEZE_MAX_ELAPSED = 13.0   # at least ~2 minutes of risk must remain
MAX_TAPE_STALE = timedelta(minutes=3)
TAPE_SPAN = timedelta(minutes=150)

SERIES = (
    {"series": "KXWTI15M", "family": "oil_wti_15m", "name": "oil_wti_15m", "version": "wti-15m-v1"},
    {"series": "KXBRENT15M", "family": "oil_brent_15m", "name": "oil_brent_15m", "version": "brent-15m-v1"},
    {"series": "KXNATGAS15M", "family": "natgas_15m", "name": "natgas_15m", "version": "natgas-15m-v1"},
)


def _candles_or_empty(coin: str, start: datetime, end: datetime) -> list:
    try:
        return hyperliquid_candles(coin, start, end)
    except HyperliquidUnavailable:
        return []


class FifteenMinInputs:
    """Hyperliquid 1-minute candles per coin, loaded once per run (keyed on
    `now`, the crypto inputs' rule)."""

    def __init__(self, *, candles_fn: Callable = _candles_or_empty):
        self._candles_fn = candles_fn
        self._now: datetime | None = None
        self._tapes: dict[str, list] = {}

    def tape(self, coin: str, now: datetime) -> list:
        if now != self._now:
            self._now = now
            self._tapes = {c: self._candles_fn(c, now - TAPE_SPAN, now)
                           for c in SERIES_COINS.values()}
        return self._tapes[coin]


class FifteenMinModel:
    cadence = CADENCE

    def __init__(self, live, fetch: Callable[[str], Any], inputs: FifteenMinInputs, spec: dict):
        self._live, self._fetch_market, self._inputs = live, fetch, inputs
        self.series, self.family = spec["series"], spec["family"]
        self.name, self.version = spec["name"], spec["version"]
        self.coin = SERIES_COINS[self.series]
        self._open: dict[str, Any] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {}
        for lm in self._live.open_markets(self.series):
            window_open = lm.market.close_time - timedelta(minutes=WINDOW_MINUTES)
            elapsed = (now - window_open).total_seconds() / 60.0
            if FREEZE_MIN_ELAPSED <= elapsed <= FREEZE_MAX_ELAPSED:
                self._open[kalshi_target(lm.market.ticker)] = lm
        return [entry_for(lm, self.family, self.cadence) for lm in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        close_time = lm.market.close_time
        window_open = close_time - timedelta(minutes=WINDOW_MINUTES)
        tape = self._inputs.tape(self.coin, now)
        by_open = {t: v for t, v in tape}
        open_price = by_open.get(window_open - timedelta(minutes=1))
        if open_price is None:
            return None  # no candle closing at the window open: skip, never approximate it
        completed = [(t, v) for t, v in tape if t + timedelta(minutes=1) <= now]
        if not completed:
            return None
        last_t, price = completed[-1]
        effective_now = last_t + timedelta(minutes=1)
        if now - effective_now > MAX_TAPE_STALE:
            return None  # a stale tape is a gap, never a live price dressed as one
        remaining = (close_time - effective_now).total_seconds() / 60.0
        if remaining < FREEZE_MIN_ELAPSED:
            return None
        sigma = realized_sigma_1m([v for _t, v in completed[-91:]])
        if sigma is None:
            return None  # tape too thin: skip the freeze, never swap the sigma method
        elapsed = (effective_now - window_open).total_seconds() / 60.0
        return Forecast(self.name, self.version, entry.target,
                        prob_up(open_price, price, sigma, remaining),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "open_price": open_price,
                                 "price": price, "price_at": effective_now.isoformat(),
                                 "elapsed_min": round(elapsed, 1),
                                 "remaining_min": round(remaining, 1),
                                 "sigma_1m": sigma, "feed": self.coin,
                                 "basis": "drift-scaled random walk on Hyperliquid 1m "
                                          "candles (v1, preregistered 2026-11-04)"})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


def build_fifteen_min(live, fetch: Callable[[str], Any] = fetch_market,
                      inputs: FifteenMinInputs | None = None) -> list:
    inputs = inputs or FifteenMinInputs()
    out = []
    for spec in SERIES:
        out += [FifteenMinModel(live, fetch, inputs, spec),
                KalshiImplied(spec["family"], (spec["series"],), CADENCE, live, fetch,
                              lead=timedelta(minutes=WINDOW_MINUTES))]
    return out
