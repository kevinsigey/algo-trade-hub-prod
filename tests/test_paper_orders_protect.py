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
    def __init__(self, pending=(), states=None, **kw):
        super().__init__(fills=FILLS, orders=ORDERS, **kw)
        self.open_orders = list(pending)
        self.states = states or {}  # order id -> statuses Alpaca reports after a cancel, in order
        self.reads = []

    def __call__(self, path, params=None):
        if path == "/v2/orders" and (params or {}).get("status") == "open":
            return self.open_orders
        if path.startswith("/v2/orders/"):
            oid = path.rsplit("/", 1)[1]
            self.reads.append(oid)
            seq = self.states.get(oid, ["canceled"])
            return {"id": oid, "status": seq.pop(0) if len(seq) > 1 else seq[0]}
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


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(paper_orders_protect, "_sleep", lambda s: None)


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
    assert (symbol, side, qty, cid) == ("GLD", "sell", 66, "idea-1-stop-202611030945-GLD-sl")
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




def test_no_stop_beside_a_pending_close(db, monkeypatch):
    # Review C1: the morning's close (cls / day limit) hasn't filled at 14:45; a stop now would be a second exit.
    pending_close = [{"id": "c1", "client_order_id": "idea-1-auto-20261103-GLD-close", "symbol": "GLD", "qty": "66",
                      "side": "sell", "type": "market", "order_class": "simple"}]
    calls = Calls()
    protect(db, Broker(pending=pending_close), calls, monkeypatch)
    assert calls.log == []


def test_a_stop_resting_with_no_shares_is_cancelled(db, monkeypatch):
    # Review C1: a buy stop on a short that's already covered would open a long when it triggers.
    db.db["idea_runs"][0]["spec"] = {**INTRADAY, "hold": [], "short": ["GLD"]}
    resting = [{"id": "r1", "client_order_id": "idea-1-stop-20261102-GLD-sl", "symbol": "GLD", "qty": "66",
                "side": "buy", "type": "stop", "stop_price": "315.00", "order_class": "simple"}]
    calls = Calls()
    broker = Broker(pending=resting)
    broker.fills = []  # covered: the idea holds nothing
    protect(db, broker, calls, monkeypatch)
    assert [c[0] for c in calls.log] == ["cancel"]


def test_not_before_the_open(db, monkeypatch):
    calls = Calls()
    monkeypatch.setattr(service, "paper_get", Broker())
    early = datetime.fromisoformat("2026-11-03T14:00:00+00:00")  # 09:00 New York (EST): before the open
    summary, _ = paper_orders_protect.run(early, db, submit=calls.submit, cancel=calls.cancel)
    assert summary == {"market": "not open yet"} and calls.log == []


def test_replacement_waits_for_the_cancel_to_finish(db, monkeypatch):
    # Review I4: Alpaca's DELETE only starts a cancel; the shares stay held until it reads "canceled".
    resting = [{"id": "r1", "client_order_id": "idea-1-stop-20261102-GLD-sl", "symbol": "GLD", "qty": "40",
                "side": "sell", "type": "stop", "stop_price": "285.00", "order_class": "simple"}]
    broker = Broker(pending=resting, states={"r1": ["pending_cancel", "pending_cancel", "canceled"]})
    calls = Calls()
    protect(db, broker, calls, monkeypatch)
    assert broker.reads == ["r1", "r1", "r1"] and [c[0] for c in calls.log] == ["cancel", "submit"]


def test_a_cancel_that_never_finishes_places_nothing(db, monkeypatch):
    resting = [{"id": "r1", "client_order_id": "idea-1-stop-20261102-GLD-sl", "symbol": "GLD", "qty": "40",
                "side": "sell", "type": "stop", "stop_price": "285.00", "order_class": "simple"}]
    calls = Calls()
    summary, failed = protect(db, Broker(pending=resting, states={"r1": ["pending_cancel"]}), calls, monkeypatch)
    assert [c[0] for c in calls.log] == ["cancel"] and 1 in failed


def test_two_replacements_in_one_day_get_distinct_tags(db, monkeypatch):
    # Review I5: the second replacement must not collide with the first's client_order_id.
    from tradehub.portfolio.autotrade import protective
    from tradehub.workshop.spec import Exits
    a = protective(1, Exits(stop_loss_pct=5), "GLD", 66, 300.0, "202611031445")
    b = protective(1, Exits(stop_loss_pct=5), "GLD", 40, 300.0, "202611031600")
    assert a["client_order_id"] != b["client_order_id"] and a["client_order_id"].startswith("idea-1-stop-")
