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
                     "order_type": "market", "time_in_force": "day", "limit_price": None,
                     "book": "main"}]
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
    monkeypatch.setattr(service, "portfolio", lambda supa, **kw: {"state": "live", "positions": []})
    assert client.get("/api/v1/portfolio", headers=headers).status_code == 200


def test_protective_and_limit_shapes_die_at_the_schema(api):
    client, db, sent = api
    headers = _key(db)
    for over in ({"stop_price": 12.3}, {"order_class": "oco"}, {"time_in_force": "gtc"}):
        body = {"symbol": "XLE", "qty": 1, "side": "buy", "client_order_id": "x-1"}
        body.update(over)
        assert client.post("/api/v1/orders", json=body, headers=headers).status_code == 422
    assert sent == []


def test_a_stop_places_against_held_shares_under_the_stop_tag(api, monkeypatch):
    """2026-11-02: a machine stop (stop + stop_price + gtc) places when the account
    holds uncovered shares, namespaced into the ext-<key>-stop- family."""
    client, db, sent = api
    headers = _key(db)
    monkeypatch.setattr(machine_api, "stop_capacity", lambda symbol, side, book=None: 115)
    r = _post(client, headers, side="sell", qty=100, order_type="stop",
              time_in_force="gtc", stop_price=65.55)
    assert r.status_code == 200
    assert sent[0]["client_order_id"] == "ext-1-stop-run-1"
    assert sent[0]["order_type"] == "stop" and sent[0]["stop_price"] == 65.55
    assert sent[0]["time_in_force"] == "gtc"


def test_a_stop_refuses_beyond_the_uncovered_position(api, monkeypatch):
    client, db, sent = api
    headers = _key(db)
    monkeypatch.setattr(machine_api, "stop_capacity", lambda symbol, side, book=None: 40)
    r = _post(client, headers, side="sell", qty=100, order_type="stop",
              time_in_force="gtc", stop_price=65.55)
    assert r.status_code == 422 and "uncovered shares" in r.json()["detail"] and sent == []
    assert any(e["outcome"] == "refused:position" for e in _events(db))


def test_stop_shapes_that_are_not_protective_stops_refuse(api, monkeypatch):
    client, db, sent = api
    headers = _key(db)
    monkeypatch.setattr(machine_api, "stop_capacity", lambda symbol, side, book=None: 500)
    for over in ({"order_type": "stop", "time_in_force": "day", "stop_price": 65.55},
                 {"order_type": "stop", "time_in_force": "gtc"},
                 {"order_type": "market", "time_in_force": "gtc"},
                 {"order_type": "market", "stop_price": 65.55},
                 {"order_type": "trailing_stop", "time_in_force": "gtc", "stop_price": 65.55}):
        r = _post(client, headers, side="sell", qty=10, **over)
        assert r.status_code == 422, over
    assert sent == []


def test_a_stop_fails_closed_when_positions_cannot_be_read(api, monkeypatch):
    client, db, sent = api
    headers = _key(db)

    def boom(symbol, side, book=None):
        raise RuntimeError("alpaca down")

    monkeypatch.setattr(machine_api, "stop_capacity", boom)
    r = _post(client, headers, side="sell", qty=10, order_type="stop",
              time_in_force="gtc", stop_price=65.55)
    assert r.status_code == 424 and sent == []


def test_a_limit_order_places_through_submit(api):
    client, db, sent = api
    headers = _key(db)
    r = _post(client, headers, order_type="limit", limit_price=50.0)
    assert r.status_code == 200
    assert sent[0]["order_type"] == "limit" and sent[0]["limit_price"] == 50.0


def test_a_limit_orders_notional_is_priced_at_its_limit_not_the_last_trade(api):
    """The fixture's latest price is $100: 100 shares would pass the $25k cap at the last
    trade ($10k) and must still refuse at the limit price ($300 x 100 = $30k)."""
    client, db, sent = api
    headers = _key(db, max_notional=25_000)
    r = _post(client, headers, order_type="limit", limit_price=300.0, qty=100)
    assert r.status_code == 429 and "max_notional" in r.json()["detail"] and sent == []
    assert _post(client, headers, order_type="limit", limit_price=300.0, qty=10,
                 client_order_id="run-2").status_code == 200


def test_limit_and_market_shapes_still_refuse_cleanly(api):
    client, db, sent = api
    headers = _key(db)
    assert _post(client, headers, order_type="limit").status_code == 422  # no limit_price
    assert _post(client, headers, limit_price=50.0).status_code == 422  # price on a market order
    assert _post(client, headers, order_type="stop").status_code == 422
    assert _post(client, headers, time_in_force="gtc").status_code == 422  # a GTC market order
    assert sent == []
    # 2026-11-10: a GTC LIMIT is the door's second resting shape (Kevin: resting
    # exits must not expire daily); it places under the ext-<key>-gtc- family.
    r = _post(client, headers, order_type="limit", limit_price=50.0, time_in_force="gtc")
    assert r.status_code == 200 and sent[-1]["client_order_id"] == "ext-1-gtc-run-1"


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
                        lambda supa, **kw: {"state": "live", "account_number": "PA123", "positions": [1]})
    headers = _key(db)
    r = client.get("/api/v1/portfolio", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"state": "live", "positions": [1]}
    assert [e["outcome"] for e in _events(db)][-1] == "read"


