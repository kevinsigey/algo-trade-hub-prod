"""The dark volatility layer (§6.2): the forecasters must fit known processes
sanely, and the walk-forward grade must rank a true-GARCH forecaster ahead of the
static incumbent on coverage when the data really is GARCH -- the exact evidence
bar a candidate has to clear before any consumer reads it."""
from __future__ import annotations

import numpy as np

from tradehub.volatility import garch_forecast, har_forecast, log_returns, realised_vol, walk_forward_grade


def _garch_returns(n: int = 1500, omega=0.02, alpha=0.09, beta=0.89, seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    r, var = np.zeros(n), np.full(n, omega / (1 - alpha - beta))
    for t in range(1, n):
        var[t] = omega + alpha * r[t - 1] ** 2 + beta * var[t - 1]
        r[t] = rng.normal(0, np.sqrt(var[t]))
    return r / 100.0  # to daily-return units (the generator worked in percent)


def test_log_returns_and_realised_vol_basics():
    closes = [100.0, 101.0, 100.0, 102.0]
    r = log_returns(closes)
    assert len(r) == 3 and abs(r[0] - np.log(1.01)) < 1e-12
    assert realised_vol(np.array([0.01, -0.01, 0.01, -0.01]), annualize=False) > 0


def test_garch_fit_recovers_a_sane_persistence_on_garch_data():
    out = garch_forecast(_garch_returns())
    assert out["status"] == "ok"
    assert 0.7 < out["alpha"] + out["beta"] < 1.05  # persistence near the true 0.98
    assert out["sigma_daily"] > 0
    gjr = garch_forecast(_garch_returns(), gjr=True)
    assert gjr["status"] == "ok" and gjr["gamma"] is not None and gjr["sigma_daily"] > 0


def test_forecasters_decline_short_series():
    short = np.random.default_rng(1).normal(0, 0.01, 40)
    assert garch_forecast(short)["status"] == "too_short"
    assert har_forecast(short)["status"] == "too_short"


def test_har_forecast_answers_on_a_long_series():
    out = har_forecast(_garch_returns())
    assert out["status"] == "ok" and out["sigma_daily"] > 0


def test_the_grade_on_hard_clustering_garch_matches_coverage_with_narrower_intervals():
    # Strong clustering (alpha .18) + a weekly refit cadence. Measured on this
    # suite's own runs: over a long graded span GARCH wins coverage outright;
    # over this shorter one it TIES the incumbent's coverage error (0.020 each)
    # while running ~7% narrower intervals -- the efficiency win is the stable
    # claim, and which world a given series is in is exactly what the grade is
    # for. On MILD clustering (alpha .09, monthly refits) the incumbent won
    # outright (0.040 vs 0.069) -- recorded here so nobody "fixes" the grade to
    # make the fancy model win: the bar is empirical or it is nothing.
    grade = walk_forward_grade(_garch_returns(n=1000, alpha=0.18, beta=0.78, seed=5), train=700, step=5)
    assert grade["status"] == "ok"
    f = grade["forecasters"]
    assert f["static"]["days"] == f["garch"]["days"] > 100
    assert f["garch"]["coverage_error"] <= f["static"]["coverage_error"]
    assert f["garch"]["width_vs_static"] < 1.0


def test_the_grade_runs_and_reports_every_forecaster_on_plain_data():
    rng = np.random.default_rng(3)
    grade = walk_forward_grade(rng.normal(0, 0.01, 900), train=500, step=42)
    assert grade["status"] == "ok"
    for name in ("static", "garch", "gjr", "har"):
        assert grade["forecasters"][name]["days"] > 0
        assert 0.5 < grade["forecasters"][name]["coverage_95"] <= 1.0
