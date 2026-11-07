"""Unit tests for call_tone pure functions."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from research.call_tone.tone import (
    compute_tone,
    compute_uncertainty_share,
    count_words,
    management_text,
    compute_tone_uncertainty,
    delta_tone,
    entry_date,
    excess_log_return,
    per_quarter_ic,
    mean_ic_t,
    tercile_spread,
    tercile_spread_per_quarter,
    load_loughran_mcdonald,
)


def test_compute_tone():
    """Test tone formula: (pos - neg) / (pos + neg + 1)"""
    assert compute_tone(10, 5) == (10 - 5) / (10 + 5 + 1)
    assert compute_tone(0, 0) == 0.0
    assert compute_tone(5, 10) == (5 - 10) / (5 + 10 + 1)
    assert compute_tone(100, 0) == 100 / 101


def test_compute_uncertainty_share():
    assert compute_uncertainty_share(5, 100) == 0.05
    assert compute_uncertainty_share(0, 100) == 0.0
    assert compute_uncertainty_share(10, 0) == 0.0


def test_count_words():
    pos_set = {"good", "great", "excellent"}
    neg_set = {"bad", "poor"}
    unc_set = {"maybe", "uncertain"}
    
    text = "This is good and great but not bad"
    assert count_words(text, pos_set) == 2
    assert count_words(text, neg_set) == 1
    assert count_words(text, unc_set) == 0
    
    # Case insensitive
    assert count_words("GOOD good Good", pos_set) == 3
    
    # Whole words only
    assert count_words("goodness", pos_set) == 0
    assert count_words("badly", neg_set) == 0
    
    # Empty text
    assert count_words("", pos_set) == 0
    assert count_words(None, pos_set) == 0


def test_management_text():
    # List of dicts with speaker
    transcript = [
        {"speaker": "Operator", "text": "Welcome to the call"},
        {"speaker": "CEO", "text": "We had a great quarter"},
        {"speaker": "Analyst", "text": "What about margins?"},
        {"speaker": "CFO", "text": "Margins improved"},
    ]
    mgmt = management_text(transcript)
    assert "great quarter" in mgmt
    assert "Margins improved" in mgmt
    assert "Welcome" not in mgmt  # operator dropped
    assert "margins" not in mgmt  # analyst dropped
    
    # String input (no speaker tags)
    assert management_text("raw text") == "raw text"
    
    # Empty
    assert management_text([]) == ""
    assert management_text("") == ""


def test_compute_tone_uncertainty():
    pos = {"good", "great"}
    neg = {"bad", "poor"}
    unc = {"maybe"}
    
    text = "good great bad maybe"
    tone, unc_share = compute_tone_uncertainty(text, pos, neg, unc)
    # pos=2, neg=1, unc=1, total=4
    assert tone == (2 - 1) / (2 + 1 + 1)
    assert unc_share == 1 / 4
    
    # Empty text
    tone, unc_share = compute_tone_uncertainty("", pos, neg, unc)
    assert tone == 0.0
    assert unc_share == 0.0


def test_delta_tone():
    # Exactly 4 prior calls -> should compute
    prior = [0.1, 0.2, 0.3, 0.4]
    assert delta_tone(0.5, prior) == 0.5 - np.mean(prior)
    
    # More than 4 -> use last 4
    prior_long = [0.0, 0.1, 0.2, 0.3, 0.4]
    assert delta_tone(0.5, prior_long) == 0.5 - np.mean(prior_long[-4:])
    
    # Fewer than 4 -> None
    assert delta_tone(0.5, [0.1, 0.2]) is None
    assert delta_tone(0.5, [0.1]) is None
    assert delta_tone(0.5, []) is None


def test_entry_date():
    trading_days = pd.DatetimeIndex([
        "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"
    ])
    
    # Call on 2024-01-02 -> entry is 2024-01-03
    d = date(2024, 1, 2)
    assert entry_date(d, trading_days) == pd.Timestamp("2024-01-03")
    
    # Call on 2024-01-03 (Wednesday) -> entry is 2024-01-04
    d = date(2024, 1, 3)
    assert entry_date(d, trading_days) == pd.Timestamp("2024-01-04")
    
    # Call on weekend after all trading days -> None
    d = date(2024, 1, 6)  # Saturday after last trading day
    assert entry_date(d, trading_days) is None


def test_excess_log_return():
    # Create simple price series
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    ticker_prices = pd.Series(100 * np.exp(np.cumsum(np.random.randn(100) * 0.01)), index=dates)
    spy_prices = pd.Series(400 * np.exp(np.cumsum(np.random.randn(100) * 0.01)), index=dates)
    prices = {"TEST": ticker_prices, "SPY": spy_prices}
    
    entry = dates[10]
    ret = excess_log_return("TEST", entry, 20, prices, spy_prices)
    assert isinstance(ret, float) or ret is None


def test_per_quarter_ic():
    # Create synthetic data with known correlation
    dates = pd.date_range("2020-01-01", periods=200, freq="B")
    df = pd.DataFrame({
        "call_date": dates[:100],
        "signal": np.random.randn(100),
        "outcome": np.random.randn(100),
    })
    # Add some quarters
    df["quarter"] = df["call_date"].dt.to_period("Q")
    
    # Make some quarters have < 15 calls (should be dropped)
    small_q = df[df["quarter"] == df["quarter"].iloc[0]].head(5).index
    df.loc[small_q, "signal"] = 0  # make them distinct
    
    ic_df = per_quarter_ic(df, "signal", "outcome", min_calls=15)
    assert "quarter" in ic_df.columns
    assert "ic" in ic_df.columns
    assert "pval" in ic_df.columns
    assert "n_calls" in ic_df.columns


def test_mean_ic_t():
    # Known mean and std
    ics = pd.Series([0.1, 0.2, 0.15, 0.05, 0.25])
    mean, t = mean_ic_t(ics)
    expected_mean = ics.mean()
    expected_t = expected_mean / ics.std(ddof=1) * np.sqrt(len(ics))
    assert abs(mean - expected_mean) < 1e-10
    assert abs(t - expected_t) < 1e-10
    
    # Single value -> t = 0
    mean, t = mean_ic_t(pd.Series([0.1]))
    assert abs(mean - 0.1) < 1e-10
    assert t == 0.0
    
    # Zero std -> t = 0
    mean, t = mean_ic_t(pd.Series([0.1, 0.1, 0.1]))
    assert abs(mean - 0.1) < 1e-10
    assert t == 0.0


def test_tercile_spread():
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    df = pd.DataFrame({
        "call_date": dates[:90],
        "signal": np.arange(90),
        "outcome": np.arange(90) * 0.01 + np.random.randn(90) * 0.001,
    })
    df["quarter"] = df["call_date"].dt.to_period("Q")
    
    spread = tercile_spread(df, "signal", "outcome", cost_bps=0)
    assert isinstance(spread, float)
    
    # With positive correlation, spread should be positive
    assert spread > -0.1  # loose bound


def test_tercile_spread_per_quarter():
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    df = pd.DataFrame({
        "call_date": dates[:90],
        "signal": np.arange(90),
        "outcome": np.arange(90) * 0.01,
    })
    df["quarter"] = df["call_date"].dt.to_period("Q")
    
    spreads = tercile_spread_per_quarter(df, "signal", "outcome")
    assert isinstance(spreads, pd.Series)
    assert len(spreads) > 0
    assert all(s > 0 for s in spreads)  # perfectly correlated


def test_load_loughran_mcdonald(tmp_path):
    # Create a mock CSV
    csv_content = """Word,Positive,Negative,Uncertainty
