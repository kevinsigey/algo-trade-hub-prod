"""Machine-cap EXIT EXEMPTION (Kevin, 2026-11-09): an order that only closes a
held position is fully exempt from the machine caps -- the 100-qty cap, the
$25k notional cap, and the 50/day count (which it does not consume).

The classification is book math computed in the shared validation layer, never
a caller flag: a shares exit is a sell whose TOTAL quantity (the group total
for a split) is no larger than the held quantity; an options exit is a package
whose every leg closes a held position (sell_to_close <= held long,
buy_to_close <= held short). An oversell, an unheld symbol, a buy, or a combo
with one opening leg is NOT an exit and runs under the caps in full. The kill
switch, the defined-risk guard and every other preflight check still run on
exits exactly as before. Preflight REPORTS the classification on every order.
"""
import requests
import pytest
from fastapi.testclient import TestClient
from workshop_fake import DB

from tradehub.api import machine_api, machine_keys, main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import alpaca_paper, options as options_mod, paper_orders


# ── shares fixture (the test_machine_api pattern, plus a held-positions stub) ──

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
    monkeypatch.setattr(machine_api, "position_qty",
                        lambda symbol, book=None: held.get(symbol, 0.0))
    # These scenarios rest no orders: the 2026-11-10 netting read sees an empty
    # book (its own tests live in test_machine_gtc_orders.py).
    monkeypatch.setattr(machine_api, "resting_reserved_qty",
                        lambda symbol, side, book=None: 0.0)
    monkeypatch.setattr(machine_api, "LIMITER", machine_api.RateLimiter())
    monkeypatch.setenv("TRADEHUB_MACHINE_ORDERS", "on")
    main.app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(main.app), db, sent, held
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


def _preflight(client, headers, **over):
    body = {"symbol": "XLE", "qty": 2, "side": "buy", "client_order_id": "run-1"}
    body.update(over)
    return client.post("/api/v1/orders/preflight", json=body, headers=headers)


def _checks(body):
    return {c["name"]: c for c in body["checks"]}


# ── the shares classification matrix ─────────────────────────────────────────

def test_preflight_classifies_a_full_exit_and_bypasses_every_cap(api):
    client, db, sent, held = api
    held["IBIT"] = 700.0
    # 684 x $100 latest = $68,400: over BOTH the 100-qty and the $25k caps.
    r = _preflight(client, _key(db), symbol="IBIT", side="sell", qty=684,
                   client_order_id="ibit-exit")
    body = r.json()
    assert body["ok"] is True and sent == []
    assert body["exit"]["is_exit"] is True
    assert body["exit"]["bypassed"] == ["max_qty", "max_notional", "daily_cap"]
    checks = _checks(body)
    assert checks["exit_classification"]["exit"] is True
    assert checks["exit_classification"]["blocking"] is False
    assert checks["max_qty"]["ok"] is True and "exit" in checks["max_qty"]["detail"]
    assert checks["daily_cap"]["ok"] is True
    # One order, not a chunked group, and it costs no daily slot.
    assert [c["qty"] for c in body["plan"]["children"]] == [684]
    assert body["headroom"]["daily_used"] == 0
    assert body["headroom"]["daily_remaining"] == 50


def test_preflight_an_oversell_is_not_an_exit_and_the_caps_apply(api):
    client, db, sent, held = api
    held["XLE"] = 700.0
    r = _preflight(client, _key(db), side="sell", qty=701)
    body = r.json()
    assert body["exit"]["is_exit"] is False
    assert body["ok"] is False
    failed = [c for c in body["checks"] if not c["ok"]]
    assert failed[0]["name"] == "max_qty"  # no partial exemption for the first 700


def test_preflight_a_sell_of_an_unheld_symbol_is_not_an_exit(api):
    client, db, sent, held = api
    r = _preflight(client, _key(db), side="sell", qty=10)  # nothing held in XLE
    body = r.json()
    assert body["exit"]["is_exit"] is False
    assert body["ok"] is True and sent == []  # a normal capped sell-to-open


def test_a_buy_is_never_an_exit(api):
    client, db, sent, held = api
    held["XLE"] = 700.0
    body = _preflight(client, _key(db), side="buy", qty=2).json()
    assert body["exit"]["is_exit"] is False
    assert body["headroom"]["daily_remaining"] == 49  # normal daily accounting


def test_a_sell_exactly_at_the_held_quantity_is_an_exit(api):
    client, db, sent, held = api
    held["XLE"] = 50.0
    body = _preflight(client, _key(db), side="sell", qty=50).json()
    assert body["exit"]["is_exit"] is True  # to zero is an exit; below zero is not


