import numpy as np
import pandas as pd
import pytest

from tradehub.workshop.engine import condition_mask, run_test, verdict_of
from tradehub.workshop.spec import IdeaSpec

N = 5000
IDX = pd.bdate_range("2006-01-03", periods=N)


def prices(returns: np.ndarray) -> np.ndarray:
    return 100 * np.cumprod(1 + returns)


def market(seed=0):
    rng = np.random.default_rng(seed)
    spy = rng.normal(0.0003, 0.01, N)
    frame = {"SPY": prices(spy),
             "QQQ": prices(spy * 1.2 + rng.normal(0, 0.004, N)),
             "IWM": prices(spy * 1.1 + rng.normal(0, 0.005, N))}
    return rng, spy, frame


def rates(rng):
    # A smooth random walk, like a yield: long rising and falling stretches.
    return pd.Series(np.cumsum(rng.normal(0, 0.05, N)) + 3, index=IDX)


WHEN = {"source": "fred", "series": "DGS10", "measure": "change", "lookback_days": 63, "op": ">", "threshold": 0.0}


def spec(**over):
    base = {"title": "Asset beats SPY when rates rise", "hold": ["AAA"], "when": WHEN, "otherwise": "SPY",
            "claim": "beats_benchmark_when"}
    return IdeaSpec.model_validate({**base, **over})


def test_planted_edge_passes():
    rng, spy, frame = market(1)
    fred = {"DGS10": rates(rng)}
    s = spec()
    mask = condition_mask(s, pd.DataFrame({**frame, "AAA": frame["SPY"]}, index=IDX), fred)
    aaa = spy + rng.normal(0, 0.004, N) + np.where(mask.reindex(IDX, fill_value=False).to_numpy(), 0.001, 0.0)
    closes = pd.DataFrame({**frame, "AAA": prices(aaa)}, index=IDX)
    out = run_test(s, closes, fred, variations=1, seed=7)
    assert out["verdict"] == "PASS", out["headline"]
    assert out["shuffle"]["p"] < 0.05 and out["claim"]["unseen"]["holds"]
    assert out["headline"] == "Did what it claims on the years it hadn't seen."


def test_noise_fails():
    rng, spy, frame = market(2)
    closes = pd.DataFrame({**frame, "AAA": prices(rng.normal(0.0003, 0.01, N))}, index=IDX)
    out = run_test(spec(), closes, {"DGS10": rates(rng)}, variations=1, seed=7)
    assert out["verdict"] == "FAIL"


def test_lookahead_is_impossible():
    # "Hold AAA on days AAA goes up" is a perfect same-day predictor. With the prior-close rule it is noise.
    rng, spy, frame = market(3)
    closes = pd.DataFrame({**frame, "AAA": prices(rng.normal(0.0003, 0.01, N))}, index=IDX)
    s = spec(when={"source": "price", "series": "AAA", "measure": "pct_change", "lookback_days": 1, "op": ">",
                   "threshold": 0.0}, otherwise="CASH", claim="beats_benchmark")
    out = run_test(s, closes, {}, variations=1, seed=7)
    assert out["verdict"] != "PASS"
    assert out["context"][0]["unseen_cagr"] < 100  # a leak would print an absurd return


def test_ballast_definition():
    rng, spy, frame = market(4)
    down = spy < 0
    good = np.where(down, 0.0, 0.0004)  # flat on SPY's down days, up overall
    bad = np.where(down, spy * 1.5, -0.0001)  # loses more than SPY, negative overall
    closes = pd.DataFrame({**frame, "GOOD": prices(good), "BAD": prices(bad)}, index=IDX)
    g = run_test(IdeaSpec(title="good ballast", hold=["GOOD"], claim="ballast"), closes, {}, variations=1, seed=1)
    b = run_test(IdeaSpec(title="bad ballast", hold=["BAD"], claim="ballast"), closes, {}, variations=1, seed=1)
    assert g["claim"]["unseen"]["holds"] and g["verdict"] == "PASS"
    assert not b["claim"]["unseen"]["holds"] and b["verdict"] == "FAIL"
    assert g["t_test"] is None


def test_short_unseen_span_is_not_enough_data():
    rng, spy, frame = market(5)
    closes = pd.DataFrame({**frame, "AAA": frame["SPY"]}, index=IDX).iloc[-1300:]  # 30% of 1300 = 390 days
    out = run_test(spec(), closes, {"DGS10": rates(rng)}, variations=1, seed=1)
    assert out["verdict"] == "NOT ENOUGH DATA" and "unseen" in out["reason"]
    assert out["headline"] == "Not enough data to judge."


