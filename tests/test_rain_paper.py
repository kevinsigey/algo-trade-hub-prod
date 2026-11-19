"""Tests for step 19's rain paper rule. Preregistration:
docs/superpowers/specs/2026-11-19-rain-paper-rule-prereg.md.

The pins: the rule trades exactly the journal's own simulated-trade
convention, rows group into DAYS (a fat winning day cannot outvote
nineteen losing ones -- cities share weather systems), pre-prereg rows
never score, and the verdict states flip at the frozen day counts.
"""

from datetime import UTC, datetime, timedelta

from tradehub.research.rain_paper import PREREG_AT, evaluate, listings_pace

BASE = PREREG_AT + timedelta(days=1)   # 2026-11-20T06:00Z


def _row(day_offset, prob=0.80, bid=0.55, ask=0.60, outcome=1):
    frozen = BASE + timedelta(days=day_offset)
    return {"frozen_at": frozen, "probability": prob,
            "payload": {"yes_bid": bid, "yes_ask": ask}, "outcome": outcome}


def _days(n, **kw):
    return [_row(d, **kw) for d in range(n)]


def test_pre_prereg_and_unquoted_rows_never_score():
    early = _row(0)
    early["frozen_at"] = PREREG_AT - timedelta(hours=1)
    unquoted = _row(0)
    unquoted["payload"] = {}
    result = evaluate([early, unquoted, _row(0)])
    assert result["rows"] == 2 and result["unquoted"] == 1   # the early row is out entirely
    assert result["days_scored"] == 1 and result["trades"] == 1


def test_days_not_rows_carry_the_verdict():
    rows = [_row(0) for _ in range(30)]            # one fat winning day
    rows += [_row(d, outcome=0) for d in range(1, 20)]  # 19 losing days, one trade each
    result = evaluate(rows)
    assert result["days_scored"] == 20
    assert result["mean_day_net_cents"] < 0        # the day-mean is negative
    assert result["state"] == "accruing"           # not proven despite 30 winning rows


def test_verdict_states_at_the_frozen_day_counts():
    assert evaluate(_days(19))["state"] == "accruing"
    assert evaluate(_days(20))["state"] == "proven"
    losers = _days(40, outcome=0)
    assert evaluate(losers)["state"] == "failed"
    assert evaluate(_days(39, outcome=0))["state"] == "accruing"


def test_listings_pace_counts_rows_per_et_day():
    rows = [{"frozen_at": BASE}, {"frozen_at": BASE},
            {"frozen_at": BASE + timedelta(days=1)}]
    pace = listings_pace(rows, days=14, now=BASE + timedelta(days=1, hours=1))
    assert pace["days_observed"] == 2 and pace["mean_per_day"] == 1.5
