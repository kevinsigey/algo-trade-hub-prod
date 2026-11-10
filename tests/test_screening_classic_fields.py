"""Classic-screen fields (Kevin's build go, 2026-11-09): the three classic
screens (Graham / Buffett / O'Neil) need four fields the catalog did not
carry -- diluted-EPS growth YoY and QoQ and revenue growth QoQ from the
quarterly statements, and 5-year diluted-EPS CAGR from EDGAR annual filings.
These tests pin the math, the NaN discipline (a % change on a non-positive
base is not a growth rate; a missing quarter is missing, never zero), and
that the three screens' specs validate against the catalog as written."""

import math

import numpy as np
import pandas as pd
import pytest

from tradehub.screening.functions import REGISTRY
from tradehub.screening.sources import _annual_series
from tradehub.screening.spec import validate_spec


class FakeStore:
    """Statements + EDGAR annual series, no network."""

    def __init__(self, income=None, annual=None):
        self._income = income or {}
        self._annual = annual or {}
        self.missing = []
        self.asof = {}

    def note_missing(self, ticker, field, reason):
        self.missing.append({"ticker": ticker, "field": field, "reason": str(reason)})

    def statements(self, ticker):
        return {"income": self._income.get(ticker, pd.DataFrame()),
                "balance": pd.DataFrame(), "cashflow": pd.DataFrame()}

    def edgar_annual_series(self, ticker, concept):
        return self._annual.get((ticker, concept))


def _income(eps=None, revenue=None):
    data = {}
    if eps is not None:
        data["Diluted EPS"] = eps
    if revenue is not None:
        data["Total Revenue"] = revenue
    cols = pd.date_range("2026-09-30", periods=max(len(v) for v in data.values()),
                         freq="QE")[::-1]
    return pd.DataFrame(data, index=cols).T  # rows = line items, cols = period ends


def test_eps_growth_qoq_and_yoy_math():
    store = FakeStore(income={"AAA": _income(eps=[2.5, 2.0, 1.8, 1.6, 2.0])})
    qoq = REGISTRY["eps_growth_qoq"]["fn"](store, ["AAA"])
    yoy = REGISTRY["eps_growth_yoy"]["fn"](store, ["AAA"])
    assert qoq["AAA"] == pytest.approx(25.0)   # 2.5 vs prior quarter 2.0
    assert yoy["AAA"] == pytest.approx(25.0)   # 2.5 vs same quarter last year 2.0


def test_revenue_growth_qoq_math():
    store = FakeStore(income={"AAA": _income(revenue=[132.0, 120.0])})
    out = REGISTRY["revenue_growth_qoq"]["fn"](store, ["AAA"])
    assert out["AAA"] == pytest.approx(10.0)


def test_growth_on_a_nonpositive_base_is_missing_never_a_number():
    store = FakeStore(income={"AAA": _income(eps=[0.5, -0.25, 1.0, 1.0, 1.0])})
    out = REGISTRY["eps_growth_qoq"]["fn"](store, ["AAA"])
    assert math.isnan(out["AAA"])
    assert any(m["field"] == "eps_growth_qoq" for m in store.missing)


def test_growth_skips_unpopulated_quarters():
    # yfinance leaves the newest quarter's EPS row NaN until it populates;
    # the latest REPORTED quarter is the data point, not the empty column.
    store = FakeStore(income={"AAA": _income(eps=[np.nan, 2.0, 1.6, 1.5, 1.4, 1.25])})
    out = REGISTRY["eps_growth_qoq"]["fn"](store, ["AAA"])
    assert out["AAA"] == pytest.approx(25.0)


def test_growth_with_too_few_quarters_is_missing():
    store = FakeStore(income={"AAA": _income(eps=[2.0, 1.9])})
    out = REGISTRY["eps_growth_yoy"]["fn"](store, ["AAA"])
    assert math.isnan(out["AAA"])
    assert any(m["field"] == "eps_growth_yoy" for m in store.missing)


