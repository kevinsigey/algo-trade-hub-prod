"""Dune as a Workshop data source (crypto step 3, Kevin, 2026-11-03):
spec validation, the cache reader, the rule_series wiring and an
end-to-end engine hit on a dune condition."""

from datetime import date

import pandas as pd
import pytest

from tradehub.workshop.data import UnknownSymbol, rule_series
from tradehub.workshop.dune import dune_series, list_dune_series
from tradehub.workshop.spec import IdeaSpec

POINTS = [{"date": f"2026-01-{d:02d}", "value": float(d)} for d in range(1, 29)]


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def execute(self):
        class R:
            pass

        r = R()
        r.data = self._rows
        return r


class FakeSupa:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _Q(self._rows)


def _spec(**kw):
    base = {"title": "USDT cost gate", "hold": ["BITO"], "claim": "beats_benchmark_when",
            "rules": {"enter": {"mode": "all", "conditions": [
                {"source": "dune", "series": "USDT_REMIT_COST", "measure": "level",
                 "lookback_days": 10, "op": ">", "threshold": 5.0}]}}}
    base.update(kw)
    return IdeaSpec.model_validate(base)


def test_spec_accepts_dune_and_refuses_wrong_measures():
    assert _spec().rules.enter.conditions[0].source == "dune"
    with pytest.raises(Exception, match="can't be measured"):
        _spec(rules={"enter": {"mode": "all", "conditions": [
            {"source": "dune", "series": "USDT_REMIT_COST", "measure": "rsi", "op": ">", "threshold": 1}]}})


def test_dune_series_reads_points_and_refuses_empty():
    s = dune_series("USDT_REMIT_COST", date(2026, 1, 10), supa=FakeSupa([{"points": POINTS}]))
    assert len(s) == 19 and s.iloc[0] == 10.0
    with pytest.raises(UnknownSymbol, match="no Dune series is cached"):
        dune_series("NOPE", date(2026, 1, 1), supa=FakeSupa([]))
    with pytest.raises(UnknownSymbol, match="no points on or after"):
        dune_series("USDT_REMIT_COST", date(2027, 1, 1), supa=FakeSupa([{"points": POINTS}]))


def test_catalogue_reports_the_span():
    out = list_dune_series(supa=FakeSupa([{"key": "USDT_REMIT_COST", "query_id": 8871549,
                                           "value_column": "crypto_total_cost", "points": POINTS,
                                           "updated_at": "2026-11-03T00:00:00Z"}]))
    assert out[0]["n_points"] == 28 and out[0]["first_date"] == "2026-01-01" and out[0]["last_date"] == "2026-01-28"


def test_rule_series_wires_the_dune_branch():
    stub = pd.Series([7.0], index=pd.DatetimeIndex(["2026-01-05"]), name="USDT_REMIT_COST")
    out = rule_series(_spec(), date(2023, 1, 1), fred=lambda i, s: pd.Series(dtype=float),
                      dune_fn=lambda key, start: stub)
    assert out["USDT_REMIT_COST"].iloc[0] == 7.0


def test_engine_hit_uses_the_publication_lag():
    from tradehub.workshop.engine import condition_mask

    idx = pd.bdate_range("2026-01-01", periods=12)
    closes = pd.DataFrame({"BITO": [100.0] * 12, "SPY": [100.0] * 12}, index=idx)
    # The series jumps above the threshold on day index 5 (value 20 > 5);
    # with the t-2 lag the idea may only be in from day index 7.
    vals = [1.0] * 5 + [20.0] * 7
    series = pd.Series(vals, index=idx, name="USDT_REMIT_COST")
    mask = condition_mask(_spec(), closes, {"USDT_REMIT_COST": series})
    assert not mask.iloc[:7].any()
    assert mask.iloc[7]
