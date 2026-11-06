"""Guidance-change screening fields (Kevin, 2026-11-06): the capex kill-zone
screen needs the change between a company's two most recent guides for the
same period, read from the guidance recorder's table. The math is a pure
function over record dicts; the fetch is monkeypatched here."""

import numpy as np
import pytest

from tradehub.screening import functions
from tradehub.screening.functions import REGISTRY, _latest_guide_change
from tradehub.screening.spec import validate_spec


def rec(period, low, high, at, metric="capex", evidence=""):
    return {"ticker": "AAA", "period": period, "metric": metric, "low": low,
            "high": high, "evidence": evidence, "created_at": at}


def test_change_is_between_the_two_latest_guides_for_a_period():
    rows = [rec("FY27", 80, 100, "2026-09-01"), rec("FY27", 90, 100, "2026-11-05")]
    assert _latest_guide_change(rows) == pytest.approx((95 - 90) / 90 * 100)


def test_change_uses_last_two_when_three_guides_exist():
    rows = [rec("FY27", 50, 50, "2026-01-01"), rec("FY27", 80, 80, "2026-06-01"),
            rec("FY27", 60, 60, "2026-11-01")]
    assert _latest_guide_change(rows) == pytest.approx(-25.0)


def test_change_picks_the_period_with_the_newest_guide():
    rows = [rec("FY26", 10, 10, "2026-01-01"), rec("FY26", 20, 20, "2026-02-01"),
            rec("FY27", 100, 100, "2026-03-01"), rec("FY27", 90, 90, "2026-11-01")]
    assert _latest_guide_change(rows) == pytest.approx(-10.0)


def test_change_is_none_without_a_prior_guide():
    assert _latest_guide_change([rec("FY27", 90, 100, "2026-11-05")]) is None
    assert _latest_guide_change([]) is None
    assert _latest_guide_change([rec("FY27", None, None, "2026-11-05"),
                                 rec("FY27", 90, 100, "2026-11-06")]) is None


class FakeStore:
    def __init__(self):
        self.missing = []

    def note_missing(self, ticker, field, reason):
        self.missing.append((ticker, field, reason))


@pytest.fixture
def rows(monkeypatch):
    data = {
        ("AAA", "capex"): [rec("FY27", 80, 100, "2026-09-01"), rec("FY27", 90, 100, "2026-11-05")],
        ("BBB", "capex"): [{**rec("FY27", 10, 12, "2026-11-05"), "ticker": "BBB"}],
        ("AAA", "other"): [
            {**rec("FY27", 40, 44, "2026-09-01", metric="other"), "evidence": "free cash flow of $40-44B"},
            {**rec("FY27", 30, 34, "2026-11-05", metric="other"), "evidence": "free cash flow guidance $30-34B"},
            {**rec("FY27", 1, 2, "2026-11-05", metric="other"), "evidence": "dividend raised"}],
    }
    monkeypatch.setattr(functions, "_guidance_rows",
                        lambda tickers, metric: [r for (t, m), rs in data.items()
                                                 if m == metric and t in tickers for r in rs])
    return data


def test_capex_field_reads_the_recorder_and_notes_missing(rows):
    store = FakeStore()
    out = functions.capex_guide_change_pct(store, ["AAA", "BBB"])
    assert out["AAA"] == pytest.approx((95 - 90) / 90 * 100)
    assert np.isnan(out["BBB"])
    assert store.missing and store.missing[0][0] == "BBB"


def test_fcf_field_only_counts_free_cash_flow_evidence(rows):
    store = FakeStore()
    out = functions.fcf_guide_change_pct(store, ["AAA"])
    assert out["AAA"] == pytest.approx((32 - 42) / 42 * 100)


def test_kill_zone_spec_validates():
    assert "capex_guide_change_pct" in REGISTRY and "fcf_guide_change_pct" in REGISTRY
    validate_spec({"name": "kz", "universe": {"type": "list", "tickers": ["MSFT", "ORCL"]},
                   "filters": [{"fn": "capex_guide_change_pct", "op": "gt", "value": 0},
                               {"fn": "fcf_guide_change_pct", "op": "lt", "value": 0}]})
