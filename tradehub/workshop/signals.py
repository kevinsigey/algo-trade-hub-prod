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
    if how == "zscore":
        roll = values.rolling(n)
        return (values - roll.mean()) / roll.std(ddof=1)
    if how == "percentile":  # today's rank in the last N values: % of them at or below today
        return values.rolling(n).apply(lambda w: (w <= w[-1]).mean() * 100, raw=True)
    if how == "vs_vwap":
        typical = (bars["high"] + bars["low"] + bars["close"]) / 3
        vwap = (typical * bars["volume"]).rolling(n).sum() / bars["volume"].rolling(n).sum()
        return (values / vwap - 1) * 100
    raise ValueError(f"unknown measure {how!r}")


def analyst_measure(actions: pd.DataFrame, idx: pd.DatetimeIndex, how: str, lookback: int, *,
                    close: pd.Series | None = None) -> pd.Series:
    """Analyst signals on trading days `idx`. Each action counts on the trading day it happened, or the next one.
    net_upgrades: ups minus downs over the last N days. target_upside: (mean target set in the last N days / close
    - 1) x 100, NaN when no target was set. Both NaN before the first action (the engine lags them 2 days).
    Actions shortly before idx[0] still count while inside the window (weekdays stand in for trading days there)."""
    if len(idx) == 0:
        return pd.Series(np.nan, index=idx)
    early = actions.index.normalize()
    early = early[early < idx[0]]
    prefix = pd.bdate_range(max(early.min(), idx[0] - pd.Timedelta(days=2 * lookback + 14)), idx[0],
                            inclusive="left") if len(early) else pd.DatetimeIndex([])
    days = prefix.append(idx)
    pos = days.searchsorted(actions.index.normalize(), side="left")
    keep = (pos < len(days)) & (actions.index.normalize() >= days[0])
    acts, pos = actions[keep], pos[keep]
    first = pos.min() if len(pos) else len(days)
    if how == "net_upgrades":
        daily = np.zeros(len(days))
        np.add.at(daily, pos, (acts["action"] == "up").to_numpy(float) - (acts["action"] == "down").to_numpy(float))
        out = pd.Series(daily, index=days).rolling(lookback, min_periods=1).sum()
    else:  # target_upside
        has = acts["target"].notna().to_numpy()
        total, count = np.zeros(len(days)), np.zeros(len(days))
        np.add.at(total, pos[has], acts["target"].to_numpy()[has])
        np.add.at(count, pos[has], 1.0)
        n = pd.Series(count, index=days).rolling(lookback, min_periods=1).sum()
        mean = pd.Series(total, index=days).rolling(lookback, min_periods=1).sum() / n.where(n > 0)
        out = (mean / close.reindex(days) - 1) * 100
    out.iloc[:first] = np.nan
    return out.iloc[len(prefix):]
