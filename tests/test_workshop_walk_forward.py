"""Walk-forward folds and the late-listing note (critique plan L9).

The built/unseen split judges a claim once, on the last stretch; the walk-forward re-judges it
on each successive stretch so an edge that only ever worked recently reads differently from one
that held throughout. And because `_frame` drops any day a leg has no close, a late-listing leg
silently truncates the whole test -- the note is what makes that truncation visible.
"""
import numpy as np
import pandas as pd

from tradehub.workshop.engine import run_test
from tradehub.workshop.spec import IdeaSpec

N = 5000
IDX = pd.bdate_range("2006-01-03", periods=N)


def prices(returns: np.ndarray) -> np.ndarray:
    return 100 * np.cumprod(1 + returns)


def market(seed=0, drift=0.0004):
    rng = np.random.default_rng(seed)
    spy = rng.normal(0.0003, 0.01, N)
    frame = {"SPY": prices(spy), "AAA": prices(spy + drift + rng.normal(0, 0.004, N))}
    return pd.DataFrame(frame, index=IDX)


def test_walk_forward_judges_each_later_fold_in_order():
    out = run_test(IdeaSpec(title="steady edge", hold=["AAA"], claim="beats_benchmark"),
                   market(3), {}, variations=1, seed=1)
    wf = out["walk_forward"]
    assert wf["of"] == 4  # five folds, the first is the built-on ground and is skipped
    assert wf["held"] == 4  # the planted edge is steady, so it holds on every later fold
    starts = [f["start"] for f in wf["folds"]]
    assert starts == sorted(starts) and len(set(starts)) == 4
    assert starts[0] > out["data_start"]  # sequential: later folds start after the data does
    assert all(f["holds"] is True and f["days"] >= 63 for f in wf["folds"])


def test_walk_forward_is_reported_even_when_there_is_not_enough_data():
    closes = market(4).iloc[:300]
    out = run_test(IdeaSpec(title="too short", hold=["AAA"], claim="beats_benchmark"),
                   closes, {}, variations=1, seed=1)
    assert out["verdict"] == "NOT ENOUGH DATA"
    wf = out["walk_forward"]
    assert wf["of"] == 0 and wf["held"] == 0
    assert wf["folds"] and all(f["holds"] is None for f in wf["folds"])


def test_a_late_listing_leg_is_noted_and_the_truncation_is_visible():
    closes = market(5)
    listed = 2500  # NEWCO "IPOs" half-way through the timeline
    newco = np.full(N, np.nan)
    newco[listed:] = prices(np.random.default_rng(6).normal(0.0003, 0.01, N - listed))
    closes["NEWCO"] = newco
    out = run_test(IdeaSpec(title="newco vs spy", hold=["NEWCO"], claim="beats_benchmark"),
                   closes, {}, variations=1, seed=1)
    first = str(IDX[listed].date())
    # The whole test silently started at the listing (data_start is the first returns day, one
    # business day after the first close)... except now the note says so, with the listing date.
    assert out["data_start"] > first and out["data_start"].startswith("2015-08")
    assert any(n.startswith(f"NEWCO has no prices before {first}") for n in out["notes"])


def test_full_history_legs_have_no_notes():
    out = run_test(IdeaSpec(title="steady edge", hold=["AAA"], claim="beats_benchmark"),
                   market(7), {}, variations=1, seed=1)
    assert out["notes"] == []
