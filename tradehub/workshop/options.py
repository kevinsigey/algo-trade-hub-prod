"""Pure Black-Scholes pricing core for Workshop options (numpy/scipy only, no network)."""

from __future__ import annotations

import math
from typing import Literal

import pandas as pd
from scipy.stats import norm

VOL_INDEX: dict[str, str] = {
    "SPY": "VIXCLS",
    "QQQ": "VXNCLS",
    "IWM": "RVXCLS",
    "GLD": "GVZCLS",
    "USO": "OVXCLS",
    "EEM": "VXEEMCLS",
    "AAPL": "VXAPLCLS",
}


def _intrinsic(kind: str, spot: float, strike: float) -> float:
    if kind == "call":
        return float(max(spot - strike, 0.0))
    return float(max(strike - spot, 0.0))


def bs_price(kind: Literal["call", "put"], spot: float, strike: float, years: float,
             rate: float, div_yield: float, vol: float) -> float:
    if years <= 0:
        return _intrinsic(kind, spot, strike)
    if vol <= 0:
        raise ValueError("vol must be positive")
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - div_yield + 0.5 * vol * vol) * years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    disc_q = math.exp(-div_yield * years)
    disc_r = math.exp(-rate * years)
    if kind == "call":
        return float(spot * disc_q * norm.cdf(d1) - strike * disc_r * norm.cdf(d2))
    return float(strike * disc_r * norm.cdf(-d2) - spot * disc_q * norm.cdf(-d1))


def bs_delta(kind: Literal["call", "put"], spot: float, strike: float, years: float,
             rate: float, div_yield: float, vol: float) -> float:
    if years <= 0:
        if kind == "call":
            return 1.0 if spot > strike else (0.5 if spot == strike else 0.0)
        return -1.0 if spot < strike else (-0.5 if spot == strike else 0.0)
    if vol <= 0:
        raise ValueError("vol must be positive")
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - div_yield + 0.5 * vol * vol) * years) / (vol * sqrt_t)
    disc_q = math.exp(-div_yield * years)
    if kind == "call":
        return float(disc_q * norm.cdf(d1))
    return float(disc_q * (norm.cdf(d1) - 1.0))


def bs_vega(kind: Literal["call", "put"], spot: float, strike: float, years: float,
            rate: float, div_yield: float, vol: float) -> float:
    if years <= 0:
        return 0.0
    if vol <= 0:
        raise ValueError("vol must be positive")
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - div_yield + 0.5 * vol * vol) * years) / (vol * sqrt_t)
    disc_q = math.exp(-div_yield * years)
    return float(spot * disc_q * sqrt_t * norm.pdf(d1))


def implied_vol_series(ticker: str, closes: pd.Series, fred: dict[str, pd.Series]) -> tuple[pd.Series, str]:
    if ticker in VOL_INDEX:
        vid = VOL_INDEX[ticker]
        if vid in fred and fred[vid] is not None:
            s = fred[vid].sort_index()
            aligned = s.reindex(closes.index, method="ffill")
            out = (aligned / 100.0).astype(float)
            out.index = closes.index
            return out, f"vol index {vid}"
    rets = closes.pct_change()
    vol = rets.rolling(21).std() * math.sqrt(252) * 1.1
    vol = vol.reindex(closes.index)
    return vol.astype(float), "cruder model: realised vol x 1.1"
