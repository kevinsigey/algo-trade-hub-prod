"""Endpoint wiring for the SWR caches: /api/oil/fifteen-rule composes its
four builds at most once per TTL per client, and /api/gaps/desk serves its
last good payload when a rebuild fails instead of 500ing the visitor."""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from tradehub.api import main
from tradehub.api.swr import SwrCache


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met within timeout")


@pytest.fixture()
def fifteen_builds(monkeypatch):
    calls = {"record": 0}

    def record(_supa):
        calls["record"] += 1
        return {"record_build": calls["record"]}

    monkeypatch.setattr("tradehub.oil_fifteen_rule.record", record)
    monkeypatch.setattr("tradehub.fifteen_shadow.summary", lambda _s: {"shadow": True})
    monkeypatch.setattr("tradehub.fifteen_blend.summary", lambda _s: {"blend": True})
    monkeypatch.setattr("tradehub.metals_fifteen_rule.record", lambda _s: {"metals": True})
    monkeypatch.setattr(main, "_FIFTEEN_RULE_CACHE", SwrCache(120))
    return calls


def test_fifteen_rule_composes_once_per_ttl(fifteen_builds):
    fake = object()
    first = main.oil_fifteen_rule(supabase=fake)
    second = main.oil_fifteen_rule(supabase=fake)
    assert first == second == {"record_build": 1, "shadow": {"shadow": True},
                               "blend": {"blend": True}, "metals": {"metals": True}}
    assert fifteen_builds["record"] == 1


def test_fifteen_rule_rebuilds_for_a_new_client(fifteen_builds):
    assert main.oil_fifteen_rule(supabase=object())["record_build"] == 1
    assert main.oil_fifteen_rule(supabase=object())["record_build"] == 2


@pytest.fixture()
def gap_desk(monkeypatch):
    clock = Clock()
    calls = {"n": 0, "fail": False}

    def desk(_supa, _now):
        calls["n"] += 1
        if calls["fail"]:
            raise RuntimeError("canceling statement due to statement timeout")
        return {"desk_build": calls["n"]}

    monkeypatch.setattr("tradehub.gaps.report.desk", desk)
    cache = SwrCache(120, clock=clock)
    monkeypatch.setattr(main, "_GAP_DESK_CACHE", cache)
    return calls, clock, cache


def test_gap_desk_serves_last_good_when_the_rebuild_fails(gap_desk):
    calls, clock, cache = gap_desk
    fake = object()
    assert main.get_gap_desk(supabase=fake) == {"desk_build": 1}
    assert main.get_gap_desk(supabase=fake) == {"desk_build": 1}
    assert calls["n"] == 1

    clock.now = 200.0
    calls["fail"] = True
    # Stale payload served; the background rebuild's failure stays invisible.
    assert main.get_gap_desk(supabase=fake) == {"desk_build": 1}
    wait_for(lambda: cache.last_error is not None)
    assert main.get_gap_desk(supabase=fake) == {"desk_build": 1}


def test_gap_desk_cold_failure_still_raises_the_table_fault(gap_desk):
    calls, _clock, _cache = gap_desk
    calls["fail"] = True
    with pytest.raises(HTTPException):
        main.get_gap_desk(supabase=object())