def test_condition_never_true_is_not_enough_data():
    rng, spy, frame = market(6)
    closes = pd.DataFrame({**frame, "AAA": frame["SPY"]}, index=IDX)
    s = spec(when={**WHEN, "threshold": 1e9})
    out = run_test(s, closes, {"DGS10": rates(rng)}, variations=1, seed=1)
    assert out["verdict"] == "NOT ENOUGH DATA" and "condition" in out["reason"]


def test_bonferroni_bar():
    rng, spy, frame = market(7)
    closes = pd.DataFrame({**frame, "AAA": prices(rng.normal(0.0003, 0.01, N))}, index=IDX)
    fred = {"DGS10": rates(rng)}
    assert run_test(spec(), closes, fred, variations=1, seed=1)["shuffle"]["bar"] == pytest.approx(0.05)
    assert run_test(spec(), closes, fred, variations=4, seed=1)["shuffle"]["bar"] == pytest.approx(0.0125)
    assert verdict_of(True, 0.02, 0.05) == "PASS" and verdict_of(True, 0.02, 0.0125) == "FAIL"
    assert verdict_of(False, 0.001, 0.05) == "FAIL"


def test_costs_reduce_returns():
    rng, spy, frame = market(8)
    closes = pd.DataFrame({**frame, "AAA": prices(rng.normal(0.0003, 0.01, N))}, index=IDX)
    flippy = {"source": "price", "series": "AAA", "measure": "pct_change", "lookback_days": 1, "op": ">", "threshold": 0.0}
    cheap = run_test(spec(when=flippy, cost_bps=0), closes, {}, variations=1, seed=1)
    dear = run_test(spec(when=flippy, cost_bps=100), closes, {}, variations=1, seed=1)
    assert dear["context"][0]["unseen_cagr"] < cheap["context"][0]["unseen_cagr"] - 5


def test_same_seed_same_result_and_curve_downsampled():
    rng, spy, frame = market(9)
    closes = pd.DataFrame({**frame, "AAA": prices(rng.normal(0.0003, 0.01, N))}, index=IDX)
    fred = {"DGS10": rates(rng)}
    a = run_test(spec(), closes, fred, variations=1, seed=3)
    b = run_test(spec(), closes, fred, variations=1, seed=3)
    assert a == b
    assert len(a["curve"]) <= 600 and a["curve"][-1]["t"] == a["data_end"]
    assert [c["name"] for c in a["context"]] == ["Idea", "SPY", "QQQ", "IWM"]
    assert a["periods"]["of"] == 5 and a["variations"] == 1


def test_signflip_null_is_centred_for_a_low_vol_hold():
    # Review finding 2: hold grows at exactly the benchmark's geometric rate, at almost no volatility. The claim
    # is a coin flip, so the shuffle must sit near the middle, not hand the idea an easy "beats chance".
    rng = np.random.default_rng(11)
    spy = rng.normal(0.0003, 0.025, N)
    k = int((N - 1) * 0.7) + 1  # the unseen span starts here (one row is lost to pct_change)
    flat = np.full(N, np.expm1(np.mean(np.log1p(spy[k:]))))  # exactly SPY's growth on the unseen years
    closes = pd.DataFrame({"SPY": prices(spy), "QQQ": prices(spy), "IWM": prices(spy), "AAA": prices(flat)}, index=IDX)
    s = IdeaSpec(title="calm asset", hold=["AAA"], claim="beats_benchmark")
    out = run_test(s, closes, {}, variations=1, seed=5, permutations=400)
    assert 35 < out["shuffle"]["beats_pct"] < 65
    assert out["verdict"] != "PASS"


def test_nan_permutation_counts_against_the_idea():
    from tradehub.workshop.engine import p_value
    p, beats = p_value(1.0, np.array([0.0, np.nan, 0.5, np.nan]))
    assert p == pytest.approx((1 + 2) / 5) and beats == pytest.approx(50.0)


def test_daily_frame_matches_run_test():
    from tradehub.workshop.engine import claim_check, daily_frame
    rng, spy, frame = market(1)
    fred = {"DGS10": rates(rng)}
    closes = pd.DataFrame({**frame, "AAA": prices(spy + rng.normal(0.0002, 0.004, N))}, index=IDX)
    s = spec()
    df = daily_frame(s, closes, fred)
    assert list(df.columns) == ["ret", "on", "bench", "spy"] and df.index[0] == IDX[1]
    out = run_test(s, closes, fred, variations=1, seed=7)
    k = int(len(df) * (1 - s.unseen_fraction))
    unseen = claim_check(s, df.iloc[k:])
    assert unseen["value"] == pytest.approx(out["claim"]["unseen"]["value"])
    assert unseen["holds"] == out["claim"]["unseen"]["holds"] and unseen["days"] == len(df) - k