def test_unreadable_positions_mean_no_exemption(api, monkeypatch):
    client, db, sent, held = api

    def boom(symbol, book=None):
        raise RuntimeError("broker down")

    monkeypatch.setattr(machine_api, "position_qty", boom)
    body = _preflight(client, _key(db), side="sell", qty=200).json()
    assert body["exit"]["is_exit"] is False
    assert "could not be read" in body["exit"]["detail"]
    assert body["ok"] is False  # the qty cap refuses it as a normal order
    body = _preflight(client, _key(db), side="sell", qty=10, client_order_id="run-2").json()
    assert body["ok"] is True  # within caps, it is still a placeable order


def test_the_caller_exit_flag_loses_to_the_book_math(api):
    client, db, sent, held = api
    held["XLE"] = 30.0
    body = _preflight(client, _key(db), side="sell", qty=52, exit=True).json()
    assert body["exit"]["is_exit"] is False
    assert body["exit"]["claimed"] is True
    assert "math wins" in body["exit"]["detail"]
    # And the reverse: no flag at all, but the math says exit -- it is one.
    held["XLE"] = 700.0
    body = _preflight(client, _key(db), side="sell", qty=684, client_order_id="run-2").json()
    assert body["exit"]["is_exit"] is True and body["exit"]["claimed"] is None


# ── split (group) totals classify as one order's quantity ────────────────────

def test_a_split_exit_uses_the_group_total_and_places_as_one_order(api):
    client, db, sent, held = api
    held["XLE"] = 250.0
    r = _post(client, _key(db), side="sell", qty=208, split=True, client_order_id="trim")
    assert r.status_code == 200
    assert [(s["qty"], s["client_order_id"]) for s in sent] == [(208, "ext-1-trim-1")]
    assert r.json()["exit"]["is_exit"] is True
    placed = [e for e in _events(db) if e["outcome"] == "placed"]
    assert len(placed) == 1
    assert (placed[0]["detail"] or "").startswith("group:trim")
    assert machine_api.detail_marks_exit(placed[0]["detail"])
    assert machine_api.placed_today(db, 1) == 0  # the exit consumed no daily slot


def test_a_split_oversell_is_not_an_exit_and_chunks_normally(api):
    client, db, sent, held = api
    held["XLE"] = 250.0
    r = _post(client, _key(db), side="sell", qty=300, split=True, client_order_id="trim")
    assert r.status_code == 200
    assert [s["qty"] for s in sent] == [100, 100, 100]
    assert machine_api.placed_today(db, 1) == 3


# ── the daily counter: exits never move it, entries still refuse at it ──────

def test_an_exit_does_not_consume_the_daily_count(api):
    client, db, sent, held = api
    held["IBIT"] = 700.0
    headers = _key(db, daily_cap=1)
    assert _post(client, headers, client_order_id="entry-1").status_code == 200
    assert machine_api.placed_today(db, 1) == 1
    # The cap is now full -- and the exit still places.
    r = _post(client, headers, symbol="IBIT", side="sell", qty=684, client_order_id="exit-1")
    assert r.status_code == 200
    assert [s["qty"] for s in sent] == [2, 684]
    assert machine_api.placed_today(db, 1) == 1  # identical after the exit
    body = _preflight(client, headers, client_order_id="peek").json()
    assert body["headroom"]["daily_used"] == 1
    # An entry at the still-full cap refuses, exactly as before.
    r = _post(client, headers, client_order_id="entry-2")
    assert r.status_code == 429 and "daily_cap" in r.json()["detail"]


def test_the_kill_switch_still_gates_an_exit(api, monkeypatch):
    client, db, sent, held = api
    held["XLE"] = 700.0
    monkeypatch.delenv("TRADEHUB_MACHINE_ORDERS")
    body = _preflight(client, _key(db), side="sell", qty=684).json()
    assert body["ok"] is False
    assert _checks(body)["machine_switch"]["ok"] is False
    r = _post(client, _key(db), side="sell", qty=684)
    assert r.status_code == 409 and sent == []


def test_a_protective_stop_within_held_shares_is_an_exit_for_the_count(api, monkeypatch):
    client, db, sent, held = api
    held["XLE"] = 700.0
    monkeypatch.setattr(machine_api, "stop_capacity", lambda symbol, side, book=None: 700)
    r = _post(client, _key(db), side="sell", qty=684, order_type="stop",
              time_in_force="gtc", stop_price=65.55)
    assert r.status_code == 200 and len(sent) == 1
    assert r.json()["exit"]["is_exit"] is True
    assert machine_api.placed_today(db, 1) == 0


# ── the counter's marker helpers ─────────────────────────────────────────────

