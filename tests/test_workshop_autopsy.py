import numpy as np
import pandas as pd
import pytest

from tradehub.workshop.autopsy import ALPHA, MAX_SUGGESTIONS, autopsy, tail_probability, trades


def _regime_losers(frame: pd.DataFrame) -> pd.DataFrame:
    """Loses to the benchmark whenever SPY sits under its 50-day average."""
    days = np.arange(len(frame))
    frame["spy"] = np.where(days % 200 >= 100, -0.004, 0.004)
    frame["bench"] = frame["spy"]
    close = pd.Series(np.cumprod(1 + frame["spy"].to_numpy()), index=frame.index)
    below = (close < close.rolling(50).mean()).to_numpy()
    frame["ret"] = frame["spy"] + np.where(below, -0.003, 0.003)
    return frame


def _frame(n=420, seed=1):
    idx = pd.bdate_range("2023-01-02", periods=n)
    rng = np.random.default_rng(seed)
    spy = rng.normal(0.0005, 0.004, n)
    ret = spy + rng.normal(0.0002, 0.002, n)
    return pd.DataFrame({"ret": ret, "bench": spy, "spy": spy, "on": True, "exit": None, "held": True}, index=idx)


def test_long_holds_split_into_blocks_and_flat_days_break_a_trade():
    frame = _frame(50)
    frame.loc[frame.index[25:28], "held"] = False
    spans = trades(frame)
    assert [(s["start"], s["end"]) for s in spans] == [(0, 20), (21, 24), (28, 48), (49, 49)]
    assert [s["fresh"] for s in spans] == [True, False, True, False]


def test_excess_is_measured_over_the_trade():
    frame = _frame(5)
    frame["ret"], frame["bench"] = 0.01, 0.0
    assert trades(frame)[0]["excess"] == pytest.approx(1.01 ** 5 - 1)


def test_a_small_lead_over_the_base_rate_is_not_a_pattern():
    assert tail_probability(6, 9, 0.54) > ALPHA  # XLE on real prices: 6 of 9 against 54% is noise
    assert tail_probability(7, 8, 0.48) < ALPHA


def test_an_always_in_idea_has_no_entries_to_blame():
    frame = _frame(420)
    days = np.arange(len(frame))
    frame["spy"] = np.where(days % 21 == 20, 0.02, 0.0)  # a big move right before every block
    frame["bench"] = frame["spy"]
    frame["ret"] = frame["spy"] - 0.001
    out = autopsy(frame, hold=["SPY"], closes=pd.DataFrame(), has_exits=True, variation=1)
    assert out["pattern"] is None


def test_too_few_trades_says_so():
    out = autopsy(_frame(60), hold=["SPY"], closes=pd.DataFrame(), has_exits=False, variation=1)
    assert out["status"] == "too_few" and out["pattern"] is None


def test_names_a_market_regime_that_keeps_losing():
    frame = _regime_losers(_frame(840))
    out = autopsy(frame, hold=["SPY"], closes=pd.DataFrame(), has_exits=False, variation=1)
    assert out["status"] == "ok" and out["pattern"]["implicates"] == "gate"
    assert "downtrend" in out["pattern"]["text"] and out["suggestion"]


def test_a_few_huge_losers_with_no_exit_implicate_the_exit():
    frame = _frame()
    frame["ret"], frame["bench"], frame["spy"] = 0.0, 0.0, 0.0
    days = np.arange(len(frame))
    frame.loc[days % 42 < 21, "ret"] = 0.001  # odd blocks win
    frame.loc[(days % 42 >= 21) & (days % 42 < 23), "ret"] = -0.0005  # even blocks lose a little
    frame.iloc[21:42, frame.columns.get_loc("ret")] = -0.03  # one block loses everything
    out = autopsy(frame, hold=["SPY"], closes=pd.DataFrame(), has_exits=False, variation=1)
    assert out["pattern"]["implicates"] == "exit"
    # With a stop already on, the same losses are not an exit finding.
    assert autopsy(frame, hold=["SPY"], closes=pd.DataFrame(), has_exits=True, variation=1)["pattern"] is None


def test_one_name_driving_the_losses_implicates_sizing():
    frame = _frame()
    frame["spy"], frame["bench"] = 0.0, 0.0
    days = np.arange(len(frame))
    lose = days % 42 >= 21
    frame["ret"] = np.where(lose, -0.001, 0.001)
    closes = pd.DataFrame({"AAA": np.cumprod(1 + np.where(lose, -0.002, 0.001)),
                           "BBB": np.cumprod(1 + np.where(lose, 0.0, 0.001))}, index=frame.index)
    out = autopsy(frame, hold=["AAA", "BBB"], closes=closes, has_exits=False, variation=1)
    assert out["pattern"]["implicates"] == "sizing" and "AAA" in out["pattern"]["text"]


def test_suggestions_stop_after_the_cap_but_the_diagnosis_stays():
    frame = _regime_losers(_frame(840))
    out = autopsy(frame, hold=["SPY"], closes=pd.DataFrame(), has_exits=False, variation=MAX_SUGGESTIONS + 1)
    assert out["pattern"] and out["suggestion"] is None and out["suggestions_left"] == 0
