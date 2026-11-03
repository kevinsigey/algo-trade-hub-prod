"""Hourly crypto (KXBTC / KXETH) settlement math: a live-price Normal whose sigma
comes from trailing 1-minute realized volatility.

Kalshi's hourly crypto markets settle on the CF Benchmarks BRTI value at the
top of the hour. The model is the oil-hourly pattern with ONE deliberate
difference, and the difference is the whole story: variant 1 took sigma from
the trailing settled hourly changes, exactly like oil, and its walk-forward
replay over the last ~100 scorable hours was a dead tie with persistence on
BTC (paired edge -0.0001 +- 0.0003) and noise on ETH (+0.0004 +- 0.0010), so
it did not ship. Variant 2 -- preregistered before it ran (2026-11-02) --
changed only the sigma source: the stdev of 1-minute log returns over the
120 minutes ending at the freeze, scaled by sqrt(time-to-close). It beat
persistence on both series clear of the bar (BTC +0.0048 +- 0.0015, ETH
+0.0090 +- 0.0025). Crypto's vol regime moves faster than a 72-hour window
of settled prints can track; the tape's own last two hours can.

No drift term, same as oil: an hour is too short for drift to be anything
but noise. Returns count only adjacent-minute bar pairs, so a data gap
never masquerades as a quiet minute.
"""

from __future__ import annotations

import math
import statistics
from datetime import timedelta

from tradehub.backtest.pit import Observation
from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

SERIES_SYMBOLS = {"KXBTC": "BTC-USD", "KXETH": "ETH-USD"}
CRYPTO_RESOLUTION = 0.01  # BRTI settles to the cent
DECISION_LEAD = timedelta(minutes=65)   # the oil hourly lead, same reasoning
RV_WINDOW = timedelta(minutes=120)      # trailing realized-vol window ending at the anchor bar
MIN_RV_RETURNS = 60                     # at least half the window must be adjacent-minute pairs
MIN_SIGMA_MINUTES = 5.0                 # the sigma scaling never assumes less than five minutes


def realized_sigma(bars: list[Observation], minutes_to_close: float) -> float | None:
    """Relative sigma for the time left to the close, or None when the tape is too thin.

    `bars` are 1-minute closes stamped with their bar time, any order. The
    window ends at the LAST bar: stdev of the log returns of adjacent-minute
    pairs inside the trailing RV_WINDOW, scaled by sqrt(minutes_to_close)
    (floored at MIN_SIGMA_MINUTES). Relative: multiply by the anchor price
    for a price sigma.
    """
    ordered = sorted(bars, key=lambda o: o.published_at)
    if not ordered:
        return None
    end = ordered[-1].published_at
    window = [o for o in ordered if o.published_at > end - RV_WINDOW]
    returns = []
    for prev, cur in zip(window, window[1:]):
        if cur.published_at - prev.published_at == timedelta(minutes=1) \
                and prev.value > 0 and cur.value > 0:
            returns.append(math.log(cur.value / prev.value))
    if len(returns) < MIN_RV_RETURNS:
        return None
    return statistics.stdev(returns) * math.sqrt(max(minutes_to_close, MIN_SIGMA_MINUTES))


def crypto_prob(market: KalshiMarket, anchor: float, sigma_price: float) -> float:
    """P(settlement resolves YES) for a Normal centred on the live price."""
    return prob_in_interval(anchor, sigma_price, yes_interval(market, CRYPTO_RESOLUTION))
