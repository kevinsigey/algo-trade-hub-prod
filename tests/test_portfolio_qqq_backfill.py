"""The QQQ snapshot backfill's price assignment: no look-ahead — a snapshot
only ever gets the close of an hourly bar that had fully closed by then."""

from types import SimpleNamespace

from tradehub.scripts.portfolio_qqq_backfill import assign_qqq_prices


def snap(at):
    return {"account_number": "PA1", "taken_at": at}


# Hourly bars: 14:00Z bar closes 300 at 15:00Z; 15:00Z bar closes 303 at 16:00Z.
BARS = [{"t": "2026-11-02T14:00:00Z", "c": 300.0},
        {"t": "2026-11-02T15:00:00Z", "c": 303.0}]


def test_snapshot_gets_the_last_fully_closed_bar():
    out = assign_qqq_prices([snap("2026-11-02T15:05:00Z")], BARS)
    assert out == {0: 300.0}  # the 15:00Z bar has not closed at 15:05


def test_snapshot_at_a_bar_close_gets_that_bar():
    out = assign_qqq_prices([snap("2026-11-02T16:00:00Z")], BARS)
    assert out == {0: 303.0}


def test_snapshot_before_any_closed_bar_stays_null():
    assert assign_qqq_prices([snap("2026-11-02T14:30:00Z")], BARS) == {}


def test_assignment_follows_taken_at_not_row_order():
    out = assign_qqq_prices([snap("2026-11-02T16:00:00Z"), snap("2026-11-02T15:05:00Z")], BARS)
    assert out == {0: 303.0, 1: 300.0}


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self._range: tuple[int, int] | None = None

    def select(self, *_a):
        return self

    def is_(self, *_a):
        return self

    def order(self, *_a):
        return self

    def range(self, lo: int, hi: int):
        self._range = (lo, hi)
        return self

    def execute(self):
        if self._range is None:
            return SimpleNamespace(data=self._rows[:1000])
        lo, hi = self._range
        return SimpleNamespace(data=self._rows[lo:hi + 1])


class _Client:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def table(self, _name: str) -> _Query:
        return _Query(self._rows)


def test_read_unfilled_pages_past_the_postgrest_cap():
    from tradehub.scripts.portfolio_qqq_backfill import read_unfilled

    rows = [{"account_number": "A", "taken_at": f"2026-11-{1 + i // 500:02d}T00:00:00+00:00"}
            for i in range(2500)]
    got = read_unfilled(_Client(rows))
    assert len(got) == 2500
