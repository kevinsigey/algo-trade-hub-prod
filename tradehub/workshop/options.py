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


def leg_returns(kind: Literal["call", "put"], side: int, closes: pd.Series, vol: pd.Series,
                rate: pd.Series, div_yield: float, *, days_to_expiry: int,
                strike_pct: float, roll_days_left: int) -> pd.DataFrame:
    closes = closes.astype(float)
    vol_ff = vol.astype(float).ffill()
    rate_ff = rate.astype(float).ffill()
    idx = closes.index
    n = len(idx)
    price_out = [float("nan")] * n
    ret_out = [0.0] * n
    strike_out = [float("nan")] * n
    expiry_out = [pd.NaT] * n
    rolled_out = [False] * n

    cur_strike = None
    cur_expiry = None
    prev_price = None
    prev_close = None

    for i in range(n):
        day = idx[i]
        close = float(closes.iloc[i])
        v = vol_ff.iloc[i]
        r = rate_ff.iloc[i]
        valid = pd.notna(v) and pd.notna(r)
        v = float(v) if valid else float("nan")
        r = float(r) if valid else float("nan")
        days_left = None
        if cur_expiry is not None:
            days_left = (cur_expiry - day).days

        roll = (cur_strike is not None and days_left is not None
                and days_left <= roll_days_left and days_left < days_to_expiry)

        if roll and valid:
            old_price_today = bs_price(kind, close, cur_strike, days_left / 365.0, r, div_yield, v)
            if prev_price is not None and prev_close is not None and prev_close != 0:
                ret_out[i] = side * (old_price_today - prev_price) / prev_close
            else:
                ret_out[i] = 0.0
            # open new
            new_strike = close * strike_pct / 100.0
            new_expiry = day + pd.Timedelta(days=int(days_to_expiry))
            new_price = bs_price(kind, close, new_strike, days_to_expiry / 365.0, r, div_yield, v)
            cur_strike = new_strike
            cur_expiry = new_expiry
            price_out[i] = new_price
            strike_out[i] = new_strike
            expiry_out[i] = new_expiry
            rolled_out[i] = True
            prev_price = new_price
            prev_close = close
            continue

        if cur_strike is None:
            if valid:
                new_strike = close * strike_pct / 100.0
                new_expiry = day + pd.Timedelta(days=int(days_to_expiry))
                new_price = bs_price(kind, close, new_strike, days_to_expiry / 365.0, r, div_yield, v)
                cur_strike = new_strike
                cur_expiry = new_expiry
                price_out[i] = new_price
                strike_out[i] = new_strike
                expiry_out[i] = new_expiry
                rolled_out[i] = False
                prev_price = new_price
                prev_close = close
            else:
                price_out[i] = float("nan")
                strike_out[i] = float("nan")
                expiry_out[i] = pd.NaT
                rolled_out[i] = False
                ret_out[i] = 0.0
                # keep prev_* None
            continue

        # existing contract
        if not valid:
            price_out[i] = float("nan")
            strike_out[i] = cur_strike
            expiry_out[i] = cur_expiry
            rolled_out[i] = False
            ret_out[i] = 0.0
            continue

        dl = (cur_expiry - day).days
        if dl < 0:
            dl = 0
        price = bs_price(kind, close, cur_strike, dl / 365.0, r, div_yield, v)
        if prev_price is not None and prev_close is not None and prev_close != 0:
            ret_out[i] = side * (price - prev_price) / prev_close
        else:
            ret_out[i] = 0.0
        price_out[i] = price
        strike_out[i] = cur_strike
        expiry_out[i] = cur_expiry
        rolled_out[i] = False
        prev_price = price
        prev_close = close

    df = pd.DataFrame({
        "price": price_out,
        "ret": ret_out,
        "strike": strike_out,
        "expiry": expiry_out,
        "rolled": rolled_out,
    }, index=idx)
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce")
    df["rolled"] = df["rolled"].astype(bool)
    return df
