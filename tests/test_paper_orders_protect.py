from datetime import datetime

import pytest
from test_paper_orders_run import SPEC, Alpaca, live_idea
from workshop_fake import DB

from tradehub.portfolio import paper_orders, service
from tradehub.scripts import paper_orders_protect
from tradehub.workshop import store

AFTER_OPEN = datetime.fromisoformat("2026-11-03T14:45:00+00:00")  # Tue 09:45 New York
INTRADAY = {**SPEC, "exits": {"stop_loss_pct": 5, "mode": "intraday"}}
FILLS = [{"id": "f1", "order_id": "a", "symbol": "GLD", "side": "buy", "qty": "66", "price": "300",
          "transaction_time": "2026-11-03T14:30:00Z"}]
ORDERS = [{"id": "a", "client_order_id": "idea-1-auto-20261103-GLD-open", "submitted_at": "t1"}]


class Broker(Alpaca):
    def __init__(self, pending=(), **kw):
        super().__init__(fills=FILLS, orders=ORDERS, **kw)
        self.open_orders = list(pending)

    def __call__(self, path, params=None):
        if path == "/v2/orders" and (params or {}).get("status") == "open":
            return self.open_orders
        return super().__call__(path, params)


class Calls:
    def __init__(self, fail=None):
        self.log, self.fail = [], fail

    def submit(self, symbol, qty, side, client_order_id, **kw):
        if self.fail:
            raise self.fail
        self.log.append(("submit", symbol, side, qty, client_order_id, kw))
        return {"id": f"s-{len(self.log)}"}

    def cancel(self, order_id, client_order_id):
        if self.fail:
            raise self.fail
        self.log.append(("cancel", order_id, client_order_id))


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    d = DB()
    store.create_idea(d, "Hold GLD", "w")
    live_idea(d, 1, spec=INTRADAY)
    return d


def protect(db, broker, calls, monkeypatch):
    monkeypatch.setattr(service, "paper_get", broker)
    return paper_orders_protect.run(AFTER_OPEN, db, submit=calls.submit, cancel=calls.cancel)


def test_places_a_stop_under_a_fresh_fill(db, monkeypatch):
    calls = Calls()
    summary, failed = protect(db, Broker(), calls, monkeypatch)
    assert failed == {} and len(calls.log) == 1
    kind, symbol, side, qty, cid, kw = calls.log[0]
    assert (symbol, side, qty, cid) == ("GLD", "sell", 66, "idea-1-stop-20261103-GLD-sl")
    assert kw["order_type"] == "stop" and kw["stop_price"] == 285.0 and kw["time_in_force"] == "gtc"
    assert db.db["paper_orders"][0]["status"] == "sent" and "protective" in db.db["paper_orders"][0]["reason"]


def test_a_matching_stop_is_left_alone(db, monkeypatch):
    resting = [{"id": "r1", "client_order_id": "idea-1-stop-20261102-GLD-sl", "symbol": "GLD", "qty": "66",
                "side": "sell", "type": "stop", "stop_price": "285.00", "order_class": "simple"}]
    calls = Calls()
    protect(db, Broker(pending=resting), calls, monkeypatch)
    assert calls.log == []


def test_a_changed_position_cancels_then_replaces(db, monkeypatch):
    resting = [{"id": "r1", "client_order_id": "idea-1-stop-20261102-GLD-sl", "symbol": "GLD", "qty": "40",
                "side": "sell", "type": "stop", "stop_price": "285.00", "order_class": "simple"}]
    calls = Calls()
    protect(db, Broker(pending=resting), calls, monkeypatch)
    assert [c[0] for c in calls.log] == ["cancel", "submit"] and calls.log[0][1] == "r1"


def test_switch_off_sends_nothing(db, monkeypatch):
    calls = Calls(fail=paper_orders.OrdersDisabled("off"))
    protect(db, Broker(), calls, monkeypatch)
    assert calls.log == [] and db.db["paper_orders"][0]["status"] == "skipped"


def test_close_based_ideas_are_left_alone(db, monkeypatch):
    db.db["idea_runs"][0]["spec"] = {**SPEC, "exits": {"stop_loss_pct": 5}}
    calls = Calls()
    protect(db, Broker(), calls, monkeypatch)
    assert calls.log == []


def test_a_switched_off_idea_has_its_stops_cancelled(db, monkeypatch):
    store.set_auto(db, 1, False, "kevin")
    resting = [{"id": "r1", "client_order_id": "idea-1-stop-20261102-GLD-sl", "symbol": "GLD", "qty": "66",
                "side": "sell", "type": "stop", "stop_price": "285.00", "order_class": "simple"}]
    calls = Calls()
    protect(db, Broker(pending=resting), calls, monkeypatch)
    assert calls.log == [("cancel", "r1", "idea-1-stop-20261102-GLD-sl")]


def test_holiday(db, monkeypatch):
    calls = Calls()
    summary, _ = protect(db, Broker(open_today=False), calls, monkeypatch)
    assert summary == {"market": "closed"} and calls.log == []


