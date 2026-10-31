import numpy as np
import pandas as pd
import pytest

from tradehub.workshop.options import (
    VOL_INDEX,
    bs_delta,
    bs_price,
    bs_vega,
    implied_vol_series,
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
