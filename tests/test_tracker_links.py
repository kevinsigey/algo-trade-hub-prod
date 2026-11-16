"""Tracker PR 5b — trade_links: the placement write, the reference
resolution, the Claim C fire walk, and the FIFO join it all reads.

The fire walk's queue rule is the point: the frozen Claim C window is
the NEXT five play-kind-(a) fires, so nets arrive in placement order,
a fire counts only once fully closed, and the walk stops at the first
incomplete fire instead of letting a later one jump it.
"""
from datetime import datetime, timedelta, timezone

from tests.test_valuation_verdicts import FakeClient
from tradehub.portfolio import book as book_mod
from tradehub.tracker import links

NOW = datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc)


def _client() -> FakeClient:
    c = FakeClient()
    c.tables["theses"] = [{"id": 1, "slug": "event-lab"},
                          {"id": 2, "slug": "core"}]
    c.tables["forecast_cards"] = [{"id": 7, "thesis_id": 1, "ticker": "NVDA"}]
    return c


def _link(c, cid, *, kind="a", book="main", days_ago=10, shadow=False):
    row = links.record_link(
        c, client_order_id=cid, book=book, play_kind=kind,
        modal_value=1.5, opposing_case_ref="research/x.md#opposing-case",
        shadow=shadow)
    stored = next(r for r in c.tables["trade_links"]
                  if r["client_order_id"] == cid)
    stored["created_at"] = (NOW - timedelta(days=days_ago)).isoformat()
    return stored


def _state(**books):
    return {name: {"closed": view.get("closed", []),
                   "open_client_ids": view.get("open", set()),
                   "open_order_ids": view.get("open_order_ids", set())}
            for name, view in books.items()}


def _trade(cid, pnl):
    return {"client_order_id": cid, "pnl": pnl}


# -- the write ---------------------------------------------------------------

def test_record_link_is_idempotent_on_the_client_order_id():
    c = _client()
    first = _link(c, "ext-1-a")
    again = links.record_link(
        c, client_order_id="ext-1-a", book="main", play_kind="a",
        modal_value=9.9, opposing_case_ref="other")
    assert again["id"] == first["id"]
    assert len(c.tables["trade_links"]) == 1
    assert c.tables["trade_links"][0]["modal_value"] == 1.5


def test_record_link_conflicting_terms_raise():
    import pytest

    c = _client()
    _link(c, "ext-1-a", shadow=True)
    # The same caller id reused for a LIVE order is a conflict, not a
    # retry: returning the shadow row would hide the live entry from
    # Claim C and the play-kind P&L.
    with pytest.raises(ValueError, match="different link terms"):
        links.record_link(
            c, client_order_id="ext-1-a", book="main", play_kind="a",
            modal_value=1.5, opposing_case_ref="research/x.md#opposing-case",
            shadow=False)
    with pytest.raises(ValueError, match="different link terms"):
        links.record_link(
            c, client_order_id="ext-1-a", book="main", play_kind="b",
            modal_value=1.5, opposing_case_ref="research/x.md#opposing-case",
            shadow=True)


class _RaceTable:
    """A table whose insert loses a race: the row appears (written by
    the 'concurrent' call) while this insert raises the unique
    violation."""

    def __init__(self, client):
        self._client = client
        self._filters = {}

    def select(self, *_a):
        return self

    def eq(self, key, value):
        self._filters[key] = value
        return self

    def insert(self, row):
        self._client.tables["trade_links"] = [dict(row, id=99)]
        raise RuntimeError("duplicate key value violates unique constraint")

    def execute(self):
        rows = [r for r in self._client.tables.get("trade_links", [])
                if all(r.get(k) == v for k, v in self._filters.items())]
        return type("R", (), {"data": rows})()


def test_record_link_recovers_a_concurrent_insert():
    c = _client()
    c.tables["trade_links"] = []
    real_table = c.table
    c.table = lambda name: _RaceTable(c) if name == "trade_links" \
        else real_table(name)
    row = links.record_link(
        c, client_order_id="ext-1-race", book="main", play_kind="a",
        modal_value=1.5, opposing_case_ref="research/x.md#opposing-case")
    assert row["id"] == 99


def test_resolve_thesis_from_card_and_errors():
    c = _client()
    assert links.resolve_thesis(c, forecast_id=7) == (1, None)
    assert links.resolve_thesis(c, thesis_id=2) == (2, None)
    assert links.resolve_thesis(c) == (None, None)
    _, err = links.resolve_thesis(c, forecast_id=99)
    assert "no forecast card" in err
    _, err = links.resolve_thesis(c, thesis_id=99)
    assert "no thesis" in err


# -- the Claim C fire walk ----------------------------------------------------

def test_fire_nets_sum_a_fires_trades_in_order():
    c = _client()
    _link(c, "ext-1-a", days_ago=10)
    _link(c, "ext-1-b", days_ago=9)
    state = _state(main={"closed": [_trade("ext-1-a", 100.0),
                                    _trade("ext-1-a", -40.0),
                                    _trade("ext-1-b", 250.0)]})
    assert links.claim_c_fire_nets(c, state, now=NOW) == [60.0, 250.0]


