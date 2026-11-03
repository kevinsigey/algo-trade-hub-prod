"""Screener speed (Kevin, 2026-11-03): a run used to fetch per-ticker data
one name at a time from rate-limited free sources, synchronously inside the
request -- a cold 300-name run took minutes. Runs now prefetch exactly the
per-ticker kinds the spec uses, concurrently, so the field functions read
the local cache; the footer states the age of the data the run used.
"""

from __future__ import annotations

import time

from tradehub.screening import runner
from tradehub.screening.sources import DataStore


def test_needed_kinds_maps_only_per_ticker_sources():
    spec = {
        "name": "x", "universe": {"type": "list", "tickers": ["AAA"]},
        "filters": [
            {"fn": "pe_ratio", "op": "lt", "value": 30},            # yfinance.info
            {"fn": "days_to_earnings", "op": "lt", "value": 30},    # yfinance earnings dates
            {"fn": "return_pct", "params": {"days": 30}, "op": "gt", "value": 0},  # bulk prices
        ],
        "score": [{"fn": "implied_move_pct", "weight": 1}],          # yfinance options
    }
    assert runner.needed_kinds(spec) == {"info", "earnings", "options"}


def test_needed_kinds_empty_when_spec_needs_no_per_ticker_data():
    spec = {"name": "x", "universe": {"type": "list", "tickers": ["AAA"]},
            "filters": [{"fn": "return_pct", "params": {"days": 30}, "op": "gt", "value": 0}]}
    assert runner.needed_kinds(spec) == set()


class _SlowStore(DataStore):
    """DataStore whose info() is a 50ms network call, counted."""

    def __init__(self, root):
        super().__init__(root)
        self.info_calls = 0

    def info(self, ticker):  # noqa: D102 - test double
        self.info_calls += 1
        time.sleep(0.05)
        return {"trailingPE": 12.0}


def test_warm_fetches_each_ticker_once_concurrently(tmp_path):
    store = _SlowStore(tmp_path)
    tickers = [f"T{i:02d}" for i in range(40)]
    t0 = time.time()
    store.warm(tickers, {"info"})
    elapsed = time.time() - t0
    assert store.info_calls == 40
    # Sequential floor is 40 x 50ms = 2.0s; the pool must beat it clearly.
    assert elapsed < 1.2, f"warm took {elapsed:.2f}s -- not concurrent"


def test_warm_with_no_kinds_fetches_nothing(tmp_path):
    store = _SlowStore(tmp_path)
    store.warm(["AAA", "BBB"], set())
    assert store.info_calls == 0


class _FakeStore:
    """The surface run_spec touches, with an event log."""

    def __init__(self):
        self.asof: dict[str, str] = {}
        self.missing: list[dict] = []
        self.events: list = []

    def note_missing(self, ticker, field, reason):
        self.missing.append({"ticker": ticker, "field": field, "reason": str(reason)})

    def warm(self, tickers, kinds):
        self.events.append(("warm", list(tickers), set(kinds)))

    def info(self, ticker):
        self.events.append(("info", ticker))
        self.asof.setdefault("info", "2026-11-03T10:00:00+00:00")
        return {"trailingPE": 9.0}


def test_run_spec_warms_before_computing_and_stamps_data_age():
    store = _FakeStore()
    spec = {"name": "demo", "universe": {"type": "list", "tickers": ["AAA", "BBB"]},
            "filters": [{"fn": "pe_ratio", "op": "lt", "value": 30}]}
    result = runner.run_spec(spec, store=store)
    assert store.events[0] == ("warm", ["AAA", "BBB"], {"info"})
    assert result.footer["data_as_of"] == "2026-11-03T10:00:00+00:00"
    assert len(result.table) == 2
