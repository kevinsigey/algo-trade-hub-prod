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


class _MainQuery:
    """The backfill main()'s read + write surface over a fixed row set."""

    def __init__(self, client):
        self._client = client
        self._range = None

    def select(self, *_a):
        return self

    def is_(self, *_a):
        return self

    def order(self, *_a):
        return self

    def range(self, lo, hi):
        self._range = (lo, hi)
        return self

    def update(self, row):
        self._client.pending_update = row
        return self

    def eq(self, key, value):
        self._client.update_filters[key] = value
        return self

    def execute(self):
        client = self._client
        if client.pending_update is not None:
            client.updates.append((dict(client.update_filters), client.pending_update))
            client.pending_update = None
            client.update_filters = {}
            return SimpleNamespace(data=[])
        if self._range is None:
            return SimpleNamespace(data=client.rows[:1000])
        lo, hi = self._range
        return SimpleNamespace(data=client.rows[lo:hi + 1])


class _MainClient:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []
        self.pending_update = None
        self.update_filters = {}

    def table(self, _name):
        return _MainQuery(self)


def test_backfill_reaches_fridays_bar_for_a_monday_snapshot(monkeypatch):
    # CodeRabbit, PR #514: a Monday 09:05 ET snapshot's last fully
    # closed bar is Friday's. The fetch window must reach back across
    # the weekend, or the row stays NULL on every re-run.
    from tradehub.scripts import portfolio_qqq_backfill as backfill

    friday_bars = [{"t": "2026-11-06T19:00:00Z", "c": 310.0},
                   {"t": "2026-11-06T20:00:00Z", "c": 312.0}]

    def fake_bars(symbol, timeframe, start, end):
        # The real API returns only bars inside [start, end].
        return [b for b in friday_bars if start <= b["t"] <= end]

    monkeypatch.setattr(backfill, "stock_bars", fake_bars)
    client = _MainClient([{"account_number": "PA1",
                            "taken_at": "2026-11-09T14:05:00+00:00"}])
    assert backfill.main(client) == 0
    assert client.updates == [({"account_number": "PA1",
                                "taken_at": "2026-11-09T14:05:00+00:00"},
                               {"qqq_price": 312.0})]
