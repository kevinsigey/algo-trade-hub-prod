"""Spread / z-score / percentile rules (critique 2026-10-31, roadmap 8: the K-Shape monitor's signal)."""
import numpy as np
import pandas as pd
import pytest

from tradehub.workshop import signals
from tradehub.workshop.engine import condition_mask, tickers_for
from tradehub.workshop.spec import IdeaSpec

IDX = pd.bdate_range("2018-01-02", periods=600)


def s(vals):
    return pd.Series(vals, index=pd.bdate_range("2020-01-01", periods=len(vals)), dtype=float)


def test_zscore_known():
    out = signals.measure(s([1, 2, 3, 4, 10]), "zscore", 5)
    x = np.array([1, 2, 3, 4, 10.0])
    assert out.iloc[-1] == pytest.approx((10 - x.mean()) / x.std(ddof=1))
    assert out.iloc[:4].isna().all()


def test_percentile_is_todays_rank_in_the_window():
    out = signals.measure(s([5, 1, 2, 3, 4]), "percentile", 5)
    assert out.iloc[-1] == pytest.approx(80.0)  # 4 is at or above 4 of 5 values
    assert signals.measure(s([1, 2, 3, 4, 5]), "percentile", 5).iloc[-1] == pytest.approx(100.0)


def test_spread_series_is_the_log_ratio_of_equal_weight_baskets():
    rng = np.random.default_rng(0)
    px = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0, 0.01, len(IDX))) for t in ("SPY", "QQQ", "IWM", "RL", "WSM", "LULU", "NKE")},
                      index=IDX)
    from tradehub.workshop.engine import spread_series
    got = spread_series("RL+WSM/LULU+NKE", px)
    want = np.log(px[["RL", "WSM"]]).mean(axis=1) - np.log(px[["LULU", "NKE"]]).mean(axis=1)
    pd.testing.assert_series_equal(got, want, check_names=False)


def k_shape(**cond):
    c = {"source": "spread", "series": "rl+wsm+abnb/lulu+nke", "measure": "zscore", "lookback_days": 60, "op": ">", "threshold": 2, **cond}
    return IdeaSpec(title="K-Shape spread stretched", hold=["RL", "WSM", "ABNB"], short=["LULU", "NKE"], claim="beats_benchmark",
                    rules={"enter": {"conditions": [c]}})


def test_spread_condition_validates_and_reads_its_tickers():
    sp = k_shape()
    assert sp.rules.enter.conditions[0].series == "RL+WSM+ABNB/LULU+NKE"
    assert {"RL", "WSM", "ABNB", "LULU", "NKE"} <= set(tickers_for(sp))
    for bad in ("RL+WSM", "RL//NKE", "RL+/NKE", "R;L/NKE"):
        with pytest.raises(ValueError):
            k_shape(series=bad)
    with pytest.raises(ValueError):
        k_shape(measure="rsi")  # spreads take level, change, vs_sma, volatility, zscore, percentile


def test_spread_rule_mask_uses_the_prior_close():
    rng = np.random.default_rng(1)
    px = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0, 0.01, len(IDX))) for t in ("SPY", "QQQ", "IWM", "RL", "WSM", "ABNB", "LULU", "NKE")},
                      index=IDX)
    from tradehub.workshop.engine import spread_series
    z = signals.measure(spread_series("RL+WSM+ABNB/LULU+NKE", px), "zscore", 60)
    want = ((z > 2) & z.notna()).shift(1, fill_value=False)
    assert (condition_mask(k_shape(), px, {}) == want).all()
