"""The stale-while-revalidate cache behind the slow read-only endpoints
(/api/oil/fifteen-rule, /api/gaps/desk): visitors never wait for a rebuild
once any payload exists, cold bursts share one build, and a failed rebuild
keeps serving the last good payload."""

from __future__ import annotations

import threading
import time

import pytest

from tradehub.api.swr import SwrCache

CLIENT = object()  # the one production client, for tests that exercise caching


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


def test_fresh_hit_never_rebuilds():
    clock = Clock()
    cache = SwrCache(120, clock=clock)
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        return {"v": calls["n"]}

    assert cache.get(build, client=CLIENT) == {"v": 1}
    clock.now = 119.0
    assert cache.get(build, client=CLIENT) == {"v": 1}
    assert calls["n"] == 1


def test_stale_hit_serves_stale_and_rebuilds_once_in_background():
    clock = Clock()
    cache = SwrCache(120, clock=clock)
    calls = {"n": 0}
    release = threading.Event()

    def build():
        calls["n"] += 1
        if calls["n"] > 1:
            release.wait(5)
        return {"v": calls["n"]}

    assert cache.get(build, client=CLIENT) == {"v": 1}
    clock.now = 121.0
    # The rebuild is blocked, yet both stale hits answer immediately.
    assert cache.get(build, client=CLIENT) == {"v": 1}
    assert cache.get(build, client=CLIENT) == {"v": 1}
    release.set()
    wait_for(lambda: calls["n"] == 2 and cache.get(build, client=CLIENT) == {"v": 2})
    assert calls["n"] == 2  # exactly one background rebuild for both hits


def test_cold_burst_shares_one_build():
    cache = SwrCache(120)
    calls = {"n": 0}
    started = threading.Event()
    release = threading.Event()

    def build():
        calls["n"] += 1
        started.set()
        release.wait(5)
        return {"v": 1}

    results: list[dict] = []
    threads = [threading.Thread(target=lambda: results.append(cache.get(build, client=CLIENT)))
               for _ in range(3)]
    for t in threads:
        t.start()
    assert started.wait(5)
    release.set()
    for t in threads:
        t.join(5)
    assert calls["n"] == 1
    assert results == [{"v": 1}] * 3


def test_cold_failure_propagates_and_next_call_retries():
    cache = SwrCache(120)
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("statement timeout")
        return {"v": 2}

    with pytest.raises(RuntimeError):
        cache.get(build, client=CLIENT)
    assert cache.get(build, client=CLIENT) == {"v": 2}


def test_failed_rebuild_keeps_serving_last_good_and_backs_off():
    clock = Clock()
    cache = SwrCache(120, retry_seconds=30, clock=clock)
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("statement timeout")
        return {"v": 1}

    assert cache.get(build, client=CLIENT) == {"v": 1}
    clock.now = 200.0
    assert cache.get(build, client=CLIENT) == {"v": 1}  # stale served, rebuild starts
    wait_for(lambda: cache.last_error is not None)
    assert cache.get(build, client=CLIENT) == {"v": 1}  # still the last good payload
    assert calls["n"] == 2  # no retry storm inside the backoff window
    clock.now = 231.0
    assert cache.get(build, client=CLIENT) == {"v": 1}
    wait_for(lambda: calls["n"] == 3)  # retries resume after the backoff


def test_no_client_means_no_caching():
    cache = SwrCache(120)
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        return {"v": calls["n"]}

    assert cache.get(build) == {"v": 1}
    assert cache.get(build) == {"v": 2}


def test_a_different_client_never_sees_the_cached_payload():
    clock = Clock()
    cache = SwrCache(120, clock=clock)
    a, b = object(), object()
    assert cache.get(lambda: {"who": "a"}, client=a) == {"who": "a"}
    assert cache.get(lambda: {"who": "b"}, client=b) == {"who": "b"}
    assert cache.get(lambda: {"who": "b2"}, client=b) == {"who": "b"}
