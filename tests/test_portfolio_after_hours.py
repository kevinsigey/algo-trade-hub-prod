"""service._fold_after_hours: the per-position after-hours move.

The figure is the latest IEX trade against today's regular close. The
trade must be an after-hours trade (at/after 16:00 ET) from today and
recent -- the IEX post-market session ends at 17:00 ET, after which the
latest trade freezes; a frozen print is not a current move.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tradehub.portfolio import service

UTC = timezone.utc
NOW = datetime(2026, 11, 12, 22, 30, tzinfo=UTC)  # 17:30 ET


def _run(monkeypatch: pytest.MonkeyPatch, snap: dict) -> dict:
    row = {"symbol": "MU", "asset": "stock", "ah_change_pct": None}
    monkeypatch.setattr(service, "latest_snapshots", lambda symbols: {"MU": snap})
    service._fold_after_hours([row], NOW)
    return row


def _snap(trade_at: str, price: float = 101.0) -> dict:
    return {"price": price, "trade_at": trade_at,
            "day_close": 100.0, "day": "2026-11-12"}


def test_recent_after_hours_trade_sets_the_move(monkeypatch: pytest.MonkeyPatch):
    row = _run(monkeypatch, _snap("2026-11-12T22:10:00+00:00"))  # 17:10 ET
    assert row["ah_change_pct"] == pytest.approx(1.0)


def test_regular_session_trade_is_not_an_after_hours_move(monkeypatch: pytest.MonkeyPatch):
    row = _run(monkeypatch, _snap("2026-11-12T20:30:00+00:00"))  # 15:30 ET
    assert row["ah_change_pct"] is None


def test_frozen_print_over_an_hour_old_stays_unknown(monkeypatch: pytest.MonkeyPatch):
    row = _run(monkeypatch, _snap("2026-11-12T21:05:00+00:00"))  # 16:05 ET, 85 min old
    assert row["ah_change_pct"] is None


def test_missing_trade_time_stays_unknown(monkeypatch: pytest.MonkeyPatch):
    row = _run(monkeypatch, _snap(""))
    assert row["ah_change_pct"] is None
