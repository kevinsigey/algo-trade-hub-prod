"""Option legs (§2.3): the spec's cover rules and the engine's model-priced streams.

Engine fixtures are synthetic and deterministic: business days, a vol index series and
DTB3 in the fred dict, closes per ticker. A flat underlying makes a bought call bleed
time decay; a rising one makes it pay; a covered call truncates the rise.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from tradehub.workshop.engine import daily_frame, run_test
from tradehub.workshop.spec import IdeaSpec, OptionLeg

DAYS = pd.bdate_range("2015-01-02", periods=1500)


def closes_for(paths: dict[str, np.ndarray]) -> pd.DataFrame:
    frame = pd.DataFrame(paths, index=DAYS)
    return frame


def fred() -> dict[str, pd.Series]:
    return {"VIXCLS": pd.Series(20.0, index=DAYS), "DTB3": pd.Series(2.0, index=DAYS)}


def spec(**kw) -> IdeaSpec:
    base = {"title": "Test idea", "claim": "beats_benchmark", "hold": [], "options": []}
    base.update(kw)
    return IdeaSpec(**base)


# --- the contract -------------------------------------------------------------


def test_pure_options_idea_is_a_position():
    s = spec(options=[{"underlying": "SPY", "kind": "call", "side": "buy"}])
    assert s.options[0].strike_pct == 100 and s.options[0].days_to_expiry == 30


def test_naked_selling_is_refused():
    with pytest.raises(ValidationError, match="no naked"):
        spec(options=[{"underlying": "SPY", "kind": "call", "side": "sell"}])
    with pytest.raises(ValidationError, match="no naked"):
        spec(hold=["QQQ"], options=[{"underlying": "SPY", "kind": "put", "side": "sell"}])


def test_covered_call_and_spread_cover_are_allowed():
    covered = spec(hold=["SPY"], options=[{"underlying": "SPY", "kind": "call", "side": "sell",
                                           "strike_pct": 105}])
    assert covered.options[0].side == "sell"
    spread = spec(options=[{"underlying": "SPY", "kind": "call", "side": "buy", "strike_pct": 100},
                           {"underlying": "SPY", "kind": "call", "side": "sell", "strike_pct": 105}])
    assert len(spread.options) == 2
    with pytest.raises(ValidationError, match="no naked"):
        # the bought call sits ABOVE the sold one: it does not cover it
        spec(options=[{"underlying": "SPY", "kind": "call", "side": "buy", "strike_pct": 110},
                      {"underlying": "SPY", "kind": "call", "side": "sell", "strike_pct": 105}])


def test_leg_shape_rules():
    with pytest.raises(ValidationError):
        OptionLeg(underlying="SPY", kind="call", side="buy", days_to_expiry=3)
    with pytest.raises(ValidationError, match="roll_days_left"):
        OptionLeg(underlying="SPY", kind="call", side="buy", days_to_expiry=30, roll_days_left=30)
    with pytest.raises(ValidationError, match="shorted underlying"):
        spec(short=["SPY"], options=[{"underlying": "SPY", "kind": "put", "side": "buy"}])
    with pytest.raises(ValidationError, match="intraday"):
        spec(hold=["SPY"], exits={"mode": "intraday", "stop_loss_pct": 5},
             options=[{"underlying": "SPY", "kind": "put", "side": "buy"}])
    with pytest.raises(ValidationError):
        spec(options=[{"underlying": "SPY", "kind": "call", "side": "buy"},
                      {"underlying": "SPY", "kind": "put", "side": "buy"},
                      {"underlying": "QQQ", "kind": "call", "side": "buy"}])  # the 2-leg cap


# --- the engine -----------------------------------------------------------------


def _run(s: IdeaSpec, closes: pd.DataFrame) -> dict:
    return run_test(s, closes, fred(), variations=1, seed=7, permutations=10)


def test_bought_call_on_a_flat_underlying_bleeds():
    flat = np.full(len(DAYS), 100.0)
    closes = closes_for({"SPY": flat, "QQQ": flat, "IWM": flat})
    frame = daily_frame(spec(options=[{"underlying": "SPY", "kind": "call", "side": "buy"}]),
                        closes, fred())
    # time decay: the idea loses a little almost every day and never gains on a flat tape
    assert frame["ret"].mean() < 0 and frame["ret"].max() <= 1e-9


def test_bought_call_on_a_rising_underlying_pays_and_is_labelled():
    # 0.3% a day: at 20% vol a gentler drift does not outrun theta -- expiry counts
    # calendar days, so weekends burn premium too (the pricing core's convention).
    rising = 100.0 * 1.003 ** np.arange(len(DAYS))
    closes = closes_for({"SPY": rising, "QQQ": rising, "IWM": rising})
    result = _run(spec(options=[{"underlying": "SPY", "kind": "call", "side": "buy"}]), closes)
    assert result["options"]["model_prices"] is True
    assert result["options"]["legs"][0]["vol"] == "vol index VIXCLS"
    assert any("Black-Scholes model" in n for n in result["notes"])
    frame = daily_frame(spec(options=[{"underlying": "SPY", "kind": "call", "side": "buy"}]),
                        closes, fred())
    assert frame["ret"].mean() > 0


def test_covered_call_truncates_the_rise():
    rising = 100.0 * 1.002 ** np.arange(len(DAYS))
    closes = closes_for({"SPY": rising, "QQQ": rising, "IWM": rising})
    plain = daily_frame(spec(hold=["SPY"]), closes, fred())
    covered = daily_frame(
        spec(hold=["SPY"], options=[{"underlying": "SPY", "kind": "call", "side": "sell",
                                     "strike_pct": 100}]),
        closes, fred())
    assert covered["ret"].mean() < plain["ret"].mean()


def test_leg_follows_the_rule_in_and_out():
    """Out of the market the leg is flat; re-entry opens a fresh contract (no bleed while out)."""
    rising = 100.0 * 1.001 ** np.arange(len(DAYS))
    closes = closes_for({"SPY": rising, "QQQ": rising, "IWM": rising})
    rule = {"enter": {"mode": "all", "conditions": [
        {"source": "fred", "series": "DTB3", "measure": "level", "op": ">", "threshold": 1.0}]}}
    s = spec(options=[{"underlying": "SPY", "kind": "call", "side": "buy"}], rules=rule,
             claim="beats_benchmark_when")
    frame = daily_frame(s, closes, fred())
    out_days = frame[~frame["on"]]
    assert (out_days["ret"] == 0).all()  # CASH otherwise: flat and NOT bleeding premium


def test_missing_rate_series_is_a_clear_error():
    flat = np.full(len(DAYS), 100.0)
    closes = closes_for({"SPY": flat, "QQQ": flat, "IWM": flat})
    with pytest.raises(ValueError, match="DTB3"):
        daily_frame(spec(options=[{"underlying": "SPY", "kind": "call", "side": "buy"}]),
                    closes, {"VIXCLS": pd.Series(20.0, index=DAYS)})
