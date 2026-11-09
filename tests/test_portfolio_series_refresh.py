"""The weekly series refresh's math: sleeve series are market-value-weighted
blends of member returns at refresh time, the book series is the whole book's,
and an unheld sleeve falls back to equal weights so a future order into it
still has a series to correlate."""
import pandas as pd
import pytest

from tradehub.portfolio.portfolio_check import DEFAULT_CONFIG
from tradehub.scripts.portfolio_series_refresh import build_series

DATES = pd.to_datetime(["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"])


def _frame():
    return pd.DataFrame({
        "GLD": [100.0, 110.0, 99.0, 99.0],    # +10%, -10%, 0%
        "XLP": [50.0, 50.0, 55.0, 55.0],      # 0%, +10%, 0%
        "SPY": [10.0, 10.0, 10.0, 10.0],      # flat
        "AAPL": [10.0, 11.0, 11.0, 11.0],     # +10%, 0%, 0%
    }, index=DATES)


def test_sleeve_series_blends_members_by_market_value():
    positions = {"GLD": {"mv": 300.0}, "XLP": {"mv": 100.0}, "SPY": {"mv": 100.0}}
    series = build_series(positions, _frame(), DEFAULT_CONFIG)
    ballast = dict(series["t4_ballast"])
    assert ballast["2026-11-03"] == pytest.approx(0.075)   # (0.10*300 + 0*100)/400
    assert ballast["2026-11-04"] == pytest.approx(-0.05)   # (-0.10*300 + 0.10*100)/400
    assert ballast["2026-11-05"] == pytest.approx(0.0)


def test_book_series_is_the_whole_book_by_invested_share():
    positions = {"GLD": {"mv": 300.0}, "XLP": {"mv": 100.0}, "SPY": {"mv": 100.0}}
    series = build_series(positions, _frame(), DEFAULT_CONFIG)
    book = dict(series["__book__"])
    assert book["2026-11-03"] == pytest.approx(0.06)       # 0.10 * 300/500
    assert len(series["__book__"]) == 3


def test_an_unheld_sleeve_falls_back_to_equal_weights():
    positions = {"GLD": {"mv": 300.0}}
    series = build_series(positions, _frame(), DEFAULT_CONFIG)
    t8 = dict(series["t8_ai"])  # only AAPL has data among the T8 members
    assert t8["2026-11-03"] == pytest.approx(0.10)


def test_symbol_series_are_stored_too():
    positions = {"GLD": {"mv": 300.0}}
    series = build_series(positions, _frame(), DEFAULT_CONFIG)
    gld = dict(series["sym:GLD"])
    assert gld["2026-11-03"] == pytest.approx(0.10)
    assert gld["2026-11-04"] == pytest.approx(-0.10)
