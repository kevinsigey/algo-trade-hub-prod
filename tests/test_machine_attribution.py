"""Order attribution (Claude review A1, 2026-11-11): every order placed through
the machine API must carry an idea id or a stated reason. The Workshop's claim is
that every strategy has rules fixed in advance; the order API was a second door
with no such rule -- all 142 historical API orders carry a null idea.

The properties that matter: a placement with neither idea_id nor reason is
refused 422 before anything reaches the broker, on shares, options and
preflight alike; an idea_id that names no workshop idea is refused; a stated
reason is stored on the order's label row and read back in attribution; the
Portfolio results split counts closed trades as tested (idea-attributed) or
discretionary (everything else, with its reasons).
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from workshop_fake import DB

from tradehub.api import machine_api, machine_keys, main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import alpaca_paper, book, paper_orders

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def api(monkeypatch):
    db = DB()
    sent = []

    def fake_submit(symbol, qty, side, client_order_id, **kwargs):
        if any(s["client_order_id"] == client_order_id for s in sent):
            raise paper_orders.DuplicateOrder(client_order_id)
        sent.append({"symbol": symbol, "qty": qty, "side": side,
                     "client_order_id": client_order_id, **kwargs})
        return {"id": f"alpaca-{len(sent)}", "status": "accepted"}

    monkeypatch.setattr(paper_orders, "submit", fake_submit)
    monkeypatch.setattr(alpaca_paper, "latest_price", lambda symbol: 100.0)
    monkeypatch.setattr(machine_api, "LIMITER", machine_api.RateLimiter())
    monkeypatch.setenv("TRADEHUB_MACHINE_ORDERS", "on")
    main.app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(main.app), db, sent
    main.app.dependency_overrides.clear()


def _key(db, scopes=("orders:place", "orders:read", "portfolio:read"), **caps):
    _, plaintext = machine_keys.create_key(db, "mac scripts", list(scopes), **caps)
    return {"Authorization": f"Bearer {plaintext}"}


def _post(client, headers, **over):
    body = {"symbol": "XLE", "qty": 2, "side": "buy", "client_order_id": "run-1"}
    body.update(over)
    return client.post("/api/v1/orders", json=body, headers=headers)


def test_a_share_order_with_neither_idea_nor_reason_is_refused(api):
    client, db, sent = api
    resp = _post(client, _key(db))
    assert resp.status_code == 422
    assert "idea_id" in resp.json()["detail"] and "reason" in resp.json()["detail"]
    assert sent == []


def test_a_reason_alone_places_and_is_stored_on_the_label(api):
    client, db, sent = api
    resp = _post(client, _key(db), reason="rebalance: trim gold toward target")
    assert resp.status_code == 200, resp.text
    assert len(sent) == 1
    labels = db.db.get("order_labels", [])
    assert len(labels) == 1
    assert labels[0]["idea_id"] is None
    assert labels[0]["reason"] == "rebalance: trim gold toward target"
    assert resp.json()["reason"] == "rebalance: trim gold toward target"


def test_an_unknown_idea_id_is_refused(api):
    client, db, sent = api
    resp = _post(client, _key(db), idea_id=999)
    assert resp.status_code == 422
    assert "999" in resp.json()["detail"]
    assert sent == []


def test_a_known_idea_id_places_and_labels_the_idea(api):
    client, db, sent = api
    db.db.setdefault("ideas", []).append({"id": 7, "title": "T8 Core"})
    resp = _post(client, _key(db), idea_id=7)
    assert resp.status_code == 200, resp.text
    labels = db.db.get("order_labels", [])
    assert labels and labels[0]["idea_id"] == 7


def test_preflight_refuses_without_attribution_too(api):
    client, db, sent = api
    headers = _key(db)
    body = {"symbol": "XLE", "qty": 2, "side": "buy", "client_order_id": "run-1"}
    resp = client.post("/api/v1/orders/preflight", json=body, headers=headers)
    assert resp.status_code == 200  # preflight answers, it does not raise
    payload = resp.json()
    assert payload["ok"] is False
    check = next(c for c in payload["checks"] if c["name"] == "attribution")
    assert check["ok"] is False and check["blocking"] is True


def test_attribution_rides_the_open_orders_readback(api):
    client, db, sent = api
    headers = _key(db)
    assert _post(client, headers, reason="breakeven exit").status_code == 200

    views = [{"alpaca_order_id": "alpaca-1", "client_order_id": "ext-1-run-1"}]
    out = machine_api.attribute_orders(db, views)
    assert out[0]["idea_id"] is None
    assert out[0]["reason"] == "breakeven exit"


def _fill(symbol, side, qty, price, at, order_id, idea_id=None, idea=None, reason=None):
    return {"symbol": symbol, "side": side, "qty": qty, "price": price,
            "transaction_time": at, "order_id": order_id,
            "idea_id": idea_id, "idea": idea or book.MANUAL, "reason": reason}


def test_results_split_counts_tested_and_discretionary_with_reasons():
    fills = [
        # tested idea round trip: +$20
        _fill("AAA", "buy", 10, 100.0, "2026-11-01T15:00:00Z", "o1", 7, "T8 Core"),
        _fill("AAA", "sell", 10, 102.0, "2026-11-03T15:00:00Z", "o2", 7, "T8 Core"),
        # discretionary round trip with a reason: -$5
        _fill("BBB", "buy", 5, 50.0, "2026-11-02T15:00:00Z", "o3", None, None, "trim gold"),
        _fill("BBB", "sell", 5, 49.0, "2026-11-04T15:00:00Z", "o4"),
        # discretionary round trip with no reason recorded: +$10
        _fill("CCC", "buy", 2, 10.0, "2026-11-02T15:00:00Z", "o5"),
        _fill("CCC", "sell", 2, 15.0, "2026-11-05T15:00:00Z", "o6"),
    ]
    split = book.results_split(book.closed_trades(fills))
    assert split["tested"] == {"trades": 1, "pnl": 20.0, "wins": 1}
    assert split["discretionary"]["trades"] == 2
    assert split["discretionary"]["pnl"] == 5.0
    reasons = {r["reason"]: r for r in split["discretionary"]["reasons"]}
    assert reasons["trim gold"] == {"reason": "trim gold", "trades": 1, "pnl": -5.0}
    assert reasons["no reason recorded"]["trades"] == 1
    assert reasons["no reason recorded"]["pnl"] == 10.0
