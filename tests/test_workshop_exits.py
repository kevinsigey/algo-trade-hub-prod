import time

import numpy as np
import pandas as pd
import pytest

from tradehub.workshop.engine import apply_exits, daily_frame, run_test, target_today
from tradehub.workshop.spec import Exits, IdeaSpec

ON = np.ones(12, dtype=bool)


def path(*daily):
    return np.array(daily, dtype=float)


def test_stop_loss_exits_on_the_first_close_through_it_and_not_before():
    sleeve = path(0.0, -0.03, -0.03, -0.03, 0.01, 0.01, 0.0, 0.0)  # -5.9% after day 2, -8.7% after day 3
    held, why = apply_exits(ON[:8], sleeve, Exits(stop_loss_pct=8), cooldown=None, lag=1)
    assert why.tolist() == ["", "", "", "stop-loss", "", "", "", ""]
    assert held.tolist() == [True, True, True, True, False, False, False, False]  # signal never went off


def test_close_timing_holds_one_more_day():
    sleeve = path(0.0, -0.1, 0.0, 0.0, 0.0)
    held, _ = apply_exits(ON[:5], sleeve, Exits(stop_loss_pct=8), cooldown=None, lag=2)
    assert held.tolist() == [True, True, True, False, False]


def test_trailing_measures_from_the_best_close():
    sleeve = path(0.10, 0.10, -0.05, -0.05, -0.05, 0.0)  # peak 1.21, then 1.1495, 1.092 (-9.75%), ...
    _, why = apply_exits(ON[:6], sleeve, Exits(trailing_pct=9), cooldown=None, lag=1)
    assert why.tolist().index("trailing") == 3
    _, why = apply_exits(ON[:6], sleeve, Exits(stop_loss_pct=9), cooldown=None, lag=1)
    assert "stop-loss" not in why.tolist()  # never 9% below entry


def test_take_profit_and_time_stop():
    sleeve = path(0.1, 0.1, 0.01, 0.0, 0.0)
    _, why = apply_exits(ON[:5], sleeve, Exits(take_profit_pct=20), cooldown=None, lag=1)
    assert why.tolist().index("take-profit") == 1
    _, why = apply_exits(ON[:5], path(0, 0, 0, 0, 0), Exits(max_days=3), cooldown=None, lag=1)
    assert why.tolist().index("time") == 2


def test_reentry_needs_a_fresh_signal():
    signal = np.array([True] * 4 + [False] + [True] * 3)
    sleeve = path(-0.1, 0, 0, 0, 0, 0, 0, 0)
    held, _ = apply_exits(signal, sleeve, Exits(stop_loss_pct=5), cooldown=None, lag=1)
    assert held.tolist() == [True, False, False, False, False, True, True, True]


def test_no_condition_reenters_after_the_cooldown():
    on = np.ones(30, dtype=bool)
    sleeve = np.zeros(30)
    sleeve[0] = -0.1
    held, _ = apply_exits(on, sleeve, Exits(stop_loss_pct=5), cooldown=21, lag=1)
    assert held[1:22].sum() == 0 and held[22] and held[0]


def test_a_gap_is_the_full_close_loss():
    sleeve = path(0.0, -0.3, 0.0)
    held, why = apply_exits(ON[:3], sleeve, Exits(stop_loss_pct=8), cooldown=None, lag=1)
    assert held.tolist() == [True, True, False] and why[1] == "stop-loss"  # day 1 keeps its -30%


N = 3000
IDX = pd.bdate_range("2010-01-04", periods=N)


def market(seed):
    rng = np.random.default_rng(seed)
    spy = rng.normal(0.0003, 0.01, N)
    px = {t: 100 * np.cumprod(1 + spy * k + rng.normal(0, 0.004, N)) for t, k in
          (("SPY", 1.0), ("QQQ", 1.2), ("IWM", 1.1), ("AAA", 1.0))}
    return pd.DataFrame(px, index=IDX)


WHEN = {"source": "price", "series": "SPY", "measure": "pct_change", "lookback_days": 20, "op": ">", "threshold": 0}


def spec(**over):
    return IdeaSpec.model_validate({"title": "AAA with stops", "hold": ["AAA"], "claim": "beats_benchmark",
                                    "start": "2010-01-04", "when": WHEN, "exits": {"stop_loss_pct": 3}, **over})


