"""The ITM line freeze/grade record (Kevin, 2026-11-03): grade math, the
freeze window, once-per-event, and the public record's aggregation."""
from __future__ import annotations

from datetime import UTC, datetime

from tradehub.oil_itm import grade, in_freeze_window, record, run

NOW = datetime(2026, 11, 3, 14, 30, tzinfo=UTC)


def test_grade_math():
    assert grade(98.0, 0.58, 98.42) == (True, 0.42)
    assert grade(98.0, 0.58, 97.90) == (False, -0.58)


def test_freeze_window():
    assert in_freeze_window(25) and in_freeze_window(35) and in_freeze_window(30)
    assert not in_freeze_window(24.9) and not in_freeze_window(35.1)


class _Q:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self.filters, self.mode, self.payload = {}, "select", None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.mode, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.mode, self.payload = "update", payload
        return self

    def execute(self):
        rows = self.store.setdefault(self.name, [])
        if self.mode == "insert":
            rows.append({"id": len(rows) + 1, "settled": False, **self.payload})
            return type("R", (), {"data": [rows[-1]]})()
        if self.mode == "update":
            for r in rows:
                if all(r.get(k) == v for k, v in self.filters.items()):
                    r.update(self.payload)
            return type("R", (), {"data": []})()
        data = [r for r in rows if all(r.get(k) == v for k, v in self.filters.items())]
        return type("R", (), {"data": list(data)})()


class _Fake:
    def __init__(self):
        self.store: dict = {}

    def table(self, name):
        return _Q(self.store, name)


class _Live:
    def settled_values_recent(self, _series, _n):
        from tradehub.backtest.pit import Observation

        return [Observation("KXWTIH-26NOV0310", 98.42, NOW)]


def _ladder(minutes=30.0, itm=True):
    def fn(_now):
        view = {"state": "live", "event": "KXWTIH-26NOV0311", "minutes_to_close": minutes,
                "live_price": 98.6,
                "itm": {"strike": 98.0, "ours": 0.65, "market": 0.58} if itm else None}
        return view

    return fn


def test_run_freezes_once_inside_the_window_and_grades():
    fake = _Fake()
    out = run(fake, now=NOW, live=_Live(), ladder_fn=_ladder())
    assert out["frozen"] == "KXWTIH-26NOV0311"
    # A second run in the same window does not double-freeze.
    out = run(fake, now=NOW, live=_Live(), ladder_fn=_ladder())
    assert out["frozen"] is None and len(fake.store["oil_itm_lines"]) == 1
    # Outside the window: no freeze.
    fake2 = _Fake()
    assert run(fake2, now=NOW, live=_Live(), ladder_fn=_ladder(minutes=50))["frozen"] is None
    # The frozen row grades once its event settles (event 0310 != 0311 here,
    # so plant a settled row for the settled event and re-run).
    fake.store["oil_itm_lines"].append(
        {"id": 99, "event_ticker": "KXWTIH-26NOV0310", "strike": 98.0, "market": 0.58,
         "ours": 0.65, "settled": False, "frozen_at": NOW.isoformat()})
    out = run(fake, now=NOW, live=_Live(), ladder_fn=_ladder(itm=False))
    assert out["graded"] == 1
    row = next(r for r in fake.store["oil_itm_lines"] if r["id"] == 99)
    assert row["settled"] is True and row["hit"] is True and row["ev"] == 0.42


def test_record_aggregates():
    fake = _Fake()
    fake.store["oil_itm_lines"] = [
        {"id": 1, "event_ticker": "E1", "strike": 98.0, "ours": 0.65, "market": 0.58,
         "settled": True, "hit": True, "ev": 0.42, "frozen_at": "2026-11-03T10:30:00+00:00"},
        {"id": 2, "event_ticker": "E2", "strike": 99.0, "ours": 0.60, "market": 0.55,
         "settled": True, "hit": False, "ev": -0.55, "frozen_at": "2026-11-03T11:30:00+00:00"},
        {"id": 3, "event_ticker": "E3", "strike": 97.0, "ours": 0.70, "market": 0.62,
         "settled": False, "hit": None, "ev": None, "frozen_at": "2026-11-03T12:30:00+00:00"},
    ]
    rec = record(fake)
    assert rec["frozen"] == 3 and rec["settled"] == 2 and rec["hits"] == 1
    assert rec["hit_rate"] == 0.5 and rec["ev_per_dollar"] == -0.065
    assert rec["recent"][0]["event_ticker"] == "E1"
