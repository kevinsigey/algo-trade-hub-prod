from datetime import date

import numpy as np
import pandas as pd

from tradehub.workshop.engine import MIN_GATE_DAYS, gate_check
from tradehub.workshop.spec import IdeaSpec

SPEC = IdeaSpec(title="AAA beats SPY", hold=["AAA"], claim="beats_benchmark")
PAIR = IdeaSpec(title="AAA and BBB beat SPY", hold=["AAA", "BBB"], claim="beats_benchmark")
END = date(2025, 12, 31)


def frame(before: float, after: float, n_after: int, n_before: int = 300, split: int | None = None):
    """Daily rows; the idea beats the benchmark by `before`/`after` per day either side of END."""
    idx = pd.bdate_range(end=pd.Timestamp(END), periods=n_before).append(
        pd.bdate_range(start=pd.Timestamp(END) + pd.Timedelta(days=1), periods=n_after))
    rng = np.random.default_rng(0)
    bench = rng.normal(0.0003, 0.01, len(idx))
    edge = np.r_[np.full(n_before, before), np.full(n_after, after)]
    if split is not None:  # the oldest `split` new days get the opposite edge
        edge[n_before:n_before + split] = -after
    return pd.DataFrame({"ret": bench + edge, "on": True, "bench": bench, "spy": bench}, index=idx)


def test_gate_uses_only_new_days():
    bad = gate_check(SPEC, frame(0.002, -0.002, 100), END, 20)
    assert bad["status"] == "fails" and not bad["claim"]["holds"] and bad["new_days"] == 100
    good = gate_check(SPEC, frame(-0.002, 0.002, 100), END, 20)
    assert good["status"] == "ready" and good["size_ok"] and good["reasons"] == []


def test_gate_waits():
    out = gate_check(SPEC, frame(0.002, 0.002, 40), END, 20)
    assert out["status"] == "waiting" and out["new_days"] == 40 and out["needed"] == MIN_GATE_DAYS == 63
    assert "40 of 63 new trading days" in out["reasons"][0]


def test_gate_window_is_last_252():
    out = gate_check(SPEC, frame(0.0, 0.002, 400, split=148), END, 20)
    assert out["status"] == "ready" and out["claim"]["days"] == 252


def test_gate_size():
    over = gate_check(PAIR, frame(0.0, 0.002, 100).assign(), END, 60)
    assert over["size_ok"] is False and over["status"] == "fails"
    assert any("30%" in r and "25%" in r for r in over["reasons"])
    none = gate_check(PAIR, frame(0.0, 0.002, 100), END, None)
    assert none["size_ok"] is None and none["status"] != "ready"


WHEN = IdeaSpec(title="AAA beats SPY when rates rise", hold=["AAA"], otherwise="SPY", claim="beats_benchmark_when",
                when={"source": "fred", "series": "DGS10", "measure": "change", "op": ">", "threshold": 0.25})


def test_condition_absent_on_new_data_waits_instead_of_failing():
    # Review finding 7: no condition days in the new data is "not judged yet", not a failed claim.
    out = gate_check(WHEN, frame(0.0, 0.002, 100).assign(on=False), END, 20)
    assert out["status"] == "waiting" and any("condition" in r for r in out["reasons"])
