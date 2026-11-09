"""The basket battery (spec 2026-11-08, claim-typed gates): relative measurement of an
always-in allocation — block bootstrap on the log-excess series, a drawdown bound
against the benchmark, frozen constants. Pure functions, synthetic series."""

import numpy as np
import pytest

from tradehub.workshop import basket_gate

DAYS = 252


def _series(mean, vol, n, seed):
    rng = np.random.default_rng(seed)
    return rng.normal(mean, vol, n)


def test_constants_are_the_preregistered_ones():
    assert basket_gate.BLOCK_DAYS == 21
    assert basket_gate.BOOTSTRAPS == 2000
    assert basket_gate.DD_RATIO_MAX == 1.25
    assert basket_gate.DD_MIN_BENCH_PP == 5.0


def test_relative_sharpe_sign_and_scale():
    x = _series(0.001, 0.01, 1000, 1)
    s = basket_gate.relative_sharpe(x)
    assert s > 0
    assert s == pytest.approx(np.mean(x) / np.std(x, ddof=1) * np.sqrt(DAYS))
    assert basket_gate.relative_sharpe(-x) == pytest.approx(-s)
    assert basket_gate.relative_sharpe(np.zeros(100)) == 0.0  # no variance, no edge: zero, not NaN


def test_bootstrap_deterministic_and_brackets_a_real_edge():
    x = _series(0.0012, 0.003, 1500, 2)  # strong steady excess: Sharpe ~6 annualized
    a = basket_gate.bootstrap_ci(x, seed=99, bootstraps=400)
    b = basket_gate.bootstrap_ci(x, seed=99, bootstraps=400)
    assert a == b  # same seed, same answer
    lo, hi, p = a
    assert lo > 0 and hi > lo and p < 0.01


def test_bootstrap_includes_zero_for_pure_noise():
    x = _series(0.0, 0.01, 1500, 3)
    x = x - x.mean()  # centred: the sample itself has exactly no edge, by construction
    lo, hi, p = basket_gate.bootstrap_ci(x, seed=99, bootstraps=400)
    assert lo < 0 < hi and p > 0.1


def test_span_stats_dd_ratio_and_binding():
    # Benchmark falls 20% then recovers; the idea falls 30%: ratio 1.5 -> bound broken.
    bench = np.concatenate([np.full(50, -0.0045), np.full(50, 0.0046), np.full(100, 0.0003)])
    idea = np.concatenate([np.full(50, -0.0071), np.full(50, 0.0074), np.full(100, 0.0006)])
    st = basket_gate.span_stats(idea, bench, seed=5, bootstraps=200)
    assert st["bench_max_dd"] < -15 and st["idea_max_dd"] < st["bench_max_dd"]
    assert st["dd_ratio"] > 1.4 and st["dd_binding"] is True and st["dd_holds"] is False


def test_span_stats_dd_not_binding_when_benchmark_barely_falls():
    bench = np.full(300, 0.0004)  # never draws down
    idea = np.concatenate([np.full(30, -0.002), np.full(270, 0.0006)])
    st = basket_gate.span_stats(idea, bench, seed=5, bootstraps=200)
    assert st["dd_binding"] is False and st["dd_holds"] is True


def _run_pair(idea, bench, k=None, ew=None, seed=7):
    k = k or len(idea) // 2
    return basket_gate.battery(idea, bench, ew, split=k, seed=seed, bootstraps=400)


def test_battery_pass_when_edge_and_drawdown_both_hold():
    bench = _series(0.0003, 0.01, 3000, 11)
    idea = bench + _series(0.0012, 0.002, 3000, 12)  # steady excess, tracks the bench's falls
    out = _run_pair(idea, bench)
    assert out["verdict"] == "PASS", out["legs"]
    assert all(leg["holds"] for leg in out["legs"])
    assert out["spans"]["unseen"]["ci_low"] > 0


def test_battery_fail_on_drawdown_even_with_an_edge():
    bench = _series(0.0003, 0.01, 3000, 13)
    rng = np.random.default_rng(14)
    idea = bench + 0.0012 + rng.normal(0, 0.001, 3000)  # the same steady edge as the PASS case
    wealth = np.cumprod(1 + bench)
    trough = int(np.argmin(wealth / np.maximum.accumulate(wealth)))
    peak = int(np.argmax(wealth[:trough + 1]))
    idea[peak:trough + 1] = bench[peak:trough + 1] * 2.2 + 0.0005  # ...except in the benchmark's
    # worst slide, where it falls more than twice as far
    out = _run_pair(idea, bench)
    assert out["verdict"] == "FAIL"
    dd = {leg["name"]: leg for leg in out["legs"]}
    assert dd["dd_built"]["holds"] is False or dd["dd_unseen"]["holds"] is False
    assert dd["ci_built"]["holds"] and dd["ci_unseen"]["holds"]  # the edge itself was real


def test_battery_fail_when_no_reliable_edge():
    bench = _series(0.0003, 0.01, 3000, 15)
    idea = _series(0.0003, 0.01, 3000, 16)  # independent noise, same mean
    out = _run_pair(idea, bench)
    assert out["verdict"] == "FAIL"
    ci = {leg["name"]: leg for leg in out["legs"]}
    assert ci["ci_built"]["holds"] is False or ci["ci_unseen"]["holds"] is False


def test_battery_identical_to_benchmark_cannot_pass():
    bench = _series(0.0003, 0.01, 2000, 17)
    out = _run_pair(bench.copy(), bench)
    assert out["verdict"] == "FAIL"  # no variance in the relative series: no provable edge


def test_ew_reference_reported_and_degenerate_case():
    bench = _series(0.0003, 0.01, 3000, 18)
    ew = bench + _series(0.0006, 0.002, 3000, 19)
    idea = bench + _series(0.0012, 0.002, 3000, 20)
    out = _run_pair(idea, bench, ew=ew)
    assert out["ew_reference"] is not None
    assert out["ew_reference"]["spans"]["unseen"]["excess_cagr"] > 0
    same = _run_pair(ew, bench, ew=ew.copy())
    assert same["ew_reference"]["spans"]["unseen"]["rel_sharpe"] == pytest.approx(0.0, abs=1e-9)
