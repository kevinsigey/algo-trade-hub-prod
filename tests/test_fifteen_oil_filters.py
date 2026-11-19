"""Tests for step 18's two oil-filter candidates (v4-side50-shadow,
v4-spread3-shadow). Preregistration:
docs/superpowers/specs/2026-11-19-fifteen-oil-filters-prereg.md.

The pins: each filter refuses exactly the rows the deep dive condemned
(the model's own side under 50%; a spread under 3c), both candidates are
oil-only, and neither scores a window from before its own PREREG_AT --
the rows the filters were selected on never score them.
"""

from datetime import UTC, datetime, timedelta

from tradehub.fifteen_candidates import CANDIDATES, candidate_trade, evaluate

CLOSE = "2026-11-20T15:15:00+00:00"   # window_open 15:00Z, after both preregs
NOW = datetime(2026, 11, 21, tzinfo=UTC)


def _row(**over):
    row = {"series": "KXBRENT15M", "target": "kalshi:KXBRENT15M-X", "close_time": CLOSE,
           "offset_min": 5, "side": "yes", "outcome": 1, "pnl": 0.30,
           "edge_net": 0.15, "side_cost": 0.40, "prob_up": 0.62,
           "yes_bid": 0.36, "yes_ask": 0.40}
    row.update(over)
    return row


def test_side50_refuses_the_side_the_model_puts_under_half():
    long_shot = _row(side="yes", prob_up=0.42)          # YES rated 42%
    assert candidate_trade([long_shot], CANDIDATES["v4-side50-shadow"], "KXBRENT15M") is None
    no_long_shot = _row(side="no", prob_up=0.62)        # NO rated 38%
    assert candidate_trade([no_long_shot], CANDIDATES["v4-side50-shadow"], "KXBRENT15M") is None
    favoured = _row(side="no", prob_up=0.44)            # NO rated 56%
    assert candidate_trade([favoured], CANDIDATES["v4-side50-shadow"], "KXBRENT15M") is favoured
    unproven = _row(prob_up=None)
    assert candidate_trade([unproven], CANDIDATES["v4-side50-shadow"], "KXBRENT15M") is None


def test_spread3_refuses_tight_quotes():
    tight = _row(yes_bid=0.38, yes_ask=0.40)            # 2c spread
    assert candidate_trade([tight], CANDIDATES["v4-spread3-shadow"], "KXBRENT15M") is None
    thin = _row(yes_bid=0.36, yes_ask=0.40)             # 4c spread
    assert candidate_trade([thin], CANDIDATES["v4-spread3-shadow"], "KXBRENT15M") is thin
    no_quote = _row(yes_bid=None)
    assert candidate_trade([no_quote], CANDIDATES["v4-spread3-shadow"], "KXBRENT15M") is None


def test_both_filters_are_oil_only():
    gas = _row(series="KXNATGAS15M")
    for version in ("v4-side50-shadow", "v4-spread3-shadow"):
        assert candidate_trade([gas], CANDIDATES[version], "KXNATGAS15M") is None


def test_a_window_before_the_candidates_prereg_does_not_score():
    old_close = (datetime(2026, 11, 18, 15, 15, tzinfo=UTC)).isoformat()
    old = _row(close_time=old_close)                   # window_open Nov 18 < PREREG_AT Nov 19
    for version in ("v4-side50-shadow", "v4-spread3-shadow"):
        result = evaluate([old], version, now=NOW)
        assert result["windows"] == 0 and result["trades"] == 0
    fresh = evaluate([_row()], "v4-side50-shadow", now=NOW)
    assert fresh["windows"] == 1 and fresh["trades"] == 1
    # The family's older candidates keep the family PREREG_AT: the same
    # Nov 18 window still scores for them.
    older = evaluate([old], "v4-no-gold-shadow", now=NOW)
    assert older["windows"] == 1