def test_eps_growth_5y_is_a_cagr_on_edgar_annual_eps():
    series = [("2021-09-25", 5.61), ("2022-09-24", 6.11), ("2023-09-30", 6.13),
              ("2024-09-28", 6.08), ("2025-09-27", 7.46), ("2026-09-26", 8.98)]
    store = FakeStore(annual={("AAPL", "EarningsPerShareDiluted"): series})
    out = REGISTRY["eps_growth_5y"]["fn"](store, ["AAPL"])
    years = (pd.Timestamp("2026-09-26") - pd.Timestamp("2021-09-25")).days / 365.25
    assert out["AAPL"] == pytest.approx(((8.98 / 5.61) ** (1 / years) - 1) * 100, abs=0.05)


def test_eps_growth_5y_refuses_a_loss_base_and_a_short_history():
    store = FakeStore(annual={
        ("AAA", "EarningsPerShareDiluted"): [("2021-12-31", -1.0), ("2026-12-31", 2.0)],
        ("BBB", "EarningsPerShareDiluted"): [("2024-12-31", 1.0), ("2026-12-31", 1.5)],
    })
    out = REGISTRY["eps_growth_5y"]["fn"](store, ["AAA", "BBB"])
    assert math.isnan(out["AAA"]) and math.isnan(out["BBB"])
    assert {m["ticker"] for m in store.missing if m["field"] == "eps_growth_5y"} == {"AAA", "BBB"}


def test_annual_series_takes_full_year_rows_and_restatements_win():
    rows = [
        {"start": "2020-09-27", "end": "2021-09-25", "val": 5.50, "fp": "FY", "filed": "2021-10-29"},
        {"start": "2020-09-27", "end": "2021-09-25", "val": 5.61, "fp": "FY", "filed": "2023-11-03"},
        {"start": "2021-06-27", "end": "2021-09-25", "val": 1.30, "fp": "Q3", "filed": "2021-10-29"},
        {"start": "2019-09-29", "end": "2021-09-25", "val": 9.90, "fp": "FY", "filed": "2021-10-29"},
    ]
    assert _annual_series(rows) == [("2021-09-25", 5.61)]


GRAHAM = {"name": "Graham value (classic)",
          "universe": {"type": "index", "index": "nasdaq_all"},
          "filters": [{"fn": "pe_ratio", "op": "lt", "value": 7},
                      {"fn": "price_to_book", "op": "lt", "value": 1.5},
                      {"fn": "debt_to_equity", "op": "lt", "value": 0.5},
                      {"fn": "current_ratio", "op": "gt", "value": 1.5}],
          "sort": {"by": "pe_ratio", "ascending": True}}

BUFFETT = {"name": "Buffett quality (classic)",
           "universe": {"type": "index", "index": "nasdaq_all"},
           "filters": [{"fn": "roe", "op": "gt", "value": 15},
                       {"fn": "net_margin", "op": "gt", "value": 10},
                       {"fn": "eps_growth_5y", "op": "gt", "value": 10},
                       {"fn": "debt_to_equity", "op": "lt", "value": 0.5}],
           "sort": {"by": "roe", "ascending": False}}

ONEIL = {"name": "O'Neil growth (classic)",
         "universe": {"type": "index", "index": "nasdaq_all"},
         "filters": [{"fn": "eps_growth_yoy", "op": "gt", "value": 20},
                     {"fn": "eps_growth_qoq", "op": "gt", "value": 20},
                     {"fn": "revenue_growth_qoq", "op": "gt", "value": 20},
                     {"fn": "roe", "op": "gt", "value": 15}],
         "sort": {"by": "eps_growth_yoy", "ascending": False}}


@pytest.mark.parametrize("spec", [GRAHAM, BUFFETT, ONEIL])
def test_the_three_classic_screen_specs_validate(spec):
    assert validate_spec(spec) is spec
