"""Extended-hours equity orders through the machine door (Kevin via the
trading chat, 2026-11-17): extended_hours=true passes through to Alpaca
on limit orders with time_in_force day or gtc, so an order can fill in
the pre-market, after-hours and overnight sessions. The door mirrors
the broker's fence at validation: market orders, opg/cls times in
force, options and splits with the flag are 422 on place AND preflight
(they share validate_order). A gtc extended-hours order rides the
existing ext-<key>-gtc- namespacing -- the sanction the service layer
requires for a resting limit -- and the preflight's extended_hours
check line states the session eligibility.
"""
import pytest
from fastapi.testclient import TestClient
from workshop_fake import DB

from tradehub.api import machine_api, machine_keys, main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import alpaca_paper, paper_orders


@pytest.fixture
def api(monkeypatch):
    db = DB()
    sent = []
    held = {}

    def fake_submit(symbol, qty, side, client_order_id, **kwargs):
        if any(s["client_order_id"] == client_order_id for s in sent):
            raise paper_orders.DuplicateOrder(client_order_id)
        sent.append({"symbol": symbol, "qty": qty, "side": side,
                     "client_order_id": client_order_id, **kwargs})
        return {"id": f"alpaca-{len(sent)}", "status": "accepted"}

    monkeypatch.setattr(paper_orders, "submit", fake_submit)
    monkeypatch.setattr(alpaca_paper, "latest_price", lambda symbol: 100.0)
    monkeypatch.setattr(alpaca_paper, "paper_get",
                        lambda path, params=None, **kw: (_ for _ in ()).throw(
                            alpaca_paper.AccountNotConnected("test fixture")))
    monkeypatch.setattr(machine_api, "position_qty",
                        lambda symbol, book=None: held.get(symbol, 0.0))
    monkeypatch.setattr(machine_api, "LIMITER", machine_api.RateLimiter())
    monkeypatch.setenv("TRADEHUB_MACHINE_ORDERS", "on")
    main.app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(main.app), db, sent, held
    main.app.dependency_overrides.clear()


def _key(db):
    _, plaintext = machine_keys.create_key(
        db, "mac scripts", ["orders:place", "orders:read", "portfolio:read"])
    return {"Authorization": f"Bearer {plaintext}"}


def _body(**over):
    body = {"symbol": "GLD", "qty": 10, "side": "buy",
            "client_order_id": "ext-1", "order_type": "limit",
            "limit_price": 378.80, "time_in_force": "day",
            "extended_hours": True, "reason": "test placement"}
    body.update(over)
    return body


def _post(client, headers, **over):
    return client.post("/api/v1/orders", json=_body(**over), headers=headers)


def _preflight(client, headers, **over):
    return client.post("/api/v1/orders/preflight", json=_body(**over),
                       headers=headers)


def test_a_day_limit_passes_extended_hours_through(api):
    client, db, sent, _ = api
    r = _post(client, _key(db))
    assert r.status_code == 200, r.text
    assert len(sent) == 1
    assert sent[0]["extended_hours"] is True
    assert sent[0]["client_order_id"] == "ext-1-ext-1"


def test_a_gtc_limit_rides_the_sanctioned_gtc_family(api):
    client, db, sent, _ = api
    r = _post(client, _key(db), time_in_force="gtc")
    assert r.status_code == 200, r.text
    assert sent[0]["extended_hours"] is True
    # The ext-<key>-gtc- namespace is the tag paper_orders sanctions for
    # a resting gtc limit; the service layer would refuse anything else.
    assert sent[0]["client_order_id"] == "ext-1-gtc-ext-1"
    assert r.json()["client_order_id"] == "ext-1-gtc-ext-1"


def test_without_the_flag_nothing_changes(api):
    client, db, sent, _ = api
    r = _post(client, _key(db), extended_hours=False)
    assert r.status_code == 200, r.text
    # The kwarg joins the submit call only when the flag is set, so an
    # ordinary order's call shape is byte-identical to before.
    assert "extended_hours" not in sent[0]


@pytest.mark.parametrize("over", [
    {"order_type": "market", "limit_price": None},
    {"time_in_force": "opg"},
    {"time_in_force": "cls"},
    {"split": True},
])
def test_refused_shapes_422_on_place_and_preflight(api, over):
    client, db, sent, _ = api
    headers = _key(db)
    r = _post(client, headers, **over)
    assert r.status_code == 422, r.text
    p = _preflight(client, headers, **over)
    assert p.status_code == 200 and p.json()["ok"] is False
    check = [c for c in p.json()["checks"] if c["name"] == "extended_hours"]
    assert check and check[0]["ok"] is False
    assert sent == []


def test_an_option_order_with_the_flag_is_422(api):
    client, db, sent, _ = api
    headers = _key(db)
    r = _post(client, headers, symbol="SPY261218C00600000")
    assert r.status_code == 422, r.text
    assert "extended" in r.json()["detail"]
    p = _preflight(client, headers, symbol="SPY261218C00600000")
    assert p.json()["ok"] is False
    assert sent == []


def test_preflight_states_the_session_eligibility(api):
    client, db, sent, _ = api
    p = _preflight(client, _key(db))
    assert p.status_code == 200 and p.json()["ok"] is True
    check = [c for c in p.json()["checks"] if c["name"] == "extended_hours"]
    assert len(check) == 1 and check[0]["ok"] is True
    assert "04:00-09:30 ET" in check[0]["detail"]
    assert "20:00-04:00 ET" in check[0]["detail"]


def test_preflight_plan_for_a_gtc_extended_hours_order(api):
    client, db, sent, _ = api
    p = _preflight(client, _key(db), time_in_force="gtc")
    assert p.json()["ok"] is True
    assert p.json()["plan"]["children"] == [
        {"qty": 10, "client_order_id": "ext-1-gtc-ext-1"}]
