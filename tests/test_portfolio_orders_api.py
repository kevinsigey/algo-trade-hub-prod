"""POST /api/portfolio/orders: the signed-in-only hand order endpoint.

The properties that matter: no admin session, no order (401, and submit is never called);
the order goes through paper_orders.submit -- the codebase's only order path -- with a
client_order_id that carries the idea tag when an idea is named; and each refusal from the
order path maps to an honest status (switch off 409, duplicate 409, account 424, refused 422).
"""
import pytest
from fastapi.testclient import TestClient

from tradehub.api import admin, main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import paper_orders


@pytest.fixture
def api(monkeypatch):
    sent = []

    def fake_submit(symbol, qty, side, client_order_id, **kwargs):
        sent.append({"symbol": symbol, "qty": qty, "side": side,
                     "client_order_id": client_order_id, **kwargs})
        return {"id": "alpaca-1", "status": "accepted"}

    monkeypatch.setattr(paper_orders, "submit", fake_submit)
    main.app.dependency_overrides[get_supabase] = lambda: object()
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    yield TestClient(main.app), sent
    main.app.dependency_overrides.clear()


def test_an_order_needs_admin(api):
    client, sent = api
    main.app.dependency_overrides.pop(admin.require_admin)
    r = client.post("/api/portfolio/orders", json={"symbol": "XLE", "qty": 1, "side": "buy"})
    assert r.status_code == 401
    assert sent == []


def test_a_market_order_goes_through_submit_with_a_manual_tag(api):
    client, sent = api
    r = client.post("/api/portfolio/orders", json={"symbol": "xle", "qty": 3, "side": "buy"})
    assert r.status_code == 200
    body = r.json()
    assert body["placed_by"] == "kevin@example.com"
    assert body["client_order_id"].startswith("manual-")
    assert sent == [{"symbol": "XLE", "qty": 3, "side": "buy", "client_order_id": body["client_order_id"],
                     "order_type": "market", "time_in_force": "day", "limit_price": None}]


def test_an_idea_order_carries_the_idea_tag(api):
    client, sent = api
    r = client.post("/api/portfolio/orders",
                    json={"symbol": "XLE", "qty": 1, "side": "buy", "idea_id": 12})
    assert r.status_code == 200
    assert r.json()["client_order_id"].startswith("idea-12-manual-")
    assert not r.json()["client_order_id"].startswith("idea-12-stop-")  # never a protective tag


def test_a_limit_order_needs_a_price_and_passes_it(api):
    client, sent = api
    bad = client.post("/api/portfolio/orders",
                      json={"symbol": "XLE", "qty": 1, "side": "buy", "order_type": "limit"})
    assert bad.status_code == 422 and sent == []
    ok = client.post("/api/portfolio/orders",
                     json={"symbol": "XLE", "qty": 1, "side": "sell", "order_type": "limit",
                           "limit_price": 91.5, "time_in_force": "cls"})
    assert ok.status_code == 200
    assert sent[0]["limit_price"] == 91.5 and sent[0]["time_in_force"] == "cls"


def test_protective_shapes_are_refused(api):
    client, sent = api
    for payload in ({"symbol": "XLE", "qty": 1, "side": "buy", "order_type": "stop", "limit_price": 1},
                    {"symbol": "XLE", "qty": 1, "side": "buy", "time_in_force": "gtc"},
                    {"symbol": "not a ticker!", "qty": 1, "side": "buy"},
                    {"symbol": "XLE", "qty": 1, "side": "hold"}):
        assert client.post("/api/portfolio/orders", json=payload).status_code == 422, payload
    assert sent == []


def test_order_path_refusals_map_to_honest_statuses(api, monkeypatch):
    client, _ = api

    def raise_disabled(*a, **k):
        raise paper_orders.OrdersDisabled("TRADEHUB_PAPER_ORDERS is off")

    monkeypatch.setattr(paper_orders, "submit", raise_disabled)
    r = client.post("/api/portfolio/orders", json={"symbol": "XLE", "qty": 1, "side": "buy"})
    assert r.status_code == 409 and "off" in r.json()["detail"]

    def raise_rejected(*a, **k):
        raise paper_orders.OrderRejected("insufficient buying power")

    monkeypatch.setattr(paper_orders, "submit", raise_rejected)
    r = client.post("/api/portfolio/orders", json={"symbol": "XLE", "qty": 1, "side": "buy"})
    assert r.status_code == 422 and "buying power" in r.json()["detail"]
