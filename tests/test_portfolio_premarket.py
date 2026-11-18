"""service._fold_premarket: the per-position premarket move.

The mirror of the after-hours fold (tests/test_portfolio_after_hours.py):
the figure is the latest IEX trade against the PRIOR session's close
(latest_snapshots' prev_close). The trade must be a premarket trade --
04:00-09:30 ET -- from today. Unlike the after-hours fold there is no
one-hour freshness cut: this fold only runs while the premarket session
is live, and premarket prints are sparse, so an early print is still the
latest premarket move hours later; the frozen-print failure the
after-hours rule guards against (a finished session's last print served
as current) cannot occur inside the window that bounds this fold.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tradehub.portfolio import service

UTC = timezone.utc
NOW = datetime(2026, 11, 12, 13, 30, tzinfo=UTC)  # 08:30 ET, in the window


def _run(monkeypatch: pytest.MonkeyPatch, snap: dict, now: datetime = NOW,
         asset: str = "stock") -> dict:
    row = {"symbol": "MU", "asset": asset, "pm_change_pct": None}
    service._SNAPSHOT_CACHE.clear()  # the fold caches snapshots for ~60 s
    monkeypatch.setattr(service, "latest_snapshots", lambda symbols: {"MU": snap})
    service._fold_premarket([row], now)
    return row


def _snap(trade_at: str, price: float = 103.0, prev_close: float | None = 100.0) -> dict:
    # Before the open, dailyBar is still the prior session's bar, so "day"
    # is YESTERDAY -- the fold must key on the trade's own timestamp and
    # prev_close, never on the snapshot's day.
    return {"price": price, "trade_at": trade_at, "day_close": 100.0,
            "day": "2026-11-11", "prev_close": prev_close}


def test_premarket_trade_sets_the_move_against_the_prior_close(monkeypatch: pytest.MonkeyPatch):
    row = _run(monkeypatch, _snap("2026-11-12T13:10:00+00:00"))  # 08:10 ET today
    assert row["pm_change_pct"] == pytest.approx(3.0)


def test_early_sparse_print_still_counts_hours_later(monkeypatch: pytest.MonkeyPatch):
    # A 04:05 ET print is still the latest premarket move at 08:30 ET --
    # no after-hours-style freshness cut inside the live window.
    row = _run(monkeypatch, _snap("2026-11-12T09:05:00+00:00"))  # 04:05 ET
    assert row["pm_change_pct"] == pytest.approx(3.0)


def test_trade_before_0400_is_not_a_premarket_move(monkeypatch: pytest.MonkeyPatch):
    row = _run(monkeypatch, _snap("2026-11-12T08:30:00+00:00"))  # 03:30 ET today
    assert row["pm_change_pct"] is None


def test_yesterdays_trade_is_not_a_premarket_move(monkeypatch: pytest.MonkeyPatch):
    row = _run(monkeypatch, _snap("2026-11-11T13:10:00+00:00"))  # 08:10 ET yesterday
    assert row["pm_change_pct"] is None


def test_regular_session_trade_is_not_a_premarket_move(monkeypatch: pytest.MonkeyPatch):
    row = _run(monkeypatch, _snap("2026-11-12T15:00:00+00:00"))  # 10:00 ET today
    assert row["pm_change_pct"] is None


def test_missing_prior_close_stays_unknown(monkeypatch: pytest.MonkeyPatch):
    row = _run(monkeypatch, _snap("2026-11-12T13:10:00+00:00", prev_close=None))
    assert row["pm_change_pct"] is None


def test_missing_trade_time_stays_unknown(monkeypatch: pytest.MonkeyPatch):
    row = _run(monkeypatch, _snap(""))
    assert row["pm_change_pct"] is None


def test_options_are_not_folded(monkeypatch: pytest.MonkeyPatch):
    row = _run(monkeypatch, _snap("2026-11-12T13:10:00+00:00"), asset="option")
    assert row["pm_change_pct"] is None


def test_fold_stands_down_on_a_market_holiday(monkeypatch: pytest.MonkeyPatch):
    # Thanksgiving (Thu Nov 26, 2026) has no premarket session: even a
    # trade stamped inside the clock window today must not fold -- the
    # NYSE calendar gates the fold, not just the clock (Claude's #555
    # review).
    thanksgiving = datetime(2026, 11, 26, 13, 30, tzinfo=UTC)  # 08:30 ET
    row = _run(monkeypatch, _snap("2026-11-26T13:10:00+00:00"),
               now=thanksgiving)
    assert row["pm_change_pct"] is None


def test_fold_is_inactive_outside_the_window(monkeypatch: pytest.MonkeyPatch):
    snap = _snap("2026-11-12T13:10:00+00:00")
    # 02:00 ET: before the window (the trade stamp is also in the future).
    row = _run(monkeypatch, snap, now=datetime(2026, 11, 12, 7, 0, tzinfo=UTC))
    assert row["pm_change_pct"] is None
    # 09:30 ET sharp: the regular session has opened; the fold stands down.
    row = _run(monkeypatch, snap, now=datetime(2026, 11, 12, 14, 30, tzinfo=UTC))
    assert row["pm_change_pct"] is None
    # 15:00 ET: regular session.
    row = _run(monkeypatch, snap, now=datetime(2026, 11, 12, 20, 0, tzinfo=UTC))
    assert row["pm_change_pct"] is None
