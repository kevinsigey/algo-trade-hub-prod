import numpy as np
import pandas as pd
import pytest

from tradehub.workshop.signals import measure

IDX = pd.bdate_range("2020-01-01", periods=6)


def s(values):
    return pd.Series(values, index=pd.bdate_range("2020-01-01", periods=len(values)), dtype=float)


def test_vs_sma_known():
    assert measure(s([1, 2, 3, 4]), "vs_sma", 2).iloc[-1] == pytest.approx((4 / 3.5 - 1) * 100)


def test_sma_cross_known():
    out = measure(s([1, 2, 3, 4]), "sma_cross", 2, slow=4)
    assert out.iloc[-1] == pytest.approx((3.5 / 2.5 - 1) * 100) and out.iloc[:3].isna().all()


def test_rsi_all_up_is_100_all_down_is_0():
    assert measure(s(range(1, 30)), "rsi", 14).iloc[-1] == pytest.approx(100)
    assert measure(s(range(30, 1, -1)), "rsi", 14).iloc[-1] == pytest.approx(0)


def test_rsi_matches_wilder_reference():
    # changes +1 -1 +2 +1 -1; seed = simple means of the first 3, then Wilder's (prev*(N-1)+x)/N.
    out = measure(s([10, 11, 10, 12, 13, 12]), "rsi", 3)
    assert out.iloc[:3].isna().all()
    assert out.iloc[3:].tolist() == pytest.approx([75.0, 100 - 100 / 5.5, 100 - 100 / (1 + (2 / 3) / (13 / 27))])


def test_macd_zero_on_flat():
    assert measure(s([50.0] * 60), "macd", 1).dropna().abs().max() == pytest.approx(0)


def test_vs_high_breakout():
    out = measure(s([10, 12, 11, 11.5, 13]), "vs_high", 3)
    assert out.iloc[-1] > 0 and out.iloc[-2] <= 0
    assert measure(s([10, 12, 11, 11.5, 9]), "vs_low", 3).iloc[-1] < 0


def test_volatility_constant_returns_zero():
    assert measure(s([100 * 1.01 ** i for i in range(30)]), "volatility", 20).iloc[-1] == pytest.approx(0, abs=1e-9)


def test_vwap_known():
    bars = pd.DataFrame({"high": [11, 13], "low": [9, 11], "close": [10, 12], "volume": [100, 300]},
                        index=pd.bdate_range("2020-01-01", periods=2), dtype=float)
    vwap = (10 * 100 + 12 * 300) / 400
    assert measure(bars["close"], "vs_vwap", 2, bars=bars).iloc[-1] == pytest.approx((12 / vwap - 1) * 100)


ALL = [("level", {}), ("change", {}), ("pct_change", {}), ("vs_sma", {}), ("sma_cross", {"slow": 30}),
       ("rsi", {}), ("macd", {}), ("vs_high", {}), ("vs_low", {}), ("volatility", {}), ("vs_vwap", {})]


@pytest.mark.parametrize("how,kw", ALL)
def test_no_signal_reads_the_future(how, kw):
    rng = np.random.default_rng(1)
    close = s(100 * np.cumprod(1 + rng.normal(0, 0.01, 120)))
    bars = pd.DataFrame({"high": close * 1.01, "low": close * 0.99, "close": close,
                         "volume": rng.integers(1, 1000, 120).astype(float)})
    base = measure(close, how, 10, bars=bars, **kw)
    close2, bars2 = close.copy(), bars.copy()
    close2.iloc[-1] *= 1.5
    bars2.iloc[-1] = bars2.iloc[-1] * 1.5
    moved = measure(close2, how, 10, bars=bars2, **kw)
    pd.testing.assert_series_equal(base.iloc[:-1], moved.iloc[:-1])
