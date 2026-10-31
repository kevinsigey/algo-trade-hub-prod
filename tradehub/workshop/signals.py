"""Step 6 signal maths. Pure: the value on day t uses data up to and including t (the engine lags it).

Units (plan rulings): percentages are "% above"; RSI is Wilder's 0-100; MACD is 12/26/9 as (line - signal) / close x 100;
vs_high / vs_low compare with the PRIOR N closes, so > 0 / < 0 is a new N-day high / low; VWAP is a rolling N-day VWAP
from daily bars (typical price (H+L+C)/3 weighted by volume).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(values: pd.Series, n: int) -> pd.Series:
    diff = values.diff().to_numpy()
    out = np.full(len(values), np.nan)
    if len(values) > n:
        gain, loss = np.clip(diff, 0, None), np.clip(-diff, 0, None)
        g, lo = np.nanmean(gain[1:n + 1]), np.nanmean(loss[1:n + 1])
        for i in range(n, len(values)):
            if i > n:
                g, lo = (g * (n - 1) + gain[i]) / n, (lo * (n - 1) + loss[i]) / n
            out[i] = 100.0 if lo == 0 else 100 - 100 / (1 + g / lo)
    return pd.Series(out, index=values.index)


def measure(values: pd.Series, how: str, lookback: int, *, slow: int | None = None,
            bars: pd.DataFrame | None = None) -> pd.Series:
    n = lookback
    if how == "level":
        return values
    if how == "change":
        return values - values.shift(n)
    if how == "pct_change":
        return (values / values.shift(n) - 1) * 100
    if how == "vs_sma":
        return (values / values.rolling(n).mean() - 1) * 100
    if how == "sma_cross":
        return (values.rolling(n).mean() / values.rolling(slow).mean() - 1) * 100
    if how == "rsi":
        return _rsi(values, n)
    if how == "macd":
        line = values.ewm(span=12, adjust=False, min_periods=26).mean() - values.ewm(span=26, adjust=False, min_periods=26).mean()
        return (line - line.ewm(span=9, adjust=False, min_periods=9).mean()) / values * 100
    if how == "vs_high":
        return (values / values.shift(1).rolling(n).max() - 1) * 100
    if how == "vs_low":
        return (values / values.shift(1).rolling(n).min() - 1) * 100
    if how == "volatility":
        return values.pct_change().rolling(n).std() * np.sqrt(252) * 100
    if how == "vs_vwap":
        typical = (bars["high"] + bars["low"] + bars["close"]) / 3
        vwap = (typical * bars["volume"]).rolling(n).sum() / bars["volume"].rolling(n).sum()
        return (values / vwap - 1) * 100
    raise ValueError(f"unknown measure {how!r}")
