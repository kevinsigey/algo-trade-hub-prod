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


def implied_vol_from_price(kind: Literal["call", "put"], price: float, spot: float, strike: float,
                           years: float, rate: float, div_yield: float) -> float | None:
    """Invert Black-Scholes for the volatility a real price implies (bisection).
    None when the price carries no invertible time value (at/past expiry, or
    below intrinsic -- a bad print, not a volatility)."""
    if years <= 0 or price <= 0 or spot <= 0 or strike <= 0:
        return None
    if price < _intrinsic(kind, spot, strike) - 1e-9:
        return None
    lo, hi = 0.01, 3.0
    if bs_price(kind, spot, strike, years, rate, div_yield, hi) < price:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if bs_price(kind, spot, strike, years, rate, div_yield, mid) < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def skew_factor(moneyness: float, days_left: float, coeffs: dict) -> float:
    """The fitted skew curve as a volatility multiplier: relative adjustment
    a + b*ln(m) + c*ln(m)^2 + d*(days/30 - 1), clamped to a sane band. Fitted
    once on real 2024-2025 prices and checked on 2026 (calibration.json);
    never re-fitted on the years a test judges."""
    lnm = math.log(moneyness) if moneyness > 0 else 0.0
    rel = (coeffs.get("a", 0.0) + coeffs.get("b", 0.0) * lnm + coeffs.get("c", 0.0) * lnm * lnm
           + coeffs.get("d", 0.0) * (days_left / 30.0 - 1.0))
    return min(2.5, max(0.5, 1.0 + rel))


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
                strike_pct: float, roll_days_left: int,
                skew_coeffs: dict | None = None, spread_frac: float = 0.0) -> pd.DataFrame:
    """Daily model P&L for one rolling leg. With a calibration (skew_coeffs /
    spread_frac, from workshop.calibration), each pricing goes through the
    fitted skew curve and every trade -- the open, and both sides of a roll --
    pays half the typical spread as a fraction of premium, in the same
    per-$1-of-underlying units as the returns (the open day normalizes on its
    own close; later trades on the previous close, like the marks)."""
    closes = closes.astype(float)
    vol_ff = vol.astype(float).ffill()
    rate_ff = rate.astype(float).ffill()

    def _v(v: float, strike: float, spot: float, days: float) -> float:
        return v * skew_factor(strike / spot, days, skew_coeffs) if skew_coeffs and spot > 0 else v
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
            old_price_today = bs_price(kind, close, cur_strike, days_left / 365.0, r, div_yield,
                                       _v(v, cur_strike, close, days_left))
            # open new
            new_strike = close * strike_pct / 100.0
            new_expiry = day + pd.Timedelta(days=int(days_to_expiry))
            new_price = bs_price(kind, close, new_strike, days_to_expiry / 365.0, r, div_yield,
                                 _v(v, new_strike, close, days_to_expiry))
            if prev_price is not None and prev_close is not None and prev_close != 0:
                ret_out[i] = side * (old_price_today - prev_price) / prev_close
                if spread_frac:
                    ret_out[i] -= 0.5 * spread_frac * (old_price_today + new_price) / prev_close
            else:
                ret_out[i] = 0.0
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
                new_price = bs_price(kind, close, new_strike, days_to_expiry / 365.0, r, div_yield,
                                     _v(v, new_strike, close, days_to_expiry))
                cur_strike = new_strike
                cur_expiry = new_expiry
                price_out[i] = new_price
                strike_out[i] = new_strike
                expiry_out[i] = new_expiry
                rolled_out[i] = False
                if spread_frac and close:
                    ret_out[i] = -0.5 * spread_frac * new_price / close
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
        price = bs_price(kind, close, cur_strike, dl / 365.0, r, div_yield,
                         _v(v, cur_strike, close, dl))
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