def test_placed_today_skips_exit_marked_rows(api):
    client, db, sent, held = api
    _key(db)
    machine_keys.record_event(db, 1, "POST /api/v1/orders", "placed",
                              detail=None, client_order_id="ext-1-a")
    machine_keys.record_event(db, 1, "POST /api/v1/orders", "placed",
                              detail="exit", client_order_id="ext-1-b")
    machine_keys.record_event(db, 1, "POST /api/v1/orders", "placed",
                              detail="group:trim; exit", client_order_id="ext-1-c-1")
    machine_keys.record_event(db, 1, "POST /api/v1/orders", "placed",
                              detail="label failed", client_order_id="ext-1-d")
    assert machine_api.placed_today(db, 1) == 2
    # Ownership still sees every placed row -- the marker only steers the count.
    assert len(machine_api.placed_events(db, 1)) == 4


def test_exit_detail_marker_round_trips():
    assert machine_api.exit_event_detail(None, True) == "exit"
    assert machine_api.exit_event_detail("label failed", True) == "label failed; exit"
    assert machine_api.exit_event_detail("group:trim", True) == "group:trim; exit"
    assert machine_api.exit_event_detail("label failed", False) == "label failed"
    assert machine_api.exit_event_detail(None, False) is None
    assert machine_api.detail_marks_exit("exit") is True
    assert machine_api.detail_marks_exit("group:trim; exit") is True
    assert machine_api.detail_marks_exit("group:exit-plan") is False
    assert machine_api.detail_marks_exit(None) is False


# ── options fixture (the test_machine_options pattern) ───────────────────────

LONG_PUT = "SPY261113P00570000"
SHORT_PUT = "SPY261113P00565000"
CONTRACTS = {LONG_PUT, SHORT_PUT}
MIDS = {LONG_PUT: 2.50, SHORT_PUT: 1.50}


def _http_error(code: int) -> requests.HTTPError:
    err = requests.HTTPError(f"HTTP {code}")
    err.response = requests.Response()
    err.response.status_code = code
    return err


@pytest.fixture
def optapi(monkeypatch):
    db = DB()
    state = {"positions": [], "orders": [],
             "account": {"buying_power": "250000", "options_buying_power": "50000"}}
    sent, mlegs = [], []

    def fake_submit(symbol, qty, side, client_order_id, **kwargs):
        sent.append({"symbol": symbol, "qty": qty, "side": side,
                     "client_order_id": client_order_id, **kwargs})
        return {"id": f"alpaca-{len(sent)}", "status": "accepted"}

    def fake_submit_mleg(legs, qty, limit_price, client_order_id, *, book=None):
        mlegs.append({"legs": legs, "qty": qty, "limit_price": limit_price,
                      "client_order_id": client_order_id, "book": book})
        return {"id": f"alpaca-mleg-{len(mlegs)}", "status": "accepted", "order_class": "mleg"}

    def fake_paper_get(path, params=None, **kw):
        if path.startswith("/v2/options/contracts/"):
            symbol = path.rsplit("/", 1)[-1]
            if symbol in CONTRACTS:
                return {"symbol": symbol, "tradable": True, "status": "active"}
            raise _http_error(404)
        if path == "/v2/account":
            return state["account"]
        if path == "/v2/positions":
            return state["positions"]
        if path == "/v2/orders":
            return state["orders"]
        return {}

    monkeypatch.setattr(alpaca_paper, "latest_price", lambda symbol: 100.0)
    monkeypatch.setattr(paper_orders, "submit", fake_submit)
    monkeypatch.setattr(paper_orders, "submit_mleg", fake_submit_mleg)
    monkeypatch.setattr(alpaca_paper, "paper_get", fake_paper_get)
    monkeypatch.setattr(options_mod, "fetch_mid", lambda symbol, **kw: MIDS.get(symbol))
    monkeypatch.setattr(machine_api, "LIMITER", machine_api.RateLimiter())
    monkeypatch.setenv("TRADEHUB_MACHINE_ORDERS", "on")
    main.app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(main.app), db, sent, mlegs, state
    main.app.dependency_overrides.clear()


def _opt_preflight(client, headers, **over):
    body = {"symbol": LONG_PUT, "qty": 1, "side": "buy", "client_order_id": "opt-1",
            "order_type": "limit", "limit_price": 2.40}
    body.update(over)
    return client.post("/api/v1/orders/preflight", json=body, headers=headers)


