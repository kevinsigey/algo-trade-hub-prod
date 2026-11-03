"""Options calibration (design doc 2026-10-31 section 2; handover item 4,
2026-11-03): one flat volatility for every strike made puts too cheap and
covered calls too rich, backtests paid no bid-ask spread, and no model
price had ever been compared with a real one. The fixes: implied-vol
inversion, a fitted skew curve, half-spread charged on every option trade,
and a calibration record shipped with the code that verdicts quote.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradehub.workshop import calibration
from tradehub.workshop.options import (bs_price, implied_vol_from_price,
                                       leg_returns, skew_factor)

COEFFS = {"a": 0.0, "b": -0.5, "c": 0.0, "d": 0.0}


def test_implied_vol_inversion_round_trips():
    for kind, strike in (("call", 105.0), ("put", 95.0), ("call", 100.0)):
        px = bs_price(kind, 100.0, strike, 30 / 365, 0.02, 0.01, 0.25)
        iv = implied_vol_from_price(kind, px, 100.0, strike, 30 / 365, 0.02, 0.01)
        assert iv == pytest.approx(0.25, abs=1e-4)


def test_implied_vol_below_intrinsic_is_none():
    # A real price under intrinsic value is a bad print, not a volatility.
    assert implied_vol_from_price("call", 4.0, 100.0, 90.0, 30 / 365, 0.02, 0.0) is None
    assert implied_vol_from_price("put", -1.0, 100.0, 90.0, 30 / 365, 0.02, 0.0) is None


def test_skew_factor_lifts_otm_puts_and_lowers_otm_calls():
    assert skew_factor(1.0, 30, COEFFS) == pytest.approx(1.0)          # at the money: untouched
    assert skew_factor(0.95, 30, COEFFS) == pytest.approx(1 + 0.5 * 0.0513, abs=1e-3)  # put side: up
    assert skew_factor(1.05, 30, COEFFS) < 1.0                          # call side: down
    assert skew_factor(0.95, 30, {"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0}) == 1.0


def _flat(days: int = 40):
    idx = pd.bdate_range("2020-01-01", periods=days)
    return idx, pd.Series(100.0, index=idx), pd.Series(0.2, index=idx), pd.Series(0.05, index=idx)


def test_open_day_pays_half_the_spread():
    idx, closes, vol, rate = _flat(10)
    df = leg_returns("call", 1, closes, vol, rate, 0.0, days_to_expiry=30, strike_pct=100,
                     roll_days_left=5, spread_frac=0.04)
    premium = bs_price("call", 100.0, 100.0, 30 / 365, 0.05, 0.0, 0.2)
    assert df["ret"].iloc[0] == pytest.approx(-0.5 * 0.04 * premium / 100.0)
    # A sold leg pays the spread too (it is not the mirror image any more).
    sold = leg_returns("call", -1, closes, vol, rate, 0.0, days_to_expiry=30, strike_pct=100,
                       roll_days_left=5, spread_frac=0.04)
    assert sold["ret"].iloc[0] == pytest.approx(-0.5 * 0.04 * premium / 100.0)


def test_roll_day_pays_spread_on_both_legs():
    idx, closes, vol, rate = _flat(40)
    plain = leg_returns("call", 1, closes, vol, rate, 0.0, days_to_expiry=30, strike_pct=100,
                        roll_days_left=5)
    costed = leg_returns("call", 1, closes, vol, rate, 0.0, days_to_expiry=30, strike_pct=100,
                         roll_days_left=5, spread_frac=0.04)
    rolled = costed.index[costed["rolled"]]
    assert len(rolled) >= 1
    day = rolled[0]
    drag = plain.loc[day, "ret"] - costed.loc[day, "ret"]
    # Closing the old contract plus opening the new one: two half-spreads.
    assert drag > 0.5 * 0.04 * costed.loc[day, "price"] / 100.0


def test_skew_raises_the_otm_put_price():
    idx, closes, vol, rate = _flat(10)
    flat = leg_returns("put", 1, closes, vol, rate, 0.0, days_to_expiry=30, strike_pct=90,
                       roll_days_left=5)
    skewed = leg_returns("put", 1, closes, vol, rate, 0.0, days_to_expiry=30, strike_pct=90,
                         roll_days_left=5, skew_coeffs=COEFFS)
    assert skewed["price"].iloc[0] > flat["price"].iloc[0]


def test_shipped_calibration_covers_the_live_underlyings():
    cal = calibration.load_calibration()
    for ticker in ("SPY", "NVDA"):
        entry = calibration.for_underlying(ticker)
        assert entry is not None, ticker
        assert 0 < entry["spread_frac"] < 0.25
        assert entry["median_err_check_pct"] is not None and entry["n_check"] >= 10
    assert calibration.for_underlying("ZZZZ") is None
    assert set(cal["skew"]) >= {"a", "b", "c", "d"}


def test_a_run_quotes_its_calibration_line():
    from tradehub.workshop.engine import run_test
    from tradehub.workshop.spec import IdeaSpec

    days = pd.bdate_range("2015-01-02", periods=1500)
    rising = 100.0 * 1.003 ** np.arange(len(days))
    closes = pd.DataFrame({"SPY": rising, "QQQ": rising, "IWM": rising}, index=days)
    fred = {"VIXCLS": pd.Series(20.0, index=days), "DTB3": pd.Series(2.0, index=days)}
    spec = IdeaSpec(title="Test idea", claim="beats_benchmark", hold=[],
                    options=[{"underlying": "SPY", "kind": "call", "side": "buy"}])
    result = run_test(spec, closes, fred, variations=1, seed=1)
    leg = result["options"]["legs"][0]
    assert leg["calibration"]["median_error_pct"] is not None
    assert any("Model vs Alpaca real" in n for n in result["notes"])
