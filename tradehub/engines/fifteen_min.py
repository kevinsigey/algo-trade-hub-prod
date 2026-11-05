"""Fifteen-minute direction math for Kalshi's KXWTI15M / KXBRENT15M / KXNATGAS15M.

These markets exist (verified live 2026-11-04; the older claim in the hourly
oil files that the 15-minute ladders are crypto-only is wrong). Each window is
a single contract: YES iff the close of the settlement source's 1-minute candle
at the window's end is at least the close at its start (Pyth PYTHOIL / BRENT /
NATGAS respectively). A direct direction bet, not a strike ladder.

The model (preregistered 2026-11-04, `*-15m-v1`; sampling superseded the
same day by `*-15m-v2`, Kevin's call -- the math is unchanged): by freeze
time part of the window has already traded. What remains is a random walk,
so

    P(up) = Phi( ln(price_now / price_at_open) / (sigma_1m * sqrt(minutes_left)) )

with sigma_1m the trailing realized volatility of 1-minute log returns on the
anchor tape. The anchor is Hyperliquid's perp trade candles (xyz:CL / xyz:BRENTOIL
/ xyz:NATGAS; candle closes are trades, not the oracle the hourly board reads) --
free and live, where the settlement source (Pyth) is gated; the basis between the
perp and Pyth's index is part of what the shadow's record grades, stated here
rather than hidden. v1 sampled only
the window opening at :15 each hour (the journal run's phase); v2 predicts
every window from a dedicated 5-minute runner, frozen about 5 minutes in,
with the exact elapsed/remaining minutes recorded on every row.

The bar (Kevin, 2026-11-04): at a 50c entry the quadratic fee (multiplier 1 on
all three series) puts break-even at about 52% hits. Simple reversal and
momentum already failed at real prices on WTI (-2c per contract, handover
2026-11-04), so v1 is the drift-scaled walk above and nothing cleverer.
"""

from __future__ import annotations

import math
import statistics

SERIES_COINS = {"KXWTI15M": "xyz:CL", "KXBRENT15M": "xyz:BRENTOIL", "KXNATGAS15M": "xyz:NATGAS"}
WINDOW_MINUTES = 15.0
SIGMA_FLOOR = 0.0002      # 2bp per minute: a dead-flat tape never prices at exactly 0/1
MIN_RETURNS = 30          # trailing 1-minute returns before the sigma is allowed to speak
MIN_REMAINING = 1.0       # the sqrt scaling never assumes less than a minute of travel


def realized_sigma_1m(closes: list[float]) -> float | None:
    """Stdev of consecutive 1-minute log returns, floored; None when the tape
    is too thin to have a sigma (the forecaster then skips -- the sigma method
    is never silently swapped, the crypto strictness rule)."""
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(returns) < MIN_RETURNS:
        return None
    return max(SIGMA_FLOOR, statistics.stdev(returns))


def prob_up(open_price: float, price: float, sigma_1m: float, minutes_remaining: float) -> float:
    """P(the window closes at or above its open) given the move so far."""
    if open_price <= 0 or price <= 0:
        raise ValueError("prices must be positive")
    drift = math.log(price / open_price)
    spread = sigma_1m * math.sqrt(max(minutes_remaining, MIN_REMAINING))
    return statistics.NormalDist().cdf(drift / spread)