def test_a_single_leg_sell_to_close_is_an_exit_and_skips_the_caps(optapi):
    client, db, sent, mlegs, state = optapi
    state["positions"] = [{"symbol": LONG_PUT, "qty": "3"}]
    headers = _key(db, max_qty=2)  # 3 contracts breaks the qty cap -- unless it is an exit
    r = _opt_preflight(client, headers, side="sell", qty=3,
                       position_intent="sell_to_close")
    body = r.json()
    assert body["ok"] is True
    assert body["exit"]["is_exit"] is True
    assert body["exit"]["bypassed"] == ["max_qty", "max_notional", "daily_cap"]
    r = client.post("/api/v1/orders", json={
        "symbol": LONG_PUT, "qty": 3, "side": "sell", "client_order_id": "close-1",
        "order_type": "limit", "limit_price": 2.40,
        "position_intent": "sell_to_close"}, headers=headers)
    assert r.status_code == 200 and len(sent) == 1
    assert machine_api.placed_today(db, 1) == 0


def test_a_buy_to_close_against_a_held_short_is_an_exit(optapi):
    client, db, sent, mlegs, state = optapi
    state["positions"] = [{"symbol": SHORT_PUT, "qty": "-2"}]
    body = _opt_preflight(client, _key(db), symbol=SHORT_PUT, side="buy", qty=2,
                          position_intent="buy_to_close").json()
    assert body["exit"]["is_exit"] is True


def test_a_combo_of_only_closing_legs_is_an_exit(optapi):
    client, db, sent, mlegs, state = optapi
    state["positions"] = [{"symbol": LONG_PUT, "qty": "1"},
                          {"symbol": SHORT_PUT, "qty": "-1"}]
    legs = [{"symbol": LONG_PUT, "side": "sell", "qty": 1, "position_intent": "sell_to_close"},
            {"symbol": SHORT_PUT, "side": "buy", "qty": 1, "position_intent": "buy_to_close"}]
    body = {"client_order_id": "unwind-1", "order_type": "limit", "limit_price": -0.50,
            "legs": legs}
    r = client.post("/api/v1/orders/preflight", json=body, headers=_key(db))
    assert r.json()["exit"]["is_exit"] is True
    r = client.post("/api/v1/orders", json=body, headers=_key(db))
    assert r.status_code == 200 and len(mlegs) == 1
    assert machine_api.placed_today(db, 1) == 0  # the package consumed no daily slot


def test_a_combo_with_one_opening_leg_is_not_an_exit(optapi):
    client, db, sent, mlegs, state = optapi
    state["positions"] = [{"symbol": SHORT_PUT, "qty": "-1"}]
    legs = [{"symbol": SHORT_PUT, "side": "buy", "qty": 1, "position_intent": "buy_to_close"},
            {"symbol": LONG_PUT, "side": "buy", "qty": 2, "position_intent": "buy_to_open"}]
    body = {"client_order_id": "mixed-1", "order_type": "limit", "limit_price": 1.20,
            "legs": legs}
    r = client.post("/api/v1/orders/preflight", json=body, headers=_key(db, max_qty=1))
    body_out = r.json()
    assert body_out["exit"]["is_exit"] is False
    assert body_out["ok"] is False  # the opening leg runs under the caps in full
    failed = [c for c in body_out["checks"] if not c["ok"]]
    assert failed and failed[0]["name"] == "max_qty"


def test_sell_to_close_beyond_held_is_not_an_exit_and_defined_risk_refuses(optapi):
    client, db, sent, mlegs, state = optapi
    state["positions"] = [{"symbol": LONG_PUT, "qty": "1"}]
    body = _opt_preflight(client, _key(db), side="sell", qty=2,
                          position_intent="sell_to_close").json()
    assert body["exit"]["is_exit"] is False
    assert body["ok"] is False
    assert _checks(body)["defined_risk"]["ok"] is False  # the guard still blocks it


def test_an_options_exit_does_not_consume_the_daily_count(optapi):
    client, db, sent, mlegs, state = optapi
    state["positions"] = [{"symbol": LONG_PUT, "qty": "3"}]
    headers = _key(db, daily_cap=1)
    r = client.post("/api/v1/orders", json={
        "symbol": LONG_PUT, "qty": 1, "side": "buy", "client_order_id": "open-1",
        "order_type": "limit", "limit_price": 2.40,
        "position_intent": "buy_to_open"}, headers=headers)
    assert r.status_code == 200 and machine_api.placed_today(db, 1) == 1
    r = client.post("/api/v1/orders", json={
        "symbol": LONG_PUT, "qty": 1, "side": "sell", "client_order_id": "close-1",
        "order_type": "limit", "limit_price": 2.40,
        "position_intent": "sell_to_close"}, headers=headers)
    assert r.status_code == 200  # the full daily cap does not refuse a close
    assert machine_api.placed_today(db, 1) == 1
