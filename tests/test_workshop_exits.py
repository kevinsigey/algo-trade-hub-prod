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
