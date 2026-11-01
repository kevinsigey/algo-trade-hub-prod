"""The Workshop revision measure (phase-2 §5.2): how far the freshest print has
been revised from its first print, built from ALFRED vintages on the labor
scoreboard's month-end grid, with first_prints' own rule for what a first print is."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradehub.workshop import data
from tradehub.workshop.spec import Condition, IdeaSpec

VINTAGES = {
    date(2025, 7, 31): {date(2025, 6, 1): 1000.0, date(2025, 7, 1): 1100.0},
    date(2025, 8, 31): {date(2025, 6, 1): 1000.0, date(2025, 7, 1): 1100.0, date(2025, 8, 1): 1250.0},
    date(2025, 9, 30): {date(2025, 6, 1): 1000.0, date(2025, 7, 1): 1120.0,
                        date(2025, 8, 1): 1230.0, date(2025, 9, 1): 1400.0},
    date(2025, 10, 31): {date(2025, 6, 1): 1000.0, date(2025, 7, 1): 1120.0,
                         date(2025, 8, 1): 1230.0, date(2025, 9, 1): 1380.0, date(2025, 10, 1): 1530.0},
}


def _vintages_fn(series_id, grid):
    return {v: VINTAGES[v] for v in grid if v in VINTAGES}


def test_revision_series_tracks_the_freshest_prints_revision():
    series = data.revision_series("PAYEMS", date(2025, 7, 1), vintages_fn=_vintages_fn, today=date(2025, 11, 15))
    # Each vintage's freshest print starts unrevised (0); by the October vintage the
    # freshest print is October's own (fresh, 0) -- September's -20 revision lands in
    # the October vintage's history but the emitted point tracks the NEWEST month.
    assert series.loc[date(2025, 7, 31)] == 0.0
    assert series.loc[date(2025, 8, 31)] == 0.0
    assert series.loc[date(2025, 9, 30)] == 0.0
    assert series.loc[date(2025, 10, 31)] == 0.0


def test_revision_series_prices_a_revision_when_the_newest_month_is_revised():
    """Same grid, but October brings no new month (a shutdown-style gap): the newest
    month in the October vintage is still September, now revised +150 -> +130."""
    vintages = dict(VINTAGES)
    vintages[date(2025, 10, 31)] = {date(2025, 6, 1): 1000.0, date(2025, 7, 1): 1120.0,
                                    date(2025, 8, 1): 1230.0, date(2025, 9, 1): 1530.0}
    series = data.revision_series("PAYEMS", date(2025, 7, 1),
                                  vintages_fn=lambda s, g: {v: vintages[v] for v in g if v in vintages},
                                  today=date(2025, 11, 15))
    assert series.loc[date(2025, 10, 31)] == 130.0  # current change 300 (1530-1230) - first print 170


def test_spec_takes_revision_on_fred_and_refuses_it_elsewhere():
    ok = Condition(source="fred", series="PAYEMS", measure="revision", op=">", threshold=25)
    assert ok.measure == "revision"
    with pytest.raises(ValueError, match="can't be measured on a price series"):
        Condition(source="price", series="SPY", measure="revision", op=">", threshold=25)


def _spec() -> IdeaSpec:
    return IdeaSpec.model_validate({
        "title": "AAA when payroll revisions run hot",
        "claim": "beats_benchmark_when",
        "hold": ["AAA"], "benchmark": "SPY",
        "rules": {"enter": {"mode": "all", "conditions": [
            {"source": "fred", "series": "PAYEMS", "measure": "revision", "op": ">", "threshold": 25}]}},
    })


def test_rule_series_routes_revision_ids_to_the_vintage_builder():
    built = pd.Series([130.0], index=pd.to_datetime(["2025-10-31"]), name="PAYEMS@revision")
    out = data.rule_series(_spec(), date(2025, 1, 1),
                           fred=lambda i, s: pd.Series(dtype=float),
                           revision_fn=lambda series_id, s: built)
    assert out["PAYEMS@revision"] is built


def test_the_condition_reads_the_revision_series_with_the_fred_lag():
    from tradehub.workshop.engine import condition_mask
    idx = pd.bdate_range("2025-10-27", periods=8)
    closes = pd.DataFrame({"AAA": np.linspace(100, 107, 8), "SPY": np.linspace(100, 107, 8)}, index=idx)
    revision = pd.Series([0.0, 130.0], index=pd.to_datetime(["2025-10-27", "2025-10-28"]), name="PAYEMS@revision")
    mask = condition_mask(_spec(), closes, {"PAYEMS": pd.Series(dtype=float), "PAYEMS@revision": revision})
    # The revision prints 130 on Oct 28; with the FRED t-2 publication lag the rule
    # first holds on Oct 30's row (index 3), never on the day itself.
    assert mask.tolist() == [False, False, False, True, True, True, True, True]