def test_daily_frame_and_run_test_agree_on_the_exit_path():
    closes = market(1)
    s = spec()
    df = daily_frame(s, closes, {})
    assert (df["exit"] == "stop-loss").sum() > 5
    plain = daily_frame(spec(exits={}), closes, {})
    assert not np.allclose(df["ret"], plain["ret"])
    out = run_test(s, closes, {}, variations=1, seed=3, permutations=200)
    k = int(len(df) * (1 - s.unseen_fraction))
    from tradehub.workshop.engine import claim_check
    assert claim_check(s, df.iloc[k:])["value"] == pytest.approx(out["claim"]["unseen"]["value"])


def test_target_today_is_out_the_morning_after_a_stop():
    closes = market(2).iloc[:400].copy()
    closes.iloc[-60:, closes.columns.get_loc("SPY")] *= np.linspace(1.0, 1.3, 60)  # condition firmly on
    s = spec(exits={"stop_loss_pct": 5})
    assert target_today(s, closes, {}) == {"AAA": 1.0}
    crashed = closes.copy()
    crashed.iloc[-1, crashed.columns.get_loc("AAA")] *= 0.8  # -20% on the last close
    assert target_today(s, crashed, {}) == {}


def test_exits_fit_the_time_budget():
    rng = np.random.default_rng(0)
    big = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, 5000)) for t in
                        ("SPY", "QQQ", "IWM", "AAA")}, index=pd.bdate_range("2000-01-03", periods=5000))
    s = spec(start="2000-01-03", exits={"stop_loss_pct": 5, "trailing_pct": 10, "max_days": 60})
    t0 = time.perf_counter()
    run_test(s, big, {}, variations=1, seed=1, permutations=1000)
    assert time.perf_counter() - t0 < 15


def test_target_today_matches_the_backtest_when_a_bar_is_missing():
    # Review I1: a missing bar must be dropped the way _legs drops it, not forward-filled into the lookback.
    full = market(5)
    s = spec(when={"source": "price", "series": "SPY", "measure": "pct_change", "lookback_days": 3, "op": ">",
                   "threshold": 0}, exits={})
    for end in range(300, 900, 7):
        for k, col in ((2, "SPY"), (3, "AAA"), (4, "SPY")):
            closes = full.iloc[:end].copy()
            closes.iloc[-k, closes.columns.get_loc(col)] = np.nan
            nxt = pd.bdate_range(closes.index[-1], periods=2)[1]
            tomorrow = pd.concat([closes, closes.iloc[[-1]].set_axis([nxt])])
            on = bool(daily_frame(s, tomorrow, {})["on"].iloc[-1])
            assert (target_today(s, closes, {}) == {"AAA": 1.0}) == on, (end, k, col)


def test_exit_reason_only_when_the_exit_made_it_flat():
    # Review I2: an old stop must not label a close that the rule itself caused.
    from tradehub.workshop.engine import target_and_reason
    up = market(6).iloc[:400].copy()
    up["SPY"] = np.linspace(100, 160, len(up))  # condition (SPY up over 20 days) always on
    up["AAA"] = 100.0
    s = spec(exits={"stop_loss_pct": 5})
    crash = up.copy()
    crash.iloc[-1, crash.columns.get_loc("AAA")] = 80.0
    assert target_and_reason(s, crash, {}) == ({}, "stop-loss")
    off = up.copy()
    off.iloc[-1, off.columns.get_loc("SPY")] = 50.0  # the rule turns off on the last close
    off.iloc[-30, off.columns.get_loc("AAA")] = 80.0  # and there was a stop a month ago
    weights, why = target_and_reason(s, off, {})
    assert weights == {} and why == ""
    assert target_and_reason(spec(exits={}), up, {}) == ({"AAA": 1.0}, "")