def test_an_open_fire_stops_the_walk():
    c = _client()
    _link(c, "ext-1-a", days_ago=10)
    _link(c, "ext-1-b", days_ago=9)
    state = _state(main={"closed": [_trade("ext-1-b", 250.0)],
                         "open": {"ext-1-a"}})
    assert links.claim_c_fire_nets(c, state, now=NOW) == []


def test_a_young_positionless_link_stops_an_old_one_is_skipped():
    c = _client()
    _link(c, "ext-1-a", days_ago=2)          # placed, maybe unfilled yet
    _link(c, "ext-1-b", days_ago=1)
    state = _state(main={"closed": [_trade("ext-1-b", 10.0)]})
    assert links.claim_c_fire_nets(c, state, now=NOW) == []

    c2 = _client()
    _link(c2, "ext-1-a", days_ago=30)        # never filled: no position
    _link(c2, "ext-1-b", days_ago=29)
    assert links.claim_c_fire_nets(c2, state, now=NOW) == [10.0]


def test_shadow_and_other_kinds_are_not_fires_and_unreadable_books_stop():
    c = _client()
    _link(c, "ext-1-a", days_ago=10, shadow=True)
    _link(c, "ext-1-b", days_ago=9, kind="b")
    _link(c, "ext-1-c", days_ago=8)
    state = _state(main={"closed": [_trade("ext-1-a", 1.0),
                                    _trade("ext-1-b", 2.0),
                                    _trade("ext-1-c", 3.0)]})
    assert links.claim_c_fire_nets(c, state, now=NOW) == [3.0]

    c2 = _client()
    _link(c2, "ext-2-a", book="big", days_ago=10)
    _link(c2, "ext-1-d", days_ago=9)
    state2 = _state(main={"closed": [_trade("ext-1-d", 5.0)]})
    # The unreadable 'big' book stops the walk BEFORE the readable
    # fire behind it — without the stop, the positionless big link is
    # old enough to skip as never-filled and the walk returns [5.0].
    assert links.claim_c_fire_nets(c2, state2, now=NOW) == []


def test_fire_net_waits_for_a_terminal_entry_order():
    c = _client()
    _link(c, "ext-1-a", days_ago=10)
    _link(c, "ext-1-b", days_ago=9)
    state = _state(main={"closed": [_trade("ext-1-a", 7.0),
                                     _trade("ext-1-b", 5.0)],
                          "open_order_ids": {"ext-1-a"}})
    # ext-1-a's filled part is closed, but its entry order is partly
    # filled and can still take fills: its net is not final, and the
    # fire behind it may not jump it.
    assert links.claim_c_fire_nets(c, state, now=NOW) == []


def test_pnl_by_play_kind_never_blends():
    c = _client()
    _link(c, "ext-1-a", kind="a")
    _link(c, "ext-1-b", kind="b")
    _link(c, "ext-1-c", kind="c", shadow=True)
    state = _state(main={"closed": [_trade("ext-1-a", 100.0),
                                    _trade("ext-1-b", -30.0),
                                    _trade("ext-1-c", 999.0)]})
    out = links.pnl_by_play_kind(c, state)
    assert out == {"a": {"links": 1, "trades": 1, "pnl": 100.0},
                   "b": {"links": 1, "trades": 1, "pnl": -30.0}}


# -- the FIFO join (book.py) ---------------------------------------------------

def _fill(order, symbol, side, qty, price, at, cid):
    return {"order_id": order, "symbol": symbol, "side": side,
            "qty": qty, "price": price, "transaction_time": at,
            "client_order_id": cid}


def test_fifo_carries_the_opening_client_id_and_option_multiplier():
    fills = [
        # an option round trip: 2 contracts in at 2.94, out at 0.21
        _fill("o1", "CRWV261113P00045000", "buy", 2, 2.94,
              "2026-11-10T14:00:00Z", "ext-1-fire1"),
        _fill("o2", "CRWV261113P00045000", "sell", 2, 0.21,
              "2026-11-12T14:00:00Z", "ext-1-close1"),
        # a share position still open
        _fill("o3", "NVDA", "buy", 10, 100.0,
              "2026-11-12T15:00:00Z", "ext-1-open1"),
    ]
    trades = book_mod.closed_trades(fills)
    assert len(trades) == 1
    assert trades[0]["client_order_id"] == "ext-1-fire1"
    assert trades[0]["pnl"] == -546.0  # (0.21 - 2.94) x 2 x 100
    assert book_mod.open_client_ids(fills) == {"ext-1-open1"}


def test_tag_fills_stamps_the_client_order_id():
    raw = [{"order_id": "o1", "symbol": "NVDA", "side": "buy", "qty": 1,
            "price": 100.0, "transaction_time": "2026-11-12T15:00:00Z"}]
    tagged = book_mod.tag_fills(raw, {"o1": "ext-9-x"}, {}, {})
    assert tagged[0]["client_order_id"] == "ext-9-x"
