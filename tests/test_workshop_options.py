import numpy as np
import pandas as pd
import pytest

from tradehub.workshop.options import (
    VOL_INDEX,
    bs_delta,
    bs_price,
    bs_vega,
    implied_vol_series,
    leg_returns,
)


def test_bs_known_values():
    c = bs_price("call", 100, 100, 1, 0.05, 0, 0.2)
    p = bs_price("put", 100, 100, 1, 0.05, 0, 0.2)
    assert c == pytest.approx(10.4506, abs=1e-3)
    assert p == pytest.approx(5.5735, abs=1e-3)


def test_put_call_parity():
    spots = [80.0, 100.0, 120.0]
    strikes = [90.0, 100.0, 110.0]
    years = [0.25, 0.5, 1.0]
    for S in spots:
        for K in strikes:
            for T in years:
                r, q, sig = 0.05, 0.02, 0.25
                call = bs_price("call", S, K, T, r, q, sig)
                put = bs_price("put", S, K, T, r, q, sig)
                lhs = call - put
                rhs = S * np.exp(-q * T) - K * np.exp(-r * T)
                assert lhs == pytest.approx(rhs, abs=1e-9)


def test_expired_is_intrinsic():
    assert bs_price("call", 100, 90, 0, 0.05, 0.0, 0.2) == 10.0
    assert bs_price("put", 100, 90, 0, 0.05, 0.0, 0.2) == 0.0
    assert bs_price("call", 100, 105, -1, 0.05, 0.0, 0.2) == 0.0


def test_delta_bounds_and_vega_positive():
    d_call = bs_delta("call", 100, 100, 1, 0.05, 0, 0.2)
    d_put = bs_delta("put", 100, 100, 1, 0.05, 0, 0.2)
    assert 0 <= d_call <= 1
    assert -1 <= d_put <= 0
    v = bs_vega("call", 100, 100, 1, 0.05, 0, 0.2)
    assert v > 0


def test_vol_nonpositive_raises():
    with pytest.raises(ValueError):
        bs_price("call", 100, 100, 1, 0.05, 0, 0)
    with pytest.raises(ValueError):
        bs_vega("call", 100, 100, 1, 0.05, 0, 0)


def test_vol_from_index_and_fallback():
    idx = pd.bdate_range("2020-01-01", periods=5)
    closes = pd.Series([100.0] * 5, index=idx)
    fred = {"VIXCLS": pd.Series([20.0] * 3, index=pd.bdate_range("2019-12-30", periods=3))}
    vol, label = implied_vol_series("SPY", closes, fred)
    assert label == "vol index VIXCLS"
    assert (vol == 0.20).all()
    vol2, label2 = implied_vol_series("XYZ", closes, fred)
    assert label2 == "cruder model: realised vol x 1.1"


def test_vol_index_dict():
    assert VOL_INDEX["SPY"] == "VIXCLS"
    assert VOL_INDEX["AAPL"] == "VXAPLCLS"


def test_leg_prices_match_bs_each_day():
    idx = pd.bdate_range("2020-01-01", periods=10)
    closes = pd.Series(100.0, index=idx)
    vol = pd.Series(0.2, index=idx)
    rate = pd.Series(0.05, index=idx)
    df = leg_returns("call", 1, closes, vol, rate, 0.0, days_to_expiry=30, strike_pct=100, roll_days_left=5)
    for i in [0, 5]:
        row = df.iloc[i]
        day = idx[i]
        days_left = (row["expiry"] - day).days
        exp = bs_price("call", closes.iloc[i], row["strike"], days_left / 365.0,
                       rate.iloc[i], 0.0, vol.iloc[i])
        assert row["price"] == pytest.approx(exp)


def test_leg_rolls_before_expiry():
    idx = pd.bdate_range("2020-01-01", periods=40)
    closes = pd.Series(100.0 + np.arange(len(idx)) * 0.5, index=idx)
    vol = pd.Series(0.2, index=idx)
    rate = pd.Series(0.05, index=idx)
    df = leg_returns("call", 1, closes, vol, rate, 0.0, days_to_expiry=30, strike_pct=100, roll_days_left=5)
    assert bool(df["rolled"].any())
    rolled_days = df.index[df["rolled"]]
    day = rolled_days[0]
    assert df.loc[day, "strike"] == pytest.approx(closes.loc[day] * 1.0)


def test_sold_leg_is_negative_of_bought_leg():
    idx = pd.bdate_range("2020-01-01", periods=10)
    closes = pd.Series(100.0 + np.arange(len(idx)), index=idx, dtype=float)
    vol = pd.Series(0.2, index=idx)
    rate = pd.Series(0.05, index=idx)
    bought = leg_returns("call", 1, closes, vol, rate, 0.0, days_to_expiry=30, strike_pct=100, roll_days_left=5)
    sold = leg_returns("call", -1, closes, vol, rate, 0.0, days_to_expiry=30, strike_pct=100, roll_days_left=5)
    assert np.allclose(sold["ret"].to_numpy(), -bought["ret"].to_numpy(), equal_nan=True)


def test_leg_ret_sums_to_price_change_without_rolls():
    idx = pd.bdate_range("2020-01-01", periods=20)
    closes = pd.Series(100.0 + np.arange(len(idx)) * 2.0, index=idx, dtype=float)
    vol = pd.Series(0.2, index=idx)
    rate = pd.Series(0.05, index=idx)
    df = leg_returns("call", 1, closes, vol, rate, 0.0, days_to_expiry=100, strike_pct=100, roll_days_left=5)
    assert not bool(df["rolled"].any())
    prev_close = closes.shift(1)
    s = (df["ret"] * prev_close).sum()
    assert s == pytest.approx(df["price"].iloc[-1] - df["price"].iloc[0])
