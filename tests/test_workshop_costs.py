"""Short-borrow cost and slippage (critique 2026-10-31, roadmap 7)."""
import numpy as np
import pandas as pd
import pytest

from tradehub.workshop.engine import daily_frame
from tradehub.workshop.spec import IdeaSpec

IDX = pd.bdate_range("2015-01-02", periods=800)


def market(seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(IDX))) for t in ("SPY", "QQQ", "IWM", "AAA")},
                        index=IDX)


def spec(**over):
    return IdeaSpec.model_validate({"title": "Long AAA short QQQ", "hold": ["AAA"], "short": ["QQQ"], "claim": "beats_benchmark",
                                    "start": "2015-01-02", **over})


def test_borrow_is_charged_daily_on_the_short_share():
    closes = market()
    free = daily_frame(spec(borrow_bps_yr=0), closes, {})
    paid = daily_frame(spec(borrow_bps_yr=252), closes, {})  # 1 bp a day on the short leg
    # one long + one short, equal weight: the short is half the sleeve, so 0.5 bp a day
    np.testing.assert_allclose(free["ret"] - paid["ret"], 0.5e-4, atol=1e-12)


def test_no_short_no_borrow():
    closes = market(1)
    long_only = {"hold": ["AAA"], "short": []}
    np.testing.assert_allclose(daily_frame(spec(**long_only, borrow_bps_yr=0), closes, {})["ret"],
                               daily_frame(spec(**long_only, borrow_bps_yr=500), closes, {})["ret"])


def test_slippage_adds_to_the_cost_per_switch():
    closes = market(2)
    rule = {"rules": {"enter": {"conditions": [{"source": "price", "series": "SPY", "measure": "pct_change",
                                                "lookback_days": 5, "op": ">", "threshold": 0}]}}, "short": []}
    a = daily_frame(spec(**rule, cost_bps=10, slippage_bps=15), closes, {})
    b = daily_frame(spec(**rule, cost_bps=25, slippage_bps=0), closes, {})
    np.testing.assert_allclose(a["ret"], b["ret"], atol=1e-12)


def test_defaults():
    s = spec()
    assert s.borrow_bps_yr == 25 and s.slippage_bps == 0
    with pytest.raises(ValueError):
        spec(borrow_bps_yr=-1)
