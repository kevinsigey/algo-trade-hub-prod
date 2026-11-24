"""oil-trend-agree-v1 (docs/superpowers/specs/2026-11-24-oil-trend-agree-v1-prereg.md):
the filter keeps only raw-rule decisions that agree with m15, it never
registers for gas or metals, and the grade pairs against the unfiltered rule."""

from datetime import UTC, datetime

from tradehub import fifteen_candidates as fc

PREREG = datetime(2026, 11, 25, tzinfo=UTC)
NOW = datetime(2026, 12, 1, tzinfo=UTC)


def test_filter_keeps_agreeing_and_drops_the_rest():
    assert fc.trend_skip_reason("yes", 101.0, 100.0) is None
    assert fc.trend_skip_reason("no", 99.0, 100.0) is None
    assert fc.trend_skip_reason("yes", 99.0, 100.0) == "disagrees"
    assert fc.trend_skip_reason("no", 101.0, 100.0) == "disagrees"
    assert fc.trend_skip_reason("yes", 100.0, 100.0) == "flat_m15"
    assert fc.trend_skip_reason("no", None, 100.0) == "no_m15"
    assert fc.trend_skip_reason("yes", 100.0, None) == "no_m15"


def test_fee_rounds_up_per_order():
    assert fc.fee_ceil(0.50) == 0.02   # 1.75c -> 2c
    assert fc.fee_ceil(0.10) == 0.01   # 0.63c -> 1c


def _fc(target, frozen_at, price, p=0.70, ask=0.50, bid=0.48):
    return {"target": target, "frozen_at": frozen_at, "probability": p,
            "payload": {"yes_ask": ask, "yes_bid": bid, "price": price}}


# 15:05Z = 10:05 ET, outside the halt; windows open 14:45 / 15:00 / 15:15 / 15:30.
ROWS = [
    _fc("prev", "2026-11-25T14:50:00+00:00", 70.0, p=0.5),          # no raw pick; supplies P_prev
    _fc("up", "2026-11-25T15:05:00+00:00", 70.5),                     # YES, m15 > 0: kept
    _fc("up", "2026-11-25T15:06:00+00:00", 60.0),                     # a later freeze is ignored
    _fc("down", "2026-11-25T15:20:00+00:00", 70.0),                   # YES, m15 < 0: dropped
    _fc("gap", "2026-11-25T15:50:00+00:00", 70.0),                    # no previous window: dropped
]
SETTLED = {"up": 1, "down": 0, "gap": 1}


def test_decisions_from_first_freezes():
    ds = {d["target"]: d for d in fc.trend_decisions(ROWS, SETTLED, fc.WTI, PREREG)}
    assert set(ds) == {"up", "down", "gap"}
    assert ds["up"]["action"] == "buy" and ds["up"]["p_now"] == 70.5
    assert ds["up"]["pnl"] == round(1 - 0.50 - 0.02, 4)
    assert ds["down"]["reason"] == "disagrees"
    assert ds["gap"]["reason"] == "no_m15"


def test_never_registers_for_gas_or_metals():
    assert set(fc.TREND_SERIES) == {fc.WTI, fc.BRENT}
    for series in (fc.NATGAS, fc.GOLD, fc.SILVER, fc.COPPER):
        assert fc.trend_decisions(ROWS, SETTLED, series, PREREG) == []
    assert fc.TREND_VERSION not in fc.CANDIDATES  # the demo lane reads CANDIDATES


def test_nothing_before_prereg():
    later = datetime(2026, 11, 26, tzinfo=UTC)
    assert fc.trend_decisions(ROWS, SETTLED, fc.WTI, later) == []


def test_grade_pairs_against_the_unfiltered_rule():
    def d(day, action, pnl):
        return {"close_time": f"2026-11-{day}T15:15:00+00:00", "action": action,
                "reason": None if action == "buy" else "disagrees", "pnl": pnl}
    # Kept trades earn; dropped ones lose -> filtered beats unfiltered.
    decisions = []
    for day in range(25, 30):
        decisions += [d(day, "buy", 0.30), d(day, "buy", 0.20), d(day, "skip", -0.50)]
    r = fc.trend_evaluate(decisions, now=NOW)
    assert r["trades"] == 10 and r["paired_windows"] == 15
    assert r["paired_low95"] > 0 and r["baseline"] == "the unfiltered raw oil rule"
    assert not r["eligible"]  # under 150 trades
    assert r["skips"] == {"disagrees": 5}
    # A dropped winner makes the paired gain negative.
    worse = [d(day, a, p) for day in range(25, 30)
             for a, p in (("buy", 0.10), ("skip", 0.50), ("skip", 0.40))]
    assert fc.trend_evaluate(worse, now=NOW)["paired_low95"] < 0


def test_eligible_only_with_150_trades_and_both_legs():
    decisions = [{"close_time": f"2026-11-{25 + i % 5}T15:15:00+00:00", "action": "buy",
                  "reason": None, "pnl": 0.10 + 0.01 * (i % 3)} for i in range(150)]
    decisions += [{"close_time": f"2026-11-{25 + i % 5}T16:15:00+00:00", "action": "skip",
                   "reason": "disagrees", "pnl": -0.2 - 0.01 * (i % 3)} for i in range(20)]
    assert fc.trend_evaluate(decisions, now=NOW)["eligible"]
    assert not fc.trend_evaluate(decisions[1:], now=NOW)["eligible"]
