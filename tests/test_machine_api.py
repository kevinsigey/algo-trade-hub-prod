"""Machine API step 2 (phase-2 spec §1.3/§1.4/§1.6): POST /api/v1/orders + GET /api/v1/portfolio.

The properties that matter: the routes are key-only (an admin JWT is a 401 here, and a machine
key is a 401 on the admin routes -- the separation runs both ways); the kill switch refuses
placements with 409 while reads keep working; caps refuse with 429 before submit is called;
a duplicate caller id can never become a second order; protective-shaped bodies die at the
schema; and every authenticated outcome writes exactly one audit event.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from workshop_fake import DB

from tradehub.api import machine_api, machine_keys, main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import alpaca_paper, paper_orders, service

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


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
    monkeypatch.setattr(machine_api, "LIMITER", machine_api.RateLimiter())  # buckets are per test
    monkeypatch.setenv("TRADEHUB_MACHINE_ORDERS", "on")
    main.app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(main.app), db, sent
    main.app.dependency_overrides.clear()


def _key(db, scopes=("orders:place", "orders:read", "portfolio:read"), **caps):
    _, plaintext = machine_keys.create_key(db, "mac scripts", list(scopes), **caps)
    return {"Authorization": f"Bearer {plaintext}"}


def _events(db, key_id=1):
    return [e for e in db.db.get(machine_keys.EVENTS, []) if e["key_id"] == key_id]


def _post(client, headers, **over):
    body = {"symbol": "XLE", "qty": 2, "side": "buy", "client_order_id": "run-1"}
    body.update(over)
    return client.post("/api/v1/orders", json=body, headers=headers)


# ── the auth matrix ──────────────────────────────────────────────────────────────

def test_no_header_and_garbage_key_are_401(api):
    client, db, sent = api
    assert _post(client, {}).status_code == 401
    assert _post(client, {"Authorization": "Bearer <redacted>"}).status_code == 401
    assert sent == [] and _events(db) == []  # a 401 has no key to audit against


def test_an_admin_jwt_is_not_a_machine_key(api):
    client, _, sent = api
    jwt_shaped = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6ImtldmluQGV4YW1wbGUuY29tIn0.signature"
    assert _post(client, {"Authorization": f"Bearer {jwt_shaped}"}).status_code == 401
    assert sent == []


def test_a_revoked_key_is_401(api):
    client, db, sent = api
    headers = _key(db)
    machine_keys.revoke_key(db, 1)
    assert _post(client, headers).status_code == 401
    assert sent == []


def test_the_wrong_scope_is_403_and_audited(api):
    client, db, sent = api
    headers = _key(db, scopes=("portfolio:read",))
    r = _post(client, headers)
    assert r.status_code == 403 and sent == []
    assert [e["outcome"] for e in _events(db)] == ["created", "refused:scope"]


# ── placement ────────────────────────────────────────────────────────────────────

def test_a_market_order_places_namespaced_labelled_and_audited(api):
    client, db, sent = api
    headers = _key(db)
    r = _post(client, headers)
    assert r.status_code == 200
    body = r.json()
    assert body["client_order_id"] == "ext-1-run-1"
    assert body["placed_by"] == "api:mac scripts"
    assert sent == [{"symbol": "XLE", "qty": 2, "side": "buy", "client_order_id": "ext-1-run-1",
                     "order_type": "market", "time_in_force": "day", "limit_price": None}]
    labels = db.db["order_labels"]
    assert labels[0]["by"] == "api:mac scripts" and labels[0]["order_id"] == "alpaca-1"
    placed = [e for e in _events(db) if e["outcome"] == "placed"]
    assert len(placed) == 1 and placed[0]["client_order_id"] == "ext-1-run-1"


def test_a_retry_with_the_same_caller_id_is_a_409_never_a_second_order(api):
    client, db, sent = api
    headers = _key(db)
    assert _post(client, headers).status_code == 200
    r = _post(client, headers)
    assert r.status_code == 409 and len(sent) == 1
    assert [e["outcome"] for e in _events(db)][-1] == "refused:duplicate"


def test_the_kill_switch_refuses_placements_but_not_reads(api, monkeypatch):
    client, db, sent = api
    headers = _key(db)
    monkeypatch.delenv("TRADEHUB_MACHINE_ORDERS")
    r = _post(client, headers)
    assert r.status_code == 409 and sent == []
    assert [e["outcome"] for e in _events(db)][-1] == "refused:switch_off"
    monkeypatch.setattr(service, "portfolio", lambda supa: {"state": "live", "positions": []})
    assert client.get("/api/v1/portfolio", headers=headers).status_code == 200


def test_protective_and_limit_shapes_die_at_the_schema(api):
    client, db, sent = api
    headers = _key(db)
    for over in ({"stop_price": 12.3}, {"order_class": "oco"}, {"time_in_force": "gtc", "order_type": "limit", "limit_price": 5}):
        body = {"symbol": "XLE", "qty": 1, "side": "buy", "client_order_id": "x-1"}
        body.update(over)
        assert client.post("/api/v1/orders", json=body, headers=headers).status_code == 422
    assert sent == []


def test_a_limit_order_is_refused_until_v11(api):
    client, db, sent = api
    headers = _key(db)
    r = _post(client, headers, order_type="limit", limit_price=50.0)
    assert r.status_code == 422 and "v1.1" in r.json()["detail"]
    assert sent == []


# ── caps ─────────────────────────────────────────────────────────────────────────

def test_the_qty_cap_refuses_before_submit(api):
    client, db, sent = api
    headers = _key(db, max_qty=5)
    r = _post(client, headers, qty=6)
    assert r.status_code == 429 and "max_qty" in r.json()["detail"] and sent == []


def test_the_notional_cap_prices_a_market_order_at_the_latest_trade(api, monkeypatch):
    client, db, sent = api
    monkeypatch.setattr(alpaca_paper, "latest_price", lambda symbol: 300.0)
    headers = _key(db, max_notional=25_000)
    r = _post(client, headers, qty=100)  # 100 x $300 = $30,000 > $25,000
    assert r.status_code == 429 and "max_notional" in r.json()["detail"] and sent == []
    assert _post(client, headers, qty=10, client_order_id="run-2").status_code == 200


def test_an_unpriceable_order_fails_closed(api, monkeypatch):
    client, db, sent = api

    def boom(symbol):
        raise RuntimeError("data host down")

    monkeypatch.setattr(alpaca_paper, "latest_price", boom)
    r = _post(client, _key(db))
    assert r.status_code == 424 and sent == []


def test_the_daily_cap_counts_from_the_audit_trail(api):
    client, db, sent = api
    headers = _key(db, daily_cap=2)
    assert _post(client, headers, client_order_id="a-1").status_code == 200
    assert _post(client, headers, client_order_id="a-2").status_code == 200
    r = _post(client, headers, client_order_id="a-3")
    assert r.status_code == 429 and "daily_cap" in r.json()["detail"] and len(sent) == 2


def test_the_rate_limiter_refuses_the_61st_request_in_a_minute():
    limiter = machine_api.RateLimiter(capacity=60)
    for _ in range(60):
        assert limiter.allow(9, now=NOW)
    assert not limiter.allow(9, now=NOW)
    assert limiter.allow(9, now=NOW + timedelta(seconds=61))
    assert limiter.allow(10, now=NOW)  # buckets are per key


# ── the portfolio read ───────────────────────────────────────────────────────────

def test_the_portfolio_read_drops_the_account_number_and_audits(api, monkeypatch):
    client, db, _ = api
    monkeypatch.setattr(service, "portfolio",
                        lambda supa: {"state": "live", "account_number": "PA123", "positions": [1]})
    headers = _key(db)
    r = client.get("/api/v1/portfolio", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"state": "live", "positions": [1]}
    assert [e["outcome"] for e in _events(db)][-1] == "read"


def test_the_portfolio_read_needs_its_scope(api):
    client, db, _ = api
    headers = _key(db, scopes=("orders:place",))
    assert client.get("/api/v1/portfolio", headers=headers).status_code == 403
