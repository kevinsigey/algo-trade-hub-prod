"""GTC share limits through the machine door + resting-sell netting (Kevin,
2026-11-10): the machine door takes a good-till-cancelled LIMIT order for
shares, namespaced into its own ext-<key>-gtc- tag family, so a resting exit
does not have to be re-placed every session. Options stay day-only through
the door; GTC market orders are refused (a standing market order is a
different risk animal and nothing needs it); a split may not be GTC (one
resting order, like a stop).

The exit test NETS resting sells (guardrail, 2026-11-10): a sell is an exit
only up to the UNRESERVED held quantity -- held minus the quantity already
reserved by resting sell orders on that book, however they are tagged
(machine, idea, manual, stops included). Two overlapping resting exits can
therefore never each classify as an exit and together oversell the position.
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
    resting = []  # broker open orders: {"symbol", "side", "qty"}

    def fake_submit(symbol, qty, side, client_order_id, **kwargs):
        if any(s["client_order_id"] == client_order_id for s in sent):
            raise paper_orders.DuplicateOrder(client_order_id)
        sent.append({ "reason": "test placement","symbol": symbol, "qty": qty, "side": side,
                     "client_order_id": client_order_id, **kwargs})
        return {"id": f"alpaca-{len(sent)}", "status": "accepted"}

    def fake_paper_get(path, params=None, **kw):
        if path == "/v2/orders":
            return [{ "reason": "test placement","symbol": o["symbol"], "side": o["side"], "qty": str(o["qty"]),
                     "filled_qty": "0", "status": "new",
                     "client_order_id": o.get("client_order_id", "resting-1")}
                    for o in resting]
        raise alpaca_paper.AccountNotConnected("test fixture: only /v2/orders is served")

    monkeypatch.setattr(paper_orders, "submit", fake_submit)
    monkeypatch.setattr(alpaca_paper, "latest_price", lambda symbol: 100.0)
    monkeypatch.setattr(alpaca_paper, "paper_get", fake_paper_get)
    monkeypatch.setattr(machine_api, "position_qty",
                        lambda symbol, book=None: held.get(symbol, 0.0))
    monkeypatch.setattr(machine_api, "LIMITER", machine_api.RateLimiter())
    monkeypatch.setenv("TRADEHUB_MACHINE_ORDERS", "on")
    main.app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(main.app), db, sent, held, resting
    main.app.dependency_overrides.clear()


def _key(db, **caps):
    _, plaintext = machine_keys.create_key(db, "mac scripts",
                                           ["orders:place", "orders:read", "portfolio:read"], **caps)
    return {"Authorization": f"Bearer {plaintext}"}


def _post(client, headers, **over):
    body = { "reason": "test placement","symbol": "GLD", "qty": 10, "side": "sell", "client_order_id": "trim-1",
            "order_type": "limit", "limit_price": 378.80, "time_in_force": "gtc"}
    body.update(over)
    return client.post("/api/v1/orders", json=body, headers=headers)


def _preflight(client, headers, **over):
    body = { "reason": "test placement","symbol": "GLD", "qty": 10, "side": "sell", "client_order_id": "trim-1",
            "order_type": "limit", "limit_price": 378.80, "time_in_force": "gtc"}
    body.update(over)
    return client.post("/api/v1/orders/preflight", json=body, headers=headers)


# ── the door takes a GTC limit ──────────────────────────────────────────────

def test_a_gtc_limit_places_under_the_gtc_tag_family(api):
    client, db, sent, held, resting = api
    held["GLD"] = 300.0
    resp = _post(client, _key(db))
    assert resp.status_code == 200, resp.text
    assert len(sent) == 1
    order = sent[0]
    assert order["time_in_force"] == "gtc" and order["order_type"] == "limit"
    assert order["client_order_id"].startswith("ext-1-gtc-"), order["client_order_id"]
    assert resp.json()["exit"]["is_exit"] is True


def test_a_gtc_market_order_is_refused(api):
    client, db, sent, held, resting = api
    held["GLD"] = 300.0
    resp = _post(client, _key(db), order_type="market", limit_price=None)
    assert resp.status_code == 422, resp.text
    assert "limit" in resp.json()["detail"]
    assert sent == []


def test_an_unknown_tif_is_still_refused(api):
    client, db, sent, held, resting = api
    held["GLD"] = 300.0
    resp = _post(client, _key(db), time_in_force="ioc")
    assert resp.status_code == 422, resp.text
    assert "gtc" in resp.json()["detail"]  # the message names the widened set
    assert sent == []


def test_a_gtc_split_is_refused_as_one_order(api):
    client, db, sent, held, resting = api
    held["GLD"] = 300.0
    resp = _post(client, _key(db), split=True, qty=50)
    assert resp.status_code == 422, resp.text
    assert sent == []


def test_a_day_limit_still_places_under_the_plain_family(api):
    client, db, sent, held, resting = api
    held["GLD"] = 300.0
    resp = _post(client, _key(db), time_in_force="day")
    assert resp.status_code == 200, resp.text
    assert sent[0]["client_order_id"].startswith("ext-1-")
    assert "-gtc-" not in sent[0]["client_order_id"]


# ── guardrail 1: the exit test nets resting sells ───────────────────────────

def test_resting_reserved_qty_sums_open_sells_only(monkeypatch):
    orders = [
        {"symbol": "IBIT", "side": "sell", "qty": "400", "filled_qty": "0"},
        {"symbol": "IBIT", "side": "buy", "qty": "50", "filled_qty": "0"},
        {"symbol": "GLD", "side": "sell", "qty": "10", "filled_qty": "0"},
    ]
    monkeypatch.setattr(alpaca_paper, "paper_get", lambda path, params=None, **kw: orders)
    assert machine_api.resting_reserved_qty("IBIT", "sell") == 400.0
    assert machine_api.resting_reserved_qty("IBIT", "buy") == 50.0


def test_classification_nets_a_resting_sell(api):
    client, db, sent, held, resting = api
    held["IBIT"] = 1000.0
    resting.append({ "reason": "test placement","symbol": "IBIT", "side": "sell", "qty": 600,
                    "client_order_id": "ext-1-gtc-first"})
    # 500 <= 1000 held, but only 400 are unreserved: NOT an exit.
    resp = _preflight(client, _key(db), symbol="IBIT", qty=500, limit_price=44.37)
    assert resp.status_code == 200, resp.text
    assert resp.json()["exit"]["is_exit"] is False
    assert "600" in resp.json()["exit"]["detail"]
    # 400 is exactly the unreserved remainder: an exit.
    resp = _preflight(client, _key(db), symbol="IBIT", qty=400, limit_price=44.37)
    assert resp.json()["exit"]["is_exit"] is True


def test_a_second_gtc_exit_cannot_oversell_the_first(api):
    client, db, sent, held, resting = api
    held["IBIT"] = 1000.0
    resting.append({ "reason": "test placement","symbol": "IBIT", "side": "sell", "qty": 600,
                    "client_order_id": "ext-1-gtc-first"})
    # Not exit-classified, so the normal caps refuse it (500 > the 100-qty cap).
    resp = _post(client, _key(db), symbol="IBIT", qty=500, limit_price=44.37,
                 client_order_id="second")
    assert resp.status_code == 429, resp.text
    assert sent == []


def test_a_resting_stop_counts_against_the_unreserved_qty(api):
    client, db, sent, held, resting = api
    held["IBIT"] = 1000.0
    resting.append({ "reason": "test placement","symbol": "IBIT", "side": "sell", "qty": 950,
                    "client_order_id": "idea-9-stop-ibit"})
    resp = _preflight(client, _key(db), symbol="IBIT", qty=100, limit_price=44.37)
    assert resp.json()["exit"]["is_exit"] is False
    resp = _preflight(client, _key(db), symbol="IBIT", qty=50, limit_price=44.37)
    assert resp.json()["exit"]["is_exit"] is True


def test_an_unreadable_resting_book_fails_toward_the_caps(api, monkeypatch):
    client, db, sent, held, resting = api
    held["IBIT"] = 1000.0

    def boom(path, params=None, **kw):
        raise RuntimeError("broker down")

    monkeypatch.setattr(alpaca_paper, "paper_get", boom)
    resp = _preflight(client, _key(db), symbol="IBIT", qty=100, limit_price=44.37)
    assert resp.json()["exit"]["is_exit"] is False
