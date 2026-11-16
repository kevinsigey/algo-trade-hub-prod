"""Warmer rotation + coverage (universe expansion PR 2): the yfinance
rotation is stale-first over the full listed universe, and the nightly
coverage read counts fresh entries per data kind."""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

from tradehub.screening.cache import Cache
from tradehub.scripts import screening_warm


def _store(tmp_path):
    return SimpleNamespace(cache=Cache(tmp_path / "cache"))


def _backdate(cache: Cache, key: str, hours: float) -> None:
    p = cache._path(key, "pkl")
    old = time.time() - hours * 3600
    os.utime(p, (old, old))


def test_age_hours(tmp_path):
    cache = Cache(tmp_path / "cache")
    assert cache.age_hours("info|NONE") is None
    cache.set("info|AAA", {"x": 1})
    assert cache.age_hours("info|AAA") < 0.1
    _backdate(cache, "info|AAA", 30)
    assert cache.age_hours("info|AAA") > 29


def test_rotation_order_is_stale_first(tmp_path):
    store = _store(tmp_path)
    store.cache.set("info|FRESH", {"x": 1})                    # just written
    store.cache.set("info|OLD", {"x": 1})
    _backdate(store.cache, "info|OLD", 100)                    # expired
    store.cache.set("info|OLDER", {"x": 1})
    _backdate(store.cache, "info|OLDER", 200)                  # expired, staler
    order = screening_warm.rotation_order(
        store, ["FRESH", "NEVER", "OLD", "OLDER", "ALSONEVER"])
    assert order == ["ALSONEVER", "NEVER", "OLDER", "OLD", "FRESH"]


def test_coverage_counts_fresh_entries_per_kind(tmp_path):
    store = _store(tmp_path)
    store.cache.set("info|AAA", {"x": 1})
    store.cache.set("stmt|AAA", {"income": 1})
    store.cache.set("edgarrows|AAA|NetIncomeLoss", [{"val": 1}])
    store.cache.set("info|BBB", {"x": 1})
    cov = screening_warm.coverage(store, ["AAA", "BBB", "CCC"])
    assert cov["names"] == 3
    assert cov["info"] == 2 / 3 and cov["statements"] == 1 / 3
    assert cov["edgar"] == 1 / 3
    assert screening_warm.coverage(store, []) == {
        "names": 0, "info": 0.0, "statements": 0.0, "edgar": 0.0}