def ohlc(rows):
    """rows of (open, high, low, close); the day before the first row closed at 100."""
    a = np.array(rows, dtype=float)
    return {"open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3], "prev": np.r_[100.0, a[:-1, 3]]}


def test_intraday_stop_fills_at_the_stop_or_the_gap_open():
    from tradehub.workshop.engine import apply_exits_intraday
    b = ohlc([(100, 101, 99, 100), (99, 100, 94, 96), (96, 97, 95, 96)])  # day 1 trades through 95
    held, why, ret = apply_exits_intraday(ON[:3], b, 1, Exits(stop_loss_pct=5), cooldown=None, lag=1)
    assert held.tolist() == [True, True, False] and why[1] == "stop-loss"
    assert ret[1] == pytest.approx(95 / 100 - 1)  # filled at the stop, not the 96 close
    gap = ohlc([(100, 101, 99, 100), (90, 92, 88, 91), (91, 92, 90, 91)])  # opens below the stop
    _, _, ret = apply_exits_intraday(ON[:3], gap, 1, Exits(stop_loss_pct=5), cooldown=None, lag=1)
    assert ret[1] == pytest.approx(90 / 100 - 1)  # the worse price: the open


def test_intraday_stop_first_when_one_day_touches_both():
    from tradehub.workshop.engine import apply_exits_intraday
    b = ohlc([(100, 111, 94, 105), (105, 106, 104, 105)])
    _, why, ret = apply_exits_intraday(ON[:2], b, 1, Exits(stop_loss_pct=5, take_profit_pct=10), cooldown=None,
                                       lag=1)
    assert why[0] == "stop-loss" and ret[0] == pytest.approx(-0.05)


def test_intraday_take_profit_and_trailing_from_the_high():
    from tradehub.workshop.engine import apply_exits_intraday
    b = ohlc([(100, 112, 99, 110), (110, 111, 109, 110)])
    _, why, ret = apply_exits_intraday(ON[:2], b, 1, Exits(take_profit_pct=10), cooldown=None, lag=1)
    assert why[0] == "take-profit" and ret[0] == pytest.approx(0.10)
    t = ohlc([(100, 120, 99, 119), (119, 119, 107, 108), (108, 109, 107, 108)])  # high 120, then 10% below = 108
    _, why, ret = apply_exits_intraday(ON[:3], t, 1, Exits(trailing_pct=10), cooldown=None, lag=1)
    assert why[1] == "trailing" and ret[1] == pytest.approx(108 / 119 - 1)


def test_intraday_short_mirrors():
    from tradehub.workshop.engine import apply_exits_intraday
    b = ohlc([(100, 106, 99, 104), (104, 105, 103, 104)])  # a short stops when price rises 5%
    held, why, ret = apply_exits_intraday(ON[:2], b, -1, Exits(stop_loss_pct=5), cooldown=None, lag=1)
    assert why[0] == "stop-loss" and ret[0] == pytest.approx(-(105 / 100 - 1)) and held.tolist() == [True, False]


def test_intraday_time_stop_and_reentry_like_close_mode():
    from tradehub.workshop.engine import apply_exits_intraday
    flat = ohlc([(100, 100.5, 99.5, 100)] * 8)
    signal = np.array([True] * 4 + [False] + [True] * 3)
    held, why, _ = apply_exits_intraday(signal, flat, 1, Exits(max_days=2), cooldown=None, lag=1)
    assert why[1] == "time" and held.tolist() == [True, True, False, False, False, True, True, False]


def intraday(s):
    s.exits.mode = "intraday"  # the spec refuses it until the order side ships (Task 8); the engine is ready now
    return s


def with_bars(closes, low_dip=None):
    from tradehub.workshop.data import add_bars
    bars = {"AAA": pd.DataFrame({"open": closes["AAA"].shift(1).fillna(closes["AAA"]), "high": closes["AAA"] * 1.005,
                                 "low": closes["AAA"] * 0.995, "close": closes["AAA"]})}
    if low_dip is not None:
        bars["AAA"].loc[low_dip, "low"] = bars["AAA"].loc[low_dip, "close"] * 0.5
    return add_bars(closes, bars)


def test_intraday_mode_runs_through_the_one_rule_path():
    closes = market(7)
    dip = closes.index[2000]
    s = intraday(spec(when=None, exits={"stop_loss_pct": 20}))
    df = daily_frame(s, with_bars(closes, low_dip=dip), {})
    assert df.loc[dip, "exit"] == "stop-loss"
    with pytest.raises(ValueError, match="daily bars"):
        daily_frame(s, closes, {})
    out = run_test(s, with_bars(closes, low_dip=dip), {}, variations=1, seed=1, permutations=100)
    assert out["verdict"] in ("PASS", "FAIL")
    assert target_today(s, with_bars(closes), {}) in ({"AAA": 1.0}, {})
