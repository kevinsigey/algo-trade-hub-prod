from datetime import UTC, date, datetime

from workshop_fake import DB

from tradehub.portfolio.reconcile import CHECKS, reconcile
from tradehub.workshop import store

NOW = datetime(2026, 11, 3, 14, 45, tzinfo=UTC)
SINCE = date(2026, 11, 3)


def _sent(db, cid="idea-1-auto-a", symbol="SPY", qty=13):
    db.table(store.ORDERS).insert({"idea_id": 1, "day": "2026-11-03", "book": "main", "symbol": symbol, "side": "buy",
                                   "qty": qty, "client_order_id": cid, "status": "sent"}).execute()


def _broker(status, filled, cid="idea-1-auto-a", qty=13, price=None):
    return {"client_order_id": cid, "status": status, "qty": str(qty), "filled_qty": str(filled),
            "filled_avg_price": price}


def test_expired_order_is_recorded_and_raises_a_manual_action():
    db = DB()
    _sent(db)
    out = reconcile(db, "main", SINCE, NOW, lambda: [_broker("expired", 0)])
    assert out == {"checked": 1, "problems": 1, "missing": 0}
    assert db.db[CHECKS][0]["broker_status"] == "expired" and db.db[CHECKS][0]["filled_qty"] == 0
    action = db.db["manual_actions"][0]
    assert action["symbol"] == "SPY" and "filled 0 of 13" in action["detail"]


def test_a_partial_fill_that_ended_is_a_problem():
    db = DB()
    _sent(db, symbol="GLD", qty=27)
    out = reconcile(db, "main", SINCE, NOW, lambda: [_broker("expired", 26, qty=27, price="400.5")])
    assert out["problems"] == 1 and db.db[CHECKS][0]["filled_avg_price"] == 400.5


def test_full_fill_raises_nothing_and_a_working_order_waits():
    db = DB()
    _sent(db)
    _sent(db, "idea-1-auto-b", "NVDA")
    out = reconcile(db, "main", SINCE, NOW, lambda: [_broker("filled", 13, price="500"), _broker("new", 0, "idea-1-auto-b")])
    assert out == {"checked": 1, "problems": 0, "missing": 0}
    assert "manual_actions" not in db.db and [c["client_order_id"] for c in db.db[CHECKS]] == ["idea-1-auto-a"]


def test_an_answered_order_is_not_raised_again_after_kevin_resolves_it():
    db = DB()
    _sent(db)
    reconcile(db, "main", SINCE, NOW, lambda: [_broker("expired", 0)])
    db.db["manual_actions"].clear()
    assert reconcile(db, "main", SINCE, NOW, lambda: [_broker("expired", 0)])["checked"] == 0
    assert db.db["manual_actions"] == []


def test_a_cancelled_protective_stop_is_not_a_problem():
    db = DB()
    _sent(db, "idea-1-stop-202611030945-sl")
    out = reconcile(db, "main", SINCE, NOW, lambda: [_broker("canceled", 0, "idea-1-stop-202611030945-sl")])
    assert out == {"checked": 0, "problems": 0, "missing": 0}


def test_a_sent_order_the_broker_does_not_show_is_counted():
    db = DB()
    _sent(db)
    assert reconcile(db, "main", SINCE, NOW, lambda: [])["missing"] == 1


def test_no_orders_skips_the_broker():
    def boom():
        raise AssertionError("no broker read needed")
    assert reconcile(DB(), "main", SINCE, NOW, boom)["checked"] == 0