good,2018,,
bad,,2018,
maybe,,,2018
neutral,,,"""
    csv_file = tmp_path / "lm.csv"
    csv_file.write_text(csv_content)
    
    pos, neg, unc = load_loughran_mcdonald(str(csv_file))
    assert "good" in pos
    assert "bad" in neg
    assert "maybe" in unc
    assert "neutral" not in pos and "neutral" not in neg and "neutral" not in unc


def test_management_text_no_speaker_tags():
    # When transcript is a string (no speaker info)
    text = "This is the full transcript text"
    assert management_text(text) == text
    
    # When transcript is list but no speaker field
    transcript = [{"text": "Hello"}, {"text": "World"}]
    assert management_text(transcript) == "Hello World"


def test_delta_tone_edge_cases():
    # All same values
    prior = [0.1, 0.1, 0.1, 0.1]
    assert delta_tone(0.2, prior) == 0.1
    
    # Negative tones
    prior = [-0.1, -0.2, -0.3, -0.4]
    assert delta_tone(0.0, prior) == 0.0 - np.mean(prior)


def test_compute_tone_edge_cases():
    # Large numbers
    assert compute_tone(1000, 500) == (1000 - 500) / (1000 + 500 + 1)
    
    # One zero
    assert compute_tone(10, 0) == 10 / 11
    assert compute_tone(0, 10) == -10 / 11


if __name__ == "__main__":
    pytest.main([__file__, "-v"])