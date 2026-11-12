"""Gas fill check: marking joins the nearest sized tick, side-aware."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradehub.fifteen_fill_check import demo_size, mark_trades, summarize

CLOSE = datetime(2026, 11, 12, 17, 15, tzinfo=timezone.utc)
FROZEN = CLOSE - timedelta(minutes=10)


def decision(**over):
    row = {
        "series": "KXNATGAS15M", "target": "kalshi:T1", "action": "buy",
        "side": "yes", "cost": 0.40, "pnl": 0.55, "gate_version": "v1",
        "close_time": CLOSE.isoformat(), "frozen_at": FROZEN.isoformat(),
    }
    row.update(over)
    return row


def tick(at, yes=None, no=None, close=CLOSE):
    return {"series": "KXNATGAS15M", "close_time": close.isoformat(),
            "at": at.isoformat(), "yes_ask_size": yes, "no_ask_size": no}


def test_marks_nearest_sized_tick_for_the_side():
    ticks = [
        tick(FROZEN - timedelta(minutes=3), yes=5),     # nearer but older
        tick(FROZEN + timedelta(minutes=1), yes=0),     # nearest overall
        tick(FROZEN + timedelta(minutes=2), yes=None),  # unsized: ignored
    ]
    [m] = mark_trades([decision()], ticks)
    assert m["ask_size"] == 0
    assert m["would_fill_1"] is False
    assert m["would_fill_sized"] is False


def test_no_side_reads_no_ask_size():
    [m] = mark_trades([decision(side="no")],
                      [tick(FROZEN, yes=100, no=3)])
    assert m["ask_size"] == 3
    assert m["would_fill_1"] is True
    assert m["would_fill_sized"] is False  # demo size at 0.40 is 12


def test_no_depth_anywhere_marks_none():
    [m] = mark_trades([decision()], [tick(FROZEN, yes=None, no=None)])
    assert m["ask_size"] is None
    assert m["would_fill_1"] is None and m["would_fill_sized"] is None


def test_unsettled_and_skips_excluded():
    rows = mark_trades([decision(pnl=None), decision(action="skip"),
                        decision()], [])
    assert len(rows) == 1


def test_demo_size_matches_the_runner_rule():
    assert demo_size(0.30) == 16
    assert demo_size(0.40) == 12
    assert demo_size(0.60) == 8
    assert demo_size(0.98) == 5


def test_summarize_aggregates_and_pnl_split():
    marked = mark_trades(
        [decision(target="kalshi:A", pnl=1.0),
         decision(target="kalshi:B", pnl=-0.5),
         decision(target="kalshi:C", pnl=2.0)],
        [tick(FROZEN, yes=50),  # A and B and C share the window fixture
         ])
    # All three decisions share one close_time here, so all read size 50.
    out = summarize(marked)
    assert out["settled_gated"] == 3 and out["with_depth"] == 3
    assert out["would_fill_1"] == 3 and out["would_fill_sized"] == 3
    assert out["shadow_pnl_all"] == pytest.approx(2.5)
    assert out["shadow_pnl_fillable_sized"] == pytest.approx(2.5)
    assert out["median_ask_size"] == 50


def test_summarize_without_depth_is_none_rates():
    out = summarize(mark_trades([decision()], []))
    assert out["with_depth"] == 0 and out["without_depth"] == 1
    assert out["fill_rate_1"] is None and out["median_ask_size"] is None
