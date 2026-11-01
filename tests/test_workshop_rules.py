"""Step 6: buy/sell-when rules in the engine."""
import time

import numpy as np
import pandas as pd

from tradehub.workshop import signals
from tradehub.workshop.engine import _held, condition_mask, daily_frame, run_test, target_today
from tradehub.workshop.spec import IdeaSpec

N = 1500
IDX = pd.bdate_range("2010-01-04", periods=N)


def market(seed=0, n=N, start="2010-01-04"):
    rng = np.random.default_rng(seed)
    spy = rng.normal(0.0003, 0.01, n)
    px = {t: 100 * np.cumprod(1 + spy * k + rng.normal(0, 0.004, n)) for t, k in
          (("SPY", 1.0), ("QQQ", 1.2), ("IWM", 1.1), ("AAA", 1.0))}
    df = pd.DataFrame(px, index=pd.bdate_range(start, periods=n))
    df["SPY.high"], df["SPY.low"] = df["SPY"] * 1.01, df["SPY"] * 0.99
    df["SPY.volume"] = rng.integers(1_000, 100_000, n).astype(float)
    return df


def cond(measure="pct_change", op=">", threshold=0.0, n=20, source="price", series="SPY", **kw):
    return {"source": source, "series": series, "measure": measure, "lookback_days": n, "op": op,
            "threshold": threshold, **kw}


def spec(rules=None, **over):
    return IdeaSpec.model_validate({"title": "AAA by rule", "hold": ["AAA"], "claim": "beats_benchmark",
                                    "start": "2010-01-04", "rules": rules, **over})


def _old_mask(when, closes, fred, timing="open"):
    """The step 2-5 condition_mask, kept verbatim as the reference for legacy specs."""
    idx = closes.index
    if when["source"] == "price":
        values, lag = closes[when["series"]], 1
    else:
        raw = fred[when["series"]].sort_index()
        values, lag = raw.reindex(idx.union(raw.index)).ffill().reindex(idx), 2
    n = when["lookback_days"]
    measured = {"level": values, "change": values - values.shift(n),
                "pct_change": (values / values.shift(n) - 1) * 100}[when["measure"]]
    hit = measured > when["threshold"] if when["op"] == ">" else measured < when["threshold"]
    lag += 1 if timing == "close" else 0
    return (hit & measured.notna()).shift(lag, fill_value=False).astype(bool)


def test_legacy_when_mask_identical():
    closes = market(1)
    fred = {"DGS10": pd.Series(np.cumsum(np.random.default_rng(2).normal(0, 0.05, N)) + 3, index=IDX[::1])}
    for when in (cond(), cond("level", "<", 105), cond("change", ">", 0.1, 63, "fred", "DGS10"),
                 cond("pct_change", "<", -2, 5)):
        for timing in ("open", "close"):
            s = IdeaSpec.model_validate({"title": "legacy", "hold": ["AAA"], "claim": "beats_benchmark",
                                         "when": when, "execution": {"timing": timing}})
            pd.testing.assert_series_equal(condition_mask(s, closes, fred), _old_mask(when, closes, fred, timing),
                                           check_names=False)


def test_all_vs_any():
    closes = market(2)
    a, b = cond(n=5), cond("vs_sma", ">", 0, 50)
    ma = condition_mask(spec({"enter": {"conditions": [a]}}), closes, {})
    mb = condition_mask(spec({"enter": {"conditions": [b]}}), closes, {})
    both = condition_mask(spec({"enter": {"mode": "all", "conditions": [a, b]}}), closes, {})
    either = condition_mask(spec({"enter": {"mode": "any", "conditions": [a, b]}}), closes, {})
    assert (both == (ma & mb)).all() and (either == (ma | mb)).all() and both.sum() < either.sum()


def _price_path(steps):
    closes = market(3, n=len(steps) + 1)
    closes["SPY"] = 100 * np.cumprod(np.r_[1, 1 + np.array(steps)])
    return closes


def test_enter_exit_hysteresis():
    # enter: SPY up on the day (A); exit: SPY down more than 2% on the day (B). Small down days don't get it out.
    steps = [0.01, -0.005, -0.005, -0.03, -0.005, 0.01, 0.0]
    closes = _price_path(steps)
    s = spec({"enter": {"conditions": [cond(n=1)]}, "exit": {"conditions": [cond(op="<", threshold=-2, n=1)]}})
    on = condition_mask(s, closes, {}).to_numpy()
    # day i decides on the close of i-1: in after day 1's rise, held through the small dips, out after the -3% day.
    assert on.tolist() == [False, False, True, True, True, False, False, True]


def test_exit_wins_same_day():
    closes = _price_path([0.01, 0.01, 0.01])
    s = spec({"enter": {"conditions": [cond(n=1)]}, "exit": {"conditions": [cond(n=1)]}})  # both fire on up days
    assert not condition_mask(s, closes, {}).any()


def test_mixed_lags():
    closes = market(4)
    fred = {"DGS10": pd.Series(np.cumsum(np.random.default_rng(5).normal(0, 0.05, N)) + 3, index=IDX)}
    f, p = cond("change", ">", 0, 21, "fred", "DGS10"), cond("rsi", "<", 40, 14)
    got = condition_mask(spec({"enter": {"mode": "any", "conditions": [f, p]}}), closes, fred)
    fv = signals.measure(fred["DGS10"], "change", 21)
    pv = signals.measure(closes["SPY"], "rsi", 14)
    want = ((fv > 0) & fv.notna()).shift(2, fill_value=False) | ((pv < 40) & pv.notna()).shift(1, fill_value=False)
    assert (got == want).all()


def test_target_matches_backtest_vwap():
    full = market(6)
    s = spec({"enter": {"conditions": [cond("vs_vwap", ">", 0, 10)]}, "exit": {"conditions": [cond("rsi", ">", 70, 14)]}})
    for end in range(200, 1400, 37):
        on = bool(daily_frame(s, full.iloc[:end + 1], {})["on"].iloc[-1])  # the real next day's position
        assert (target_today(s, full.iloc[:end], {}) == {"AAA": 1.0}) == on, end


def test_stop_then_fresh_signal_with_exit_group():
    s = spec({"enter": {"conditions": [cond()]}, "exit": {"conditions": [cond(op="<", threshold=-5)]}},
             exits={"stop_loss_pct": 5})
    signal = np.array([1, 1, 1, 1, 1, 0, 1, 1], dtype=bool)
    sleeve = np.array([0.0, -0.08, 0, 0, 0, 0, 0, 0])
    held, why, _ = _held(s, signal, sleeve)
    # stopped at day 1's close, out from day 2; the rule still says "in" but that isn't a fresh signal;
    # back in only after the rule goes out (day 5) and in again (day 6).
    assert held.tolist() == [True, True, False, False, False, False, True, True] and why[1] == "stop-loss"


def test_three_condition_rule_fits_the_time_budget():
    big = market(0, n=5000, start="2000-01-03")
    s = spec({"enter": {"mode": "all", "conditions": [cond("rsi", "<", 50, 14),
                                                      cond("sma_cross", ">", 0, 50, slow_days=200),
                                                      cond("vs_vwap", ">", -3, 20)]},
              "exit": {"mode": "any", "conditions": [cond("vs_high", ">", 0, 20)]}},
             start="2000-01-03", exits={"stop_loss_pct": 5, "max_days": 60})
    t0 = time.perf_counter()
    run_test(s, big, {}, variations=1, seed=1, permutations=1000)
    assert time.perf_counter() - t0 < 15