def test_the_portfolio_read_needs_its_scope(api):
    client, db, _ = api
    headers = _key(db, scopes=("orders:place",))
    assert client.get("/api/v1/portfolio", headers=headers).status_code == 403


# ── step 4: read/cancel, ownership from the audit trail ─────────────────────────

BROKER_ORDER = {"id": "alpaca-1", "client_order_id": "ext-1-run-1", "symbol": "XLE",
                "qty": "2", "side": "buy", "status": "new",
                "submitted_at": "2026-11-01T12:00:01+00:00", "filled_avg_price": None}


@pytest.fixture
def api4(api, monkeypatch):
    client, db, sent = api
    cancels = []
    monkeypatch.setattr(alpaca_paper, "paper_get",
                        lambda path, params=None, **kw: [BROKER_ORDER] if path == "/v2/orders" else {})
    monkeypatch.setattr(paper_orders, "cancel_machine_order",
                        lambda order_id, cid, **kw: cancels.append((order_id, cid)))
    return client, db, sent, cancels


def test_the_list_shows_only_the_calling_keys_orders(api4):
    client, db, _, _ = api4
    mine = _key(db)
    theirs = _key(db)  # second key: id 2
    assert _post(client, mine).status_code == 200
    assert _post(client, theirs, client_order_id="run-9").status_code == 200
    orders = client.get("/api/v1/orders", headers=mine).json()["orders"]
    assert [o["client_order_id"] for o in orders] == ["ext-1-run-1"]
    assert orders[0]["status"] == "new" and orders[0]["alpaca_order_id"] == "alpaca-1"
    orders2 = client.get("/api/v1/orders", headers=theirs).json()["orders"]
    assert [o["client_order_id"] for o in orders2] == ["ext-2-run-9"]
    assert orders2[0]["status"] == "unknown"  # not in the broker window: stated, not hidden


def test_the_list_pages_by_event_id(api4):
    client, db, _, _ = api4
    headers = _key(db)
    for cid in ("p-1", "p-2", "p-3"):
        assert _post(client, headers, client_order_id=cid).status_code == 200
    page1 = client.get("/api/v1/orders", headers=headers, params={"limit": 2}).json()["orders"]
    assert [o["client_order_id"] for o in page1] == ["ext-1-p-3", "ext-1-p-2"]
    page2 = client.get("/api/v1/orders", headers=headers,
                       params={"limit": 2, "before": page1[-1]["event_id"]}).json()["orders"]
    assert [o["client_order_id"] for o in page2] == ["ext-1-p-1"]


def test_the_list_carries_the_staged_fields(api4):
    client, db, _, _ = api4
    headers = _key(db)
    assert _post(client, headers).status_code == 200
    view = client.get("/api/v1/orders", headers=headers).json()["orders"][0]
    # The staged-book fields (2026-11-02): what kind of order it is, at what price, how
    # much has filled -- the old view carried none of them.
    for field in ("type", "time_in_force", "qty", "filled_qty", "limit_price", "stop_price"):
        assert field in view
    assert view["qty"] == 2.0 and view["filled_qty"] is None


def test_the_open_filter_keeps_only_resting_orders(api4, monkeypatch):
    client, db, _, _ = api4
    headers = _key(db)
    assert _post(client, headers).status_code == 200
    resting = client.get("/api/v1/orders", headers=headers,
                         params={"status": "open"}).json()["orders"]
    assert [o["client_order_id"] for o in resting] == ["ext-1-run-1"]  # broker says "new"
    from tradehub.portfolio import alpaca_paper
    monkeypatch.setattr(alpaca_paper, "paper_get", lambda path, params=None, **kw: [])
    # Outside the broker window the status reads unknown: never presented as resting.
    assert client.get("/api/v1/orders", headers=headers,
                      params={"status": "open"}).json()["orders"] == []
    assert client.get("/api/v1/orders", headers=headers,
                      params={"status": "bogus"}).status_code == 422


def test_open_orders_lists_the_whole_broker_book(api4, monkeypatch):
    from tradehub.portfolio import alpaca_paper

    manual = {"id": "alpaca-9", "client_order_id": "9f2e-manual", "symbol": "XOM",
              "qty": "49", "filled_qty": "0", "side": "sell", "type": "stop",
              "time_in_force": "gtc", "stop_price": "175.00", "limit_price": None,
              "status": "new", "submitted_at": "2026-11-02T14:31:00+00:00",
              "filled_avg_price": None}

    def fake_get(path, params=None, **kw):
        if path == "/v2/orders" and (params or {}).get("status") == "open":
            return [BROKER_ORDER, manual]
        return [BROKER_ORDER] if path == "/v2/orders" else {}

    monkeypatch.setattr(alpaca_paper, "paper_get", fake_get)
    client, db, _, _ = api4
    headers = _key(db)
    body = client.get("/api/v1/orders/open", headers=headers).json()
    assert body["broker_reachable"] is True
    by_symbol = {o["symbol"]: o for o in body["orders"]}
    # The manual app order is in the staged book even though the API never placed it.
    assert by_symbol["XOM"]["stop_price"] == 175.0
    assert by_symbol["XOM"]["time_in_force"] == "gtc"
    assert by_symbol["XLE"]["client_order_id"] == "ext-1-run-1"


def test_the_admin_open_orders_endpoint_reads_the_broker_book(api4, monkeypatch):
    from tradehub.api import admin, main
    from tradehub.portfolio import alpaca_paper

    monkeypatch.setattr(alpaca_paper, "paper_get",
                        lambda path, params=None, **kw: [BROKER_ORDER] if path == "/v2/orders" else {})
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "k"}
    client, db, _, _ = api4
    resp = client.get("/api/portfolio/open-orders")
    assert resp.status_code == 200
    assert resp.json()["orders"][0]["symbol"] == "XLE"


def test_get_one_accepts_caller_or_namespaced_id_and_404s_for_anyone_else(api4):
    client, db, _, _ = api4
    mine = _key(db)
    theirs = _key(db)
    assert _post(client, mine).status_code == 200
    assert client.get("/api/v1/orders/run-1", headers=mine).status_code == 200
    assert client.get("/api/v1/orders/ext-1-run-1", headers=mine).json()["status"] == "new"
    assert client.get("/api/v1/orders/run-1", headers=theirs).status_code == 404
    assert client.get("/api/v1/orders/never-placed", headers=mine).status_code == 404


def test_cancel_happy_path_and_the_audit_says_so(api4):
    client, db, _, cancels = api4
    headers = _key(db)
    assert _post(client, headers).status_code == 200
    r = client.delete("/api/v1/orders/run-1", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert cancels == [("alpaca-1", "ext-1-run-1")]
    assert [e["outcome"] for e in _events(db)][-1] == "cancelled"


def test_cancel_someone_elses_order_is_a_404_and_never_reaches_the_broker(api4):
    client, db, _, cancels = api4
    mine = _key(db)
    theirs = _key(db)
    assert _post(client, mine).status_code == 200
    assert client.delete("/api/v1/orders/run-1", headers=theirs).status_code == 404
    assert cancels == []


def test_cancel_a_filled_order_is_a_409(api4, monkeypatch):
    client, db, _, _ = api4

    def gone(order_id, cid, **kw):
        raise paper_orders.OrderGone(order_id)

    monkeypatch.setattr(paper_orders, "cancel_machine_order", gone)
    headers = _key(db)
    assert _post(client, headers).status_code == 200
    assert client.delete("/api/v1/orders/run-1", headers=headers).status_code == 409


def test_cancels_work_with_the_kill_switch_off(api4, monkeypatch):
    client, db, _, cancels = api4
    headers = _key(db)
    assert _post(client, headers).status_code == 200
    monkeypatch.delenv("TRADEHUB_MACHINE_ORDERS")
    assert client.delete("/api/v1/orders/run-1", headers=headers).status_code == 200
    assert cancels == [("alpaca-1", "ext-1-run-1")]


def test_read_routes_need_read_scope_and_delete_needs_place_scope(api4):
    client, db, _, _ = api4
    placer = _key(db, scopes=("orders:place",))
    reader = _key(db, scopes=("orders:read",))
    assert client.get("/api/v1/orders", headers=placer).status_code == 403
    assert client.delete("/api/v1/orders/run-1", headers=reader).status_code == 403


def test_cancel_machine_order_refuses_protective_ids(monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s3cr3t")

    class Resp:
        status_code = 204

        def json(self):
            return {}

    with pytest.raises(ValueError):
        paper_orders.cancel_machine_order("abc-123", "idea-4-stop-aaaaaaaaaaaa",
                                          session=None)
    # the ext- shape passes the guard and reaches the (faked) session
    import tradehub.portfolio.paper_orders as po

    calls = []

    class Session:
        def delete(self, url, headers=None, timeout=None):
            calls.append(url)
            return Resp()

    po.cancel_machine_order("abc-123", "ext-1-run-1", session=Session())
    assert calls and calls[0].endswith("/v2/orders/abc-123")


# ── book awareness (handover item 6: the helpers and reads ignored the book) ──

def test_stop_capacity_reads_the_named_book(monkeypatch):
    seen = []

    def fake_get(path, params=None, **kw):
        seen.append(kw.get("book"))
        if path == "/v2/positions":
            return [{"symbol": "SPY", "qty": "120"}]
        return [{"symbol": "SPY", "side": "sell", "qty": "14"}]

    monkeypatch.setattr(alpaca_paper, "paper_get", fake_get)
    assert machine_api.stop_capacity("SPY", "sell", book="big") == 106
    assert seen == ["big", "big"]
    seen.clear()
    assert machine_api.stop_capacity("SPY", "sell") == 106  # default: the current book (main)
    assert seen == [None, None]


def test_broker_orders_reads_the_named_book(monkeypatch):
    seen = []

    def fake_get(path, params=None, **kw):
        seen.append(kw.get("book"))
        return [{"client_order_id": "ext-1-a", "status": "new"}]

    monkeypatch.setattr(alpaca_paper, "paper_get", fake_get)
    out = machine_api.broker_orders(book="big")
    assert list(out) == ["ext-1-a"] and seen == ["big"]


def test_portfolio_read_threads_the_book(api, monkeypatch):
    """Item 6 threaded ?book= through the reads; per-book keys (2026-11-03) bind the
    book to the KEY instead: no parameter reads the key's own book, a matching
    parameter is accepted, a mismatched one is a 403 (a key only ever sees its own
    book), and an unknown book name stays a 422."""
    client, db, sent = api
    headers = _key(db)
    seen = {}

    def fake_portfolio(supa, now=None, book_name=None):
        seen["book_name"] = book_name
        return {"state": "live", "positions": []}

    monkeypatch.setattr(service, "portfolio", fake_portfolio)
    assert client.get("/api/v1/portfolio", headers=headers).status_code == 200
    assert seen["book_name"] == "main"
    assert client.get("/api/v1/portfolio?book=main", headers=headers).status_code == 200
    assert client.get("/api/v1/portfolio?book=big", headers=headers).status_code == 403
    assert client.get("/api/v1/portfolio?book=nope", headers=headers).status_code == 422


def test_order_reads_thread_the_book(api, monkeypatch):
    client, db, sent = api
    headers = _key(db)
    seen = {}
    monkeypatch.setattr(machine_api, "placed_events", lambda supa, key_id: [])

    def fake_broker(book=None):
        seen["broker"] = book
        return {}

    def fake_open(book=None):
        seen["open"] = book
        return []

    monkeypatch.setattr(machine_api, "broker_orders", fake_broker)
    monkeypatch.setattr(machine_api, "open_broker_orders", fake_open)
    assert client.get("/api/v1/orders", headers=headers).status_code == 200
    assert seen["broker"] == "main"
    assert client.get("/api/v1/orders/open", headers=headers).status_code == 200
    assert seen["open"] == "main"
    assert client.get("/api/v1/orders?book=big", headers=headers).status_code == 403
    assert client.get("/api/v1/orders?book=nope", headers=headers).status_code == 422


# ── per-book keys (Kevin, 2026-11-03): the key's book is the only book it can touch ──

def test_key_book_defaults_to_main_for_legacy_rows():
    assert machine_api.key_book({}) == "main"
    assert machine_api.key_book({"book": None}) == "main"
    assert machine_api.key_book({"book": "big"}) == "big"


def test_a_big_book_key_places_on_the_big_book(api):
    client, db, sent = api
    headers = _key(db, book="big")
    r = _post(client, headers)
    assert r.status_code == 200 and sent[0]["book"] == "big"


def test_a_big_book_keys_stop_capacity_reads_the_big_book(api, monkeypatch):
    client, db, sent = api
    headers = _key(db, book="big")
    seen = {}

    def fake_capacity(symbol, side, book=None):
        seen["book"] = book
        return 115

    monkeypatch.setattr(machine_api, "stop_capacity", fake_capacity)
    r = _post(client, headers, side="sell", qty=100, order_type="stop",
              time_in_force="gtc", stop_price=65.55)
    assert r.status_code == 200
    assert seen["book"] == "big" and sent[0]["book"] == "big"


def test_a_big_book_key_reads_the_big_book_by_default(api, monkeypatch):
    client, db, sent = api
    headers = _key(db, book="big")
    seen = {}

    def fake_portfolio(supa, now=None, book_name=None):
        seen["book_name"] = book_name
        return {"state": "live", "positions": []}

    monkeypatch.setattr(service, "portfolio", fake_portfolio)
    assert client.get("/api/v1/portfolio", headers=headers).status_code == 200
    assert seen["book_name"] == "big"
    assert client.get("/api/v1/portfolio?book=main", headers=headers).status_code == 403


def test_a_big_book_key_cancels_on_the_big_book(api4, monkeypatch):
    client, db, sent, _ = api4
    headers = _key(db, book="big")
    assert _post(client, headers).status_code == 200
    assert sent[0]["book"] == "big"
    books_seen = []
    cancels = []

    def fake_get(path, params=None, **kw):
        books_seen.append(kw.get("book"))
        return [BROKER_ORDER] if path == "/v2/orders" else {}

    monkeypatch.setattr(alpaca_paper, "paper_get", fake_get)
    monkeypatch.setattr(paper_orders, "cancel_machine_order",
                        lambda order_id, cid, **kw: cancels.append((order_id, cid, kw.get("book"))))
    r = client.delete("/api/v1/orders/run-1", headers=headers)
    assert r.status_code == 200
    assert books_seen and all(b == "big" for b in books_seen)
    assert cancels == [("alpaca-1", "ext-1-run-1", "big")]


# ── circuit breakers: a tripped book refuses new openings, never exits or protection ──

def _tripped(monkeypatch, qty=0):
    monkeypatch.setattr("tradehub.portfolio.breakers.check",
                        lambda supa, book: {"enabled": True, "tripped": True, "reasons": ["daily loss 3%"]})
    monkeypatch.setattr(machine_api, "position_qty", lambda symbol, book=None: qty)


def test_a_tripped_breaker_refuses_an_opening_order_and_raises_a_notice(api, monkeypatch):
    client, db, sent = api
    _tripped(monkeypatch)
    r = _post(client, _key(db))
    assert r.status_code == 409 and "circuit breaker" in r.json()["detail"] and sent == []
    assert db.db["manual_actions"][0]["kind"] == "breaker"


def test_a_tripped_breaker_lets_a_closing_order_through(api, monkeypatch):
    client, db, sent = api
    _tripped(monkeypatch, qty=50)
    r = _post(client, _key(db), side="sell", qty=50)
    assert r.status_code == 200 and len(sent) == 1


def test_a_tripped_breaker_lets_a_protective_stop_through(api, monkeypatch):
    client, db, sent = api
    _tripped(monkeypatch)
    monkeypatch.setattr(machine_api, "stop_capacity", lambda symbol, side, book=None: 115)
    r = _post(client, _key(db), side="sell", qty=100, order_type="stop", time_in_force="gtc", stop_price=65.55)
    assert r.status_code == 200 and len(sent) == 1


def test_a_tripped_breaker_fails_closed_when_positions_are_unreadable(api, monkeypatch):
    client, db, sent = api
    _tripped(monkeypatch)

    def boom(symbol, book=None):
        raise RuntimeError("broker down")
    monkeypatch.setattr(machine_api, "position_qty", boom)
    r = _post(client, _key(db), side="sell", qty=50)
    assert r.status_code == 424 and sent == []


# ── preflight (2026-11-08): the same validators, run without submitting ──────

def _preflight(client, headers, **over):
    body = {"symbol": "XLE", "qty": 2, "side": "buy", "client_order_id": "run-1"}
    body.update(over)
    return client.post("/api/v1/orders/preflight", json=body, headers=headers)


def test_preflight_reports_headroom_and_places_nothing(api, monkeypatch):
    client, db, sent = api
    monkeypatch.setattr(alpaca_paper, "paper_get",
                        lambda path, params=None, **kw: {"buying_power": "50000"} if path == "/v2/account" else {})
    r = _preflight(client, _key(db))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and sent == []
    assert all(c["ok"] for c in body["checks"])
    head = body["headroom"]
    assert head["price_used"] == 100.0 and head["order_notional"] == 200.0
    assert head["daily_used"] == 0 and head["daily_remaining"] == 49  # after this order
    assert body["kill_switch"]["machine_orders"] is True
    assert body["kill_switch"]["breaker_tripped"] is False
    assert body["account"]["buying_power"] == 50000.0
    # A preflight is audited as a preflight -- never as a placement (the daily cap
    # counts outcome="placed" rows, so a dry run must not eat the cap).
    assert [e["outcome"] for e in _events(db)][-1] == "preflight"
    assert not any(e["outcome"] == "placed" for e in _events(db))


def test_preflight_flags_a_cap_failure_instead_of_refusing(api):
    client, db, sent = api
    r = _preflight(client, _key(db), qty=200)  # default max_qty is 100
    assert r.status_code == 200 and sent == []
    body = r.json()
    assert body["ok"] is False
    failed = [c for c in body["checks"] if not c["ok"]]
    assert failed and failed[0]["name"] == "max_qty"


def test_preflight_with_the_switch_off_reports_not_ok(api, monkeypatch):
    client, db, sent = api
    monkeypatch.delenv("TRADEHUB_MACHINE_ORDERS")
    r = _preflight(client, _key(db))
    assert r.status_code == 200 and r.json()["ok"] is False and sent == []
    assert r.json()["kill_switch"]["machine_orders"] is False


def test_preflight_needs_the_place_scope(api):
    client, db, sent = api
    assert _preflight(client, _key(db, scopes=("portfolio:read",))).status_code == 403


def test_preflight_a_sell_reports_held_qty_and_shortability(api, monkeypatch):
    client, db, sent = api
    monkeypatch.setattr(machine_api, "position_qty", lambda symbol, book=None: 30.0)
    monkeypatch.setattr(alpaca_paper, "asset_flags",
                        lambda symbol, **kw: {"tradable": True, "shortable": True,
                                              "easy_to_borrow": True, "fractionable": False})
    r = _preflight(client, _key(db), side="sell", qty=52)
    body = r.json()
    assert body["account"]["held_qty"] == 30.0
    checks = {c["name"]: c for c in body["checks"]}
    # 52 > 30 held: the trim overshoots into a short. Advisory, not a refusal --
    # sells-to-open are legal -- but the fact is on the page, with shortability.
    assert checks["held_qty"]["ok"] is False and checks["held_qty"]["blocking"] is False
    assert checks["shortable"]["ok"] is True
    assert body["ok"] is True and sent == []


def test_preflight_of_a_split_reports_the_child_plan(api):
    client, db, sent = api
    r = _preflight(client, _key(db), qty=208, split=True, client_order_id="trim")
    body = r.json()
    assert body["ok"] is True and sent == []
    children = body["plan"]["children"]
    assert [c["qty"] for c in children] == [100, 100, 8]  # the max_qty cap chunks it
    assert [c["client_order_id"] for c in children] == ["ext-1-trim-1", "ext-1-trim-2", "ext-1-trim-3"]
    assert body["headroom"]["daily_remaining"] == 50 - 3  # children count against the cap


# ── parent orders / server-side splitting (2026-11-08) ───────────────────────

def test_a_split_places_children_under_the_caps_and_audits_each(api):
    client, db, sent = api
    r = _post(client, _key(db), qty=208, split=True, client_order_id="trim")
    assert r.status_code == 200
    assert [(s["qty"], s["client_order_id"]) for s in sent] == [
        (100, "ext-1-trim-1"), (100, "ext-1-trim-2"), (8, "ext-1-trim-3")]
    body = r.json()
    assert body["client_order_id"] == "ext-1-trim" and body["placed_by"] == "api:mac scripts"
    group = body["group"]
    assert group["is_group"] is True and group["qty"] == 208.0
    placed = [e for e in _events(db) if e["outcome"] == "placed"]
    assert len(placed) == 3  # children count against the daily cap individually
    assert all((e["detail"] or "").startswith("group:trim") for e in placed)


def test_a_split_chunks_by_the_notional_cap_when_it_bites_harder(api, monkeypatch):
    client, db, sent = api
    monkeypatch.setattr(alpaca_paper, "latest_price", lambda symbol: 300.0)
    r = _post(client, _key(db, max_notional=25_000), qty=100, split=True, client_order_id="trim")
    assert r.status_code == 200
    # floor(25000 / 300) = 83 shares per child keeps every child under BOTH caps.
    assert [s["qty"] for s in sent] == [83, 17]


def test_a_split_refuses_before_placing_anything_when_the_daily_cap_cannot_hold_it(api):
    client, db, sent = api
    r = _post(client, _key(db, daily_cap=2), qty=208, split=True, client_order_id="trim")
    assert r.status_code == 429 and "daily_cap" in r.json()["detail"] and sent == []


def test_a_split_retry_counts_already_placed_children_as_placed(api):
    client, db, sent = api
    headers = _key(db)
    assert _post(client, headers, qty=208, split=True, client_order_id="trim").status_code == 200
    r = _post(client, headers, qty=208, split=True, client_order_id="trim")
    assert r.status_code == 200 and len(sent) == 3  # no child was placed twice


def test_a_split_that_fails_midway_reports_its_placed_children(api, monkeypatch):
    client, db, sent = api
    real_submit = paper_orders.submit

    def flaky(symbol, qty, side, client_order_id, **kwargs):
        if client_order_id.endswith("-2"):
            raise paper_orders.OrderRejected("broker said no")
        return real_submit(symbol, qty, side, client_order_id, **kwargs)

    monkeypatch.setattr(paper_orders, "submit", flaky)
    r = _post(client, _key(db), qty=208, split=True, client_order_id="trim")
    assert r.status_code == 422
    body = r.json()
    assert body["placed_children"] == ["ext-1-trim-1"]
    assert body["failed_child"]["client_order_id"] == "ext-1-trim-2"
    assert [s["client_order_id"] for s in sent] == ["ext-1-trim-1"]  # child 3 never attempted


def test_a_stop_cannot_be_split(api):
    client, db, sent = api
    r = _post(client, _key(db), side="sell", qty=10, split=True, order_type="stop",
              time_in_force="gtc", stop_price=65.55)
    assert r.status_code == 422 and sent == []


# ── session semantics (2026-11-08): when an accepted order actually goes live ──

from datetime import datetime as _dt, timezone as _tz  # noqa: E402

_SUN_EVENING = _dt(2026, 11, 8, 23, 0, tzinfo=_tz.utc)  # Sun 18:00 ET


def _order_view(**over):
    order = {"id": "alpaca-1", "client_order_id": "ext-1-x", "symbol": "GLD", "qty": "52",
             "filled_qty": "0", "side": "sell", "type": "market", "time_in_force": "opg",
             "status": "accepted", "submitted_at": "2026-11-08T23:00:00+00:00",
             "filled_avg_price": None, "limit_price": None, "stop_price": None}
    order.update(over)
    return machine_api.broker_order_view(order, now=_SUN_EVENING)


def test_an_opg_order_staged_sunday_is_held_for_mondays_open():
    view = _order_view()
    assert view["effective_session"] == "2026-11-09"  # Monday's auction, stated
    assert view["session_state"] == "held_for_open"  # never mistaken for working


def test_an_opg_order_sent_before_the_open_targets_that_open():
    view = _order_view(submitted_at="2026-11-09T13:00:00+00:00")  # Mon 08:00 ET
    assert view["effective_session"] == "2026-11-09"
    assert view["session_state"] == "held_for_open"


def test_an_opg_order_sent_after_the_open_rolls_to_the_next_session():
    view = _order_view(submitted_at="2026-11-09T15:00:00+00:00")  # Mon 10:00 ET
    assert view["effective_session"] == "2026-11-10"


def test_a_day_order_staged_on_a_sunday_is_held_for_monday():
    view = _order_view(time_in_force="day")
    assert view["effective_session"] == "2026-11-09" and view["session_state"] == "held_for_open"


def test_a_working_order_in_its_session_reads_active():
    view = _order_view(time_in_force="day", submitted_at="2026-11-09T17:00:00+00:00",
                       )  # Mon 12:00 ET
    assert machine_api.session_fields(
        {"time_in_force": "day", "submitted_at": "2026-11-09T17:00:00+00:00", "status": "new"},
        now=_dt(2026, 11, 9, 17, 5, tzinfo=_tz.utc)) == {
        "effective_session": "2026-11-09", "session_state": "active"}


def test_a_filled_order_is_never_held():
    view = _order_view(status="filled", filled_qty="52")
    assert view["session_state"] == "active"


def test_the_place_response_carries_the_session_fields(api):
    client, db, sent = api
    r = _post(client, _key(db), time_in_force="opg")
    assert r.status_code == 200
    assert r.json()["effective_session"] and r.json()["session_state"] in ("held_for_open", "active")


# ── combo read-back (2026-11-08): a multi-leg order never reads as plain filled ──

def _leg(symbol, side, intent, filled, price=None, ratio="1", status=None):
    return {"symbol": symbol, "side": side, "ratio_qty": ratio, "position_intent": intent,
            "qty": "1", "filled_qty": str(filled), "filled_avg_price": price,
            "status": status or ("filled" if filled else "new")}


def _mleg(status="filled", filled="1", leg_fills=("1", "1")):
    return {"id": "alpaca-mleg-1", "client_order_id": "idea-50-spread-abc", "symbol": None,
            "qty": "1", "filled_qty": filled, "side": None, "type": "limit",
            "order_class": "mleg", "time_in_force": "day", "status": status,
            "limit_price": "2.50", "stop_price": None,
            "submitted_at": "2026-11-08T15:00:00+00:00", "filled_avg_price": "2.50",
            "legs": [_leg("NVDA261204C00200000", "buy", "buy_to_open", leg_fills[0], "4.00"),
                     _leg("NVDA261204C00220000", "sell", "sell_to_open", leg_fills[1], "1.50")]}


def test_a_combo_view_carries_legs_expected_fills_and_a_leg_state():
    view = machine_api.broker_order_view(_mleg())
    assert view["leg_state"] == "complete" and "status_warning" not in view
    assert view["expected_leg_fills"] == [
        {"symbol": "NVDA261204C00200000", "side": "buy", "ratio_qty": 1.0, "qty": 1.0},
        {"symbol": "NVDA261204C00220000", "side": "sell", "ratio_qty": 1.0, "qty": 1.0}]
    assert [leg["filled_qty"] for leg in view["legs"]] == [1.0, 1.0]
    assert view["legs"][0]["position_intent"] == "buy_to_open"


def test_a_partially_filled_leg_is_a_warning_never_a_plain_fill():
    """The Idea 50 / combo-quantity lesson: the parent can claim a fill while a leg
    is short. That state gets its own warning status on the read-back."""
    view = machine_api.broker_order_view(_mleg(leg_fills=("1", "0")))
    assert view["status"] == "filled"  # the broker's word, preserved
    assert view["leg_state"] == "partial_leg_fill"
    assert view["status_warning"] == "partial_leg_fill"


def test_an_unfilled_combo_reads_pending_and_a_plain_order_has_no_leg_keys():
    view = machine_api.broker_order_view(_mleg(status="accepted", filled="0", leg_fills=("0", "0")))
    assert view["leg_state"] == "pending"
    plain = machine_api.broker_order_view(BROKER_ORDER)
    assert "legs" not in plain and "leg_state" not in plain


def test_the_combo_shape_reaches_the_open_orders_read(api4, monkeypatch):
    client, db, _, _ = api4
    monkeypatch.setattr(alpaca_paper, "paper_get",
                        lambda path, params=None, **kw: [_mleg(leg_fills=("1", "0"))]
                        if path == "/v2/orders" else {})
    body = client.get("/api/v1/orders/open", headers=_key(db)).json()
    view = body["orders"][0]
    assert view["leg_state"] == "partial_leg_fill" and view["status_warning"] == "partial_leg_fill"
    assert view["source"] == "hub" and view["idea_id"] == 50


# ── thesis tags (2026-11-08): a manual play keeps its label end to end ───────

def test_a_tag_is_stored_echoed_and_shown_on_reads(api4):
    client, db, _, _ = api4
    headers = _key(db)
    r = _post(client, headers, tag="gld-trim")
    assert r.status_code == 200 and r.json()["tag"] == "gld-trim"
    assert db.db["order_labels"][0]["tag"] == "gld-trim"
    listed = client.get("/api/v1/orders", headers=headers).json()["orders"]
    assert listed[0]["tag"] == "gld-trim"
    one = client.get("/api/v1/orders/run-1", headers=headers).json()
    assert one["tag"] == "gld-trim"


def test_an_untagged_order_reads_tag_none(api4):
    client, db, _, _ = api4
    headers = _key(db)
    assert _post(client, headers).status_code == 200
    assert client.get("/api/v1/orders", headers=headers).json()["orders"][0]["tag"] is None


def test_a_tag_with_bad_characters_or_length_dies_at_the_schema(api):
    client, db, sent = api
    headers = _key(db)
    for tag in ("gold trim", "bang!", "-leading-dash", "x" * 25, ""):
        assert _post(client, headers, tag=tag).status_code == 422, tag
    assert sent == []


def test_a_split_carries_the_tag_to_every_child(api):
    client, db, sent = api
    r = _post(client, _key(db), qty=208, split=True, client_order_id="trim", tag="gld-trim")
    assert r.status_code == 200 and r.json()["tag"] == "gld-trim"
    assert [row["tag"] for row in db.db["order_labels"]] == ["gld-trim"] * 3


# ── the book-wide open-orders read (2026-11-08): who placed what ─────────────

def test_open_orders_accepts_a_portfolio_read_key(api4):
    client, db, _, _ = api4
    reader = _key(db, scopes=("portfolio:read",))
    assert client.get("/api/v1/orders/open", headers=reader).status_code == 200
    place_only = _key(db, scopes=("orders:place",))
    assert client.get("/api/v1/orders/open", headers=place_only).status_code == 403


def test_open_orders_are_labelled_with_who_placed_them(api4, monkeypatch):
    from tradehub.portfolio import alpaca_paper
    from tradehub.workshop import store as workshop_store

    client, db, _, _ = api4
    mine = _key(db)               # key 1, "mac scripts"
    theirs = _key(db)             # key 2, also labelled "mac scripts" by the helper
    orders = [
        {**BROKER_ORDER, "id": "alpaca-1", "client_order_id": "ext-1-run-1"},
        {"id": "alpaca-2", "client_order_id": "ext-2-big-1", "symbol": "GLD", "qty": "52",
         "filled_qty": "0", "side": "sell", "type": "market", "time_in_force": "opg",
         "status": "accepted", "submitted_at": "2026-11-08T23:00:00+00:00", "filled_avg_price": None},
        {"id": "alpaca-3", "client_order_id": "idea-50-entry-abc", "symbol": "NVDA", "qty": "1",
         "filled_qty": "0", "side": "buy", "type": "limit", "time_in_force": "day",
         "status": "new", "submitted_at": "2026-11-08T20:00:00+00:00", "filled_avg_price": None},
        {"id": "alpaca-4", "client_order_id": "9f2e-manual", "symbol": "XOM", "qty": "49",
         "filled_qty": "0", "side": "sell", "type": "stop", "time_in_force": "gtc",
         "status": "new", "submitted_at": "2026-11-08T19:00:00+00:00", "filled_avg_price": None},
    ]
    monkeypatch.setattr(alpaca_paper, "paper_get",
                        lambda path, params=None, **kw: orders if path == "/v2/orders" else {})
    workshop_store.add_label(db, "alpaca-3", 50, "hub:idea engine")
    body = client.get("/api/v1/orders/open", headers=mine).json()
    by_id = {o["alpaca_order_id"]: o for o in body["orders"]}
    assert by_id["alpaca-1"]["placed_by"] == "api:mac scripts" and by_id["alpaca-1"]["source"] == "machine"
    assert by_id["alpaca-2"]["source"] == "machine"  # another key's order, still attributed
    assert by_id["alpaca-3"]["idea_id"] == 50 and by_id["alpaca-3"]["source"] == "hub"
    assert by_id["alpaca-4"]["placed_by"] == "unknown" and by_id["alpaca-4"]["source"] == "external"


def test_the_group_read_aggregates_children_fills(api, monkeypatch):
    client, db, sent = api
    headers = _key(db)
    assert _post(client, headers, qty=208, split=True, client_order_id="trim").status_code == 200
    kids = [
        {"id": "a1", "client_order_id": "ext-1-trim-1", "symbol": "XLE", "qty": "100", "side": "buy",
         "status": "filled", "filled_qty": "100", "filled_avg_price": "90.0",
         "submitted_at": "2026-11-01T12:00:01+00:00"},
        {"id": "a2", "client_order_id": "ext-1-trim-2", "symbol": "XLE", "qty": "100", "side": "buy",
         "status": "filled", "filled_qty": "100", "filled_avg_price": "110.0",
         "submitted_at": "2026-11-01T12:00:02+00:00"},
        {"id": "a3", "client_order_id": "ext-1-trim-3", "symbol": "XLE", "qty": "8", "side": "buy",
         "status": "filled", "filled_qty": "8", "filled_avg_price": "50.0",
         "submitted_at": "2026-11-01T12:00:03+00:00"},
    ]
    monkeypatch.setattr(alpaca_paper, "paper_get",
                        lambda path, params=None, **kw: kids if path == "/v2/orders" else {})
    body = client.get("/api/v1/orders/trim", headers=headers).json()
    assert body["is_group"] is True and body["status"] == "filled"
    assert body["qty"] == 208.0 and body["filled_qty"] == 208.0
    assert body["filled_avg_price"] == pytest.approx(20400 / 208)
    assert [c["client_order_id"] for c in body["children"]] == [
        "ext-1-trim-1", "ext-1-trim-2", "ext-1-trim-3"]
    listed = client.get("/api/v1/orders", headers=headers).json()["orders"]
    assert {o["client_order_id"]: o.get("group_id") for o in listed} == {
        "ext-1-trim-1": "trim", "ext-1-trim-2": "trim", "ext-1-trim-3": "trim"}
