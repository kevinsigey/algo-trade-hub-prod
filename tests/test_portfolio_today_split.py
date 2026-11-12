"""book.today_split: the Portfolio header's Today, split at the 4 PM ET close.

Snapshots are stored hourly, so the "4:00 PM snapshot" is the first stored
snapshot at or after 16:00 ET on the day. The regular-session figure is
that snapshot minus the prior ET day's last snapshot; the after-hours
figure is the live equity minus that snapshot. Before any post-close
snapshot exists, the whole day is the regular figure.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tradehub.portfolio import book

UTC = timezone.utc


def snap(at: str, equity: float, spy: float) -> dict:
    return {"taken_at": at, "equity": equity, "spy_price": spy}


# Nov 11 2026 (ET = UTC-5): last snapshot 16:30 ET at equity 1000 / SPY 600.
PRIOR = [
    snap("2026-11-11T20:00:00+00:00", 900.0, 590.0),   # 15:00 ET
    snap("2026-11-11T21:30:00+00:00", 1000.0, 600.0),  # 16:30 ET -- the prior close
]


def test_regular_hours_whole_day_is_the_regular_figure():
    now = datetime(2026, 11, 12, 20, 30, tzinfo=UTC)  # 15:30 ET
    snaps = PRIOR + [snap("2026-11-12T15:00:00+00:00", 1010.0, 603.0)]  # 10:00 ET
    out = book.today_split(snaps, now, equity=1005.0, spy_price=606.0)
    assert out["state"] == "regular"
    assert out["prior_close_at"] == "2026-11-11T21:30:00+00:00"
    assert out["close_at"] is None
    assert out["regular_pl"] == 5.0
    assert out["regular_pct"] == pytest.approx(0.5)
    assert out["after_hours_pl"] is None
    assert out["spy_regular_pct"] == pytest.approx(1.0)
    assert out["spy_after_hours_pct"] is None


def test_after_hours_splits_at_the_first_post_close_snapshot():
    now = datetime(2026, 11, 12, 23, 30, tzinfo=UTC)  # 18:30 ET
    snaps = PRIOR + [
        snap("2026-11-12T20:00:00+00:00", 1020.0, 610.0),  # 15:00 ET, pre-close
        snap("2026-11-12T21:05:00+00:00", 990.0, 594.0),   # 16:05 ET -- the close
        snap("2026-11-12T22:05:00+00:00", 988.0, 593.0),   # later snaps don't move it
    ]
    out = book.today_split(snaps, now, equity=985.0, spy_price=591.0)
    assert out["state"] == "after_hours"
    assert out["close_at"] == "2026-11-12T21:05:00+00:00"
    assert out["regular_pl"] == -10.0
    assert out["regular_pct"] == pytest.approx(-1.0)
    assert out["after_hours_pl"] == -5.0
    assert round(out["after_hours_pct"], 3) == round(-5.0 / 990.0 * 100, 3)
    assert out["spy_regular_pct"] == pytest.approx(-1.0)
    assert round(out["spy_after_hours_pct"], 3) == round((591.0 / 594.0 - 1) * 100, 3)


def test_snapshot_exactly_at_1600_et_is_the_close():
    now = datetime(2026, 11, 12, 22, 0, tzinfo=UTC)  # 17:00 ET
    snaps = PRIOR + [snap("2026-11-12T21:00:00+00:00", 1002.0, 601.0)]  # 16:00 ET sharp
    out = book.today_split(snaps, now, equity=1002.0, spy_price=601.0)
    assert out["state"] == "after_hours"
    assert out["regular_pl"] == 2.0
    assert out["after_hours_pl"] == 0.0


def test_first_day_has_no_split():
    now = datetime(2026, 11, 12, 20, 30, tzinfo=UTC)
    snaps = [snap("2026-11-12T15:00:00+00:00", 1010.0, 603.0)]
    out = book.today_split(snaps, now, equity=1010.0, spy_price=603.0)
    assert out["state"] == "no_prior"
    assert out["regular_pl"] is None
    assert out["after_hours_pl"] is None
    assert out["spy_regular_pct"] is None


def test_missing_live_prices_fall_back_to_the_last_snapshot():
    now = datetime(2026, 11, 12, 20, 30, tzinfo=UTC)  # 15:30 ET
    snaps = PRIOR + [snap("2026-11-12T15:00:00+00:00", 1010.0, 603.0)]
    out = book.today_split(snaps, now, equity=None, spy_price=None)
    # Current reads as the newest stored snapshot, so the split still lands.
    assert out["regular_pl"] == 10.0
    assert out["spy_regular_pct"] == pytest.approx(0.5)
