"""An idea tested inside a portfolio: a share of the idea plus a core, judged against the core (Kevin, 2026-10-31)."""
import numpy as np
import pandas as pd
import pytest

from tradehub.workshop.engine import claim_check, daily_frame, run_test, target_and_reason, tickers_for
from tradehub.workshop.spec import IdeaSpec

IDX = pd.bdate_range("2010-01-04", periods=3000)


def market(seed=0):
    rng = np.random.default_rng(seed)
    spy = rng.normal(0.0003, 0.01, len(IDX))
    px = {"SPY": spy, "QQQ": spy * 1.2 + rng.normal(0, 0.004, len(IDX)), "IWM": spy * 1.1 + rng.normal(0, 0.005, len(IDX)),
          "GLD": -0.3 * spy + rng.normal(0.0002, 0.009, len(IDX)), "TLT": -0.2 * spy + rng.normal(0.0001, 0.008, len(IDX))}
    return pd.DataFrame({t: 100 * np.cumprod(1 + r) for t, r in px.items()}, index=IDX)


FALL = {"source": "price", "series": "SPY", "measure": "pct_change", "lookback_days": 10, "op": "<", "threshold": 0}


def spec(**over):
    base = {"title": "Gold when stocks fall, inside a SPY portfolio", "hold": ["GLD"], "claim": "smoother_ride",
            "start": "2010-01-04", "rules": {"enter": {"conditions": [FALL]}}}
    return IdeaSpec.model_validate({**base, **over})


def test_portfolio_spec_bounds():
    s = spec(portfolio={"core": ["spy"], "idea_share": 0.4})
    assert s.portfolio.core == ["SPY"] and s.portfolio.idea_share == 0.4
    for bad in ({"core": [], "idea_share": 0.5}, {"core": ["SPY"], "idea_share": 0.95}, {"core": ["SPY"], "idea_share": 0.0}):
        with pytest.raises(ValueError):
            spec(portfolio=bad)
    assert "TLT" in tickers_for(spec(portfolio={"core": ["SPY", "TLT"], "idea_share": 0.5}))


def test_the_daily_return_is_the_blend():
    closes = market()
    alone = daily_frame(spec(), closes, {})
    mixed = daily_frame(spec(portfolio={"core": ["SPY", "TLT"], "idea_share": 0.3}), closes, {})
    core = closes[["SPY", "TLT"]].pct_change().loc[alone.index].mean(axis=1)
    np.testing.assert_allclose(mixed["ret"], 0.3 * alone["ret"] + 0.7 * core, atol=1e-12)
    assert (mixed["on"] == alone["on"]).all()


def test_the_verdict_judges_the_blend():
    closes = market(1)
    s = spec(portfolio={"core": ["SPY"], "idea_share": 0.5})
    out = run_test(s, closes, {}, variations=1, seed=3, permutations=200)
    df = daily_frame(s, closes, {})
    k = int(len(df) * (1 - s.unseen_fraction))
    assert claim_check(s, df.iloc[k:])["value"] == pytest.approx(out["claim"]["unseen"]["value"])
    assert out["curve"][-1]["idea"] == pytest.approx(((1 + df["ret"]).prod() - 1) * 100)


def test_morning_targets_hold_the_core_share_in_or_out():
    closes = market(2)
    s = spec(portfolio={"core": ["SPY"], "idea_share": 0.5})
    plain = spec()
    weights, _ = target_and_reason(s, closes, {})
    alone, _ = target_and_reason(plain, closes, {})
    if alone:  # the rule has gold in today
        assert weights == pytest.approx({"GLD": 0.5, "SPY": 0.5})
    else:
        assert weights == pytest.approx({"SPY": 0.5})
    both = spec(hold=["SPY"], rules=None, portfolio={"core": ["SPY"], "idea_share": 0.5})
    assert target_and_reason(both, closes, {})[0] == pytest.approx({"SPY": 1.0})  # overlapping legs add up


def test_intraday_stops_are_not_for_portfolio_ideas():
    # A resting stop on the leg would also sell the core's shares of the same ticker.
    with pytest.raises(ValueError, match="portfolio"):
        spec(hold=["SPY"], exits={"stop_loss_pct": 5, "mode": "intraday"}, portfolio={"core": ["SPY"], "idea_share": 0.5})
