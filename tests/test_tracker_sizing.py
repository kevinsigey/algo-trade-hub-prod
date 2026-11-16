"""Tracker PR 5a — the sizing fork (v6 spec Section 4).

Schedule v2 ($5,000 base / $10,000 top-tier) applies only while the
grader's last successful run is fresh (< 26h); anything else — a stale
stamp, a failed run, no stamp at all — reads the $1,500 fallback.
The fork is automatic: no vote, no grace period.
"""
from datetime import datetime, timedelta, timezone

from tests.test_valuation_verdicts import FakeClient
from tradehub.tracker import sizing

NOW = datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc)


def _client(config=None, health=None) -> FakeClient:
    c = FakeClient()
    if config is not None:
        c.tables["tracker_config"] = [dict(config, id=1)]
    if health is not None:
        c.tables["tracker_health"] = [dict(health, id=1)]
    return c


def _health(hours_ago: float, ok: bool = True) -> dict:
    return {"last_grader_run_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "last_grader_ok": ok}


def test_missing_rows_read_as_defaults_and_fallback():
    c = _client()
    assert sizing.load_config(c) == sizing.DEFAULTS
    assert sizing.grader_fresh(c, now=NOW) is False
    unit = sizing.governing_unit(c, now=NOW)
    assert unit == {"unit": 1500.0, "source": "fallback", "fresh": False}


def test_fresh_grader_unlocks_schedule_v2():
    c = _client(health=_health(1.5))
    assert sizing.grader_fresh(c, now=NOW) is True
    assert sizing.governing_unit(c, now=NOW)["unit"] == 5000.0
    top = sizing.governing_unit(c, top_tier=True, now=NOW)
    assert top == {"unit": 10000.0, "source": "schedule_v2", "fresh": True}


def test_stale_failed_and_future_stamps_all_fall_back():
    assert sizing.grader_fresh(_client(health=_health(26.5)), now=NOW) is False
    assert sizing.grader_fresh(_client(health=_health(0.5, ok=False)),
                               now=NOW) is False
    future = {"last_grader_run_at": (NOW + timedelta(hours=1)).isoformat(),
              "last_grader_ok": True}
    assert sizing.grader_fresh(_client(health=future), now=NOW) is False
    assert sizing.governing_unit(_client(health=_health(30)),
                                 now=NOW)["unit"] == 1500.0


def test_config_row_overrides_the_defaults():
    c = _client(config={"unit_v2_premium": 4000, "unit_v2_top": 8000,
                        "unit_fallback": 1200, "play_kind_c_live": True,
                        "cash_floor_pct": 12},
                health=_health(2))
    assert sizing.load_config(c)["play_kind_c_live"] is True
    assert sizing.governing_unit(c, now=NOW)["unit"] == 4000.0
    assert sizing.governing_unit(c, top_tier=True, now=NOW)["unit"] == 8000.0
