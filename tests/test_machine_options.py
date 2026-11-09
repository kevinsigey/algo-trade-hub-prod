"""Machine-API options placement (Kevin, 2026-11-09) + the Portfolio hand-order form.

The properties that matter: an OCC symbol (21 chars) passes the door that used to cap
symbols at 10; a combo is ONE mleg order whose per-leg quantities map onto Alpaca's
ratio_qty x parent qty WITHOUT multiplying (buy 6 / sell 3 fills 6 and 3); anything
net-short or uncovered is refused by the shared defined-risk check before submit is
called; caps run per leg and the daily cap counts a combo once; and the site's
"Place an order by hand" form runs through the same validation, so the two surfaces
cannot diverge on what is allowed.
"""
import requests
import pytest
from fastapi.testclient import TestClient
from workshop_fake import DB

from tradehub.api import admin, machine_api, machine_keys, main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import alpaca_paper, options as options_mod, paper_orders

LONG_PUT = "SPY261113P00570000"        # SPY Nov 13 2026 $570 put
SHORT_PUT = "SPY261113P00565000"       # SPY Nov 13 2026 $565 put
LONG_CALL = "SPY261113C00580000"       # SPY Nov 13 2026 $580 call
SHORT_CALL = "SPY261113C00585000"      # SPY Nov 13 2026 $585 call
OTHER_EXPIRY_PUT = "SPY261120P00570000"
UNKNOWN_OCC = "SPY261113P00400000"     # OCC-shaped, not a listed contract in the stub

CONTRACTS = {LONG_PUT, SHORT_PUT, LONG_CALL, SHORT_CALL, OTHER_EXPIRY_PUT}
MIDS = {LONG_PUT: 2.50, SHORT_PUT: 1.50, LONG_CALL: 3.00, SHORT_CALL: 2.00,
        OTHER_EXPIRY_PUT: 2.60}


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
    sent, mlegs, cancels = [], [], []

    def fake_submit(symbol, qty, side, client_order_id, **kwargs):
        if any(s["client_order_id"] == client_order_id for s in sent + mlegs):
            raise paper_orders.DuplicateOrder(client_order_id)
        sent.append({"symbol": symbol, "qty": qty, "side": side,
                     "client_order_id": client_order_id, **kwargs})
        return {"id": f"alpaca-{len(sent)}", "status": "accepted"}

    def fake_submit_mleg(legs, qty, limit_price, client_order_id, *, book=None):
        if any(s["client_order_id"] == client_order_id for s in sent + mlegs):
            raise paper_orders.DuplicateOrder(client_order_id)
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
    monkeypatch.setattr(paper_orders, "cancel_machine_order",
                        lambda order_id, cid, **kw: cancels.append((order_id, cid)))
    monkeypatch.setattr(alpaca_paper, "paper_get", fake_paper_get)
    monkeypatch.setattr(options_mod, "fetch_mid", lambda symbol, **kw: MIDS.get(symbol))
    monkeypatch.setattr(machine_api, "LIMITER", machine_api.RateLimiter())
    monkeypatch.setenv("TRADEHUB_MACHINE_ORDERS", "on")
    main.app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(main.app), db, sent, mlegs, cancels, state
    main.app.dependency_overrides.clear()


@pytest.fixture
def formapi(optapi):
    client, db, sent, mlegs, cancels, state = optapi
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    yield client, sent, mlegs, state
    main.app.dependency_overrides.pop(admin.require_admin, None)


def _key(db, scopes=("orders:place", "orders:read", "portfolio:read"), **caps):
    _, plaintext = machine_keys.create_key(db, "mac scripts", list(scopes), **caps)
    return {"Authorization": f"Bearer {plaintext}"}


def _events(db, key_id=1):
    return [e for e in db.db.get(machine_keys.EVENTS, []) if e["key_id"] == key_id]


def _single(client, headers, **over):
    body = {"symbol": LONG_PUT, "qty": 1, "side": "buy", "client_order_id": "opt-1",
            "order_type": "limit", "limit_price": 2.40}
    body.update(over)
    return client.post("/api/v1/orders", json=body, headers=headers)


def _combo(client, headers, legs, **over):
    body = {"client_order_id": "spread-1", "order_type": "limit", "limit_price": 1.20,
            "legs": legs}
    body.update(over)
    return client.post("/api/v1/orders", json=body, headers=headers)


SPREAD = [{"symbol": LONG_PUT, "side": "buy", "qty": 1},
          {"symbol": SHORT_PUT, "side": "sell", "qty": 1}]


# ── requirement 1: OCC symbols pass validation, garbage does not ─────────────────

def test_occ_single_leg_limit_places_with_open_intent(optapi):
    client, db, sent, mlegs, _, _ = optapi
    r = _single(client, _key(db), qty=2)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["client_order_id"] == "ext-1-opt-1"
    assert body["position_intent"] == "buy_to_open"
    assert sent == [{"symbol": LONG_PUT, "qty": 2, "side": "buy",
                     "client_order_id": "ext-1-opt-1", "order_type": "limit",
                     "time_in_force": "day", "limit_price": 2.40, "book": "main",
                     "position_intent": "buy_to_open"}]
    assert mlegs == []


def test_garbage_long_symbols_are_refused(optapi):
    client, db, sent, mlegs, _, _ = optapi
    headers = _key(db)
    for symbol in ("SPY261113X00045000", "SPY261113P0004500", "NOTACONTRACTATALL123"):
        r = _single(client, headers, symbol=symbol, client_order_id=f"g-{symbol[:4]}")
        assert r.status_code == 422, (symbol, r.text)
    assert sent == [] and mlegs == []


def test_an_unlisted_contract_is_refused(optapi):
    client, db, sent, _, _, _ = optapi
    r = _single(client, _key(db), symbol=UNKNOWN_OCC)
    assert r.status_code == 422 and "contract" in r.json()["detail"]
    assert sent == []


# ── requirement 2: single-leg shapes, intents, TIF honesty ───────────────────────

def test_single_leg_market_option_places_priced_at_the_mid(optapi):
    client, db, sent, _, _, _ = optapi
    r = _single(client, _key(db), order_type="market", limit_price=None, qty=2)
    assert r.status_code == 200, r.text
    assert sent[0]["order_type"] == "market" and sent[0]["limit_price"] is None


def test_opg_and_cls_are_refused_for_options_never_downgraded(optapi):
    client, db, sent, _, _, _ = optapi
    headers = _key(db)
    for tif in ("opg", "cls", "gtc"):
        r = _single(client, headers, time_in_force=tif, client_order_id=f"tif-{tif}")
        assert r.status_code == 422, (tif, r.text)
        assert "day" in r.json()["detail"]
    assert sent == []


def test_a_stop_option_order_is_refused(optapi):
    client, db, sent, _, _, _ = optapi
    r = _single(client, _key(db), order_type="stop", limit_price=None, stop_price=2.0,
                time_in_force="gtc")
    assert r.status_code == 422
    assert sent == []


# ── requirement 5 (defined risk): naked shorts never place ──────────────────────

def test_a_naked_single_leg_short_is_refused(optapi):
    client, db, sent, _, _, _ = optapi
    r = _single(client, _key(db), side="sell")
    assert r.status_code == 422 and "naked" in r.json()["detail"]
    assert sent == []


def test_sell_to_close_beyond_the_held_contracts_is_refused(optapi):
    client, db, sent, _, _, state = optapi
    state["positions"] = [{"symbol": LONG_PUT, "qty": "1"}]
    headers = _key(db)
    r = _single(client, headers, side="sell", qty=2, position_intent="sell_to_close")
    assert r.status_code == 422 and sent == []
    ok = _single(client, headers, side="sell", qty=1, position_intent="sell_to_close",
                 client_order_id="opt-close")
    assert ok.status_code == 200, ok.text
    assert sent[0]["position_intent"] == "sell_to_close"


def test_sell_to_open_covered_by_a_held_long_is_allowed(optapi):
    client, db, sent, _, _, state = optapi
    state["positions"] = [{"symbol": LONG_CALL, "qty": "2"}]
    r = _single(client, _key(db), symbol=SHORT_CALL, side="sell", qty=2, limit_price=1.90)
    assert r.status_code == 200, r.text
    assert sent[0]["position_intent"] == "sell_to_open"


def test_buying_power_is_checked_against_max_loss(optapi):
    client, db, sent, _, _, state = optapi
    state["account"] = {"buying_power": "250000", "options_buying_power": "100"}
    r = _combo(client, _key(db), SPREAD)  # max loss = the $120 net debit
    assert r.status_code == 422 and "buying power" in r.json()["detail"]


# ── requirement 3: combos are one mleg order, ratios never multiply ─────────────

def test_a_combo_places_as_one_mleg_order(optapi):
    client, db, sent, mlegs, _, _ = optapi
    r = _combo(client, _key(db), SPREAD)
    assert r.status_code == 200, r.text
    assert sent == [] and len(mlegs) == 1
    placed = mlegs[0]
    assert placed["qty"] == 1 and placed["limit_price"] == 1.20
    assert placed["client_order_id"] == "ext-1-spread-1"
    assert [(l["symbol"], l["side"], l["ratio_qty"], l["position_intent"]) for l in placed["legs"]] == [
        (LONG_PUT, "buy", 1, "buy_to_open"), (SHORT_PUT, "sell", 1, "sell_to_open")]
    body = r.json()
    assert body["net_limit_price"] == 1.20 and "debit" in body["net_price_convention"]
    assert [e["outcome"] for e in _events(db)][-1] == "placed"


def test_the_ratio_form_maps_onto_parent_and_ratios(optapi):
    client, db, _, mlegs, _, _ = optapi
    legs = [{"symbol": LONG_PUT, "side": "buy", "qty": 6},
            {"symbol": SHORT_PUT, "side": "sell", "qty": 3}]
    r = _combo(client, _key(db), legs)
    assert r.status_code == 200, r.text
    placed = mlegs[0]
    # parent 3 x ratios 2/1 fills 6 and 3 -- never 18/9 or 36/18.
    assert placed["qty"] == 3
    assert [l["ratio_qty"] for l in placed["legs"]] == [2, 1]
    expected = {e["symbol"]: e["qty"] for e in r.json()["legs"]}
    assert expected == {LONG_PUT: 6, SHORT_PUT: 3}


def test_a_two_to_one_ratio_uses_parent_one(optapi):
    client, db, _, mlegs, _, _ = optapi
    legs = [{"symbol": LONG_PUT, "side": "buy", "qty": 2},
            {"symbol": SHORT_PUT, "side": "sell", "qty": 1}]
    r = _combo(client, _key(db), legs, client_order_id="spread-21")
    assert r.status_code == 200, r.text
    assert mlegs[0]["qty"] == 1 and [l["ratio_qty"] for l in mlegs[0]["legs"]] == [2, 1]


def test_a_net_short_combo_is_refused(optapi):
    client, db, _, mlegs, _, _ = optapi
    legs = [{"symbol": SHORT_PUT, "side": "sell", "qty": 2},
            {"symbol": LONG_PUT, "side": "buy", "qty": 1}]
    r = _combo(client, _key(db), legs)
    assert r.status_code == 422 and "naked" in r.json()["detail"]
    assert mlegs == []


def test_a_credit_combo_takes_a_negative_net_limit(optapi):
    client, db, _, mlegs, _, _ = optapi
    legs = [{"symbol": LONG_PUT, "side": "sell", "qty": 1},
            {"symbol": SHORT_PUT, "side": "buy", "qty": 1}]
    r = _combo(client, _key(db), legs, limit_price=-0.85, client_order_id="credit-1")
    assert r.status_code == 200, r.text
    assert mlegs[0]["limit_price"] == -0.85


def test_combo_shape_refusals(optapi):
    client, db, _, mlegs, _, _ = optapi
    headers = _key(db)
    mixed = [{"symbol": LONG_PUT, "side": "buy", "qty": 1},
             {"symbol": OTHER_EXPIRY_PUT, "side": "sell", "qty": 1}]
    assert _combo(client, headers, mixed, client_order_id="mix-1").status_code == 422
    assert _combo(client, headers, SPREAD, order_type="market", limit_price=None,
                  client_order_id="mkt-1").status_code == 422
    assert _combo(client, headers, SPREAD[:1], client_order_id="one-1").status_code == 422
    assert _combo(client, headers, SPREAD, split=True, client_order_id="spl-1").status_code == 422
    assert mlegs == []


# ── requirement 5 (caps): per leg, and the daily cap counts a combo once ────────

def test_per_leg_caps_apply_to_options(optapi):
    client, db, sent, mlegs, _, _ = optapi
    headers = _key(db)
    r = _single(client, headers, qty=101)
    assert r.status_code == 429 and "max_qty" in r.json()["detail"]
    # Priced at the mid (a market order): mid 2.50 x 100 contracts x $100 = $25,000
    # sits at the cap; a $3.00 mid breaks it.
    MIDS[LONG_PUT] = 3.00
    try:
        r = _single(client, headers, qty=100, order_type="market", limit_price=None,
                    client_order_id="opt-big")
        assert r.status_code == 429 and "max_notional" in r.json()["detail"]
        legs = [{"symbol": LONG_PUT, "side": "buy", "qty": 101},
                {"symbol": SHORT_PUT, "side": "sell", "qty": 101}]
        assert _combo(client, headers, legs, client_order_id="leg-big").status_code == 429
    finally:
        MIDS[LONG_PUT] = 2.50
    assert sent == [] and mlegs == []


def test_the_daily_cap_counts_a_combo_once(optapi):
    client, db, _, _, _, _ = optapi
    headers = _key(db, daily_cap=1)
    assert _combo(client, headers, SPREAD).status_code == 200
    r = client.post("/api/v1/orders", headers=headers, json={
        "symbol": "XLE", "qty": 1, "side": "buy", "client_order_id": "share-1"})
    assert r.status_code == 429 and "daily_cap" in r.json()["detail"]


def test_the_kill_switch_still_refuses_option_orders(optapi, monkeypatch):
    client, db, sent, mlegs, _, _ = optapi
    monkeypatch.setenv("TRADEHUB_MACHINE_ORDERS", "off")
    assert _single(client, _key(db)).status_code == 409
    assert sent == [] and mlegs == []


# ── requirements 4, 6, 7: read-back, tags, cancel ────────────────────────────────

MLEG_BROKER = {"id": "alpaca-mleg-1", "client_order_id": "ext-1-spread-1",
               "order_class": "mleg", "symbol": None, "side": None, "type": "limit",
               "time_in_force": "day", "qty": "3", "filled_qty": "3",
               "limit_price": "1.20", "status": "filled",
               "submitted_at": "2026-11-09T15:00:00Z", "filled_avg_price": "1.10",
               "legs": [
                   {"symbol": LONG_PUT, "side": "buy", "ratio_qty": "2",
                    "position_intent": "buy_to_open", "status": "filled",
                    "filled_qty": "6", "filled_avg_price": "2.30"},
                   {"symbol": SHORT_PUT, "side": "sell", "ratio_qty": "1",
                    "position_intent": "sell_to_open", "status": "filled",
                    "filled_qty": "3", "filled_avg_price": "3.50"}]}


def test_combo_read_back_shows_per_leg_fills_net_price_and_tag(optapi):
    client, db, _, _, _, state = optapi
    headers = _key(db)
    legs = [{"symbol": LONG_PUT, "side": "buy", "qty": 6},
            {"symbol": SHORT_PUT, "side": "sell", "qty": 3}]
    assert _combo(client, headers, legs, tag="crwv-fcc").status_code == 200
    state["orders"] = [MLEG_BROKER]
    r = client.get("/api/v1/orders/spread-1", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tag"] == "crwv-fcc"
    assert body["net_fill_price"] == 1.10
    fills = {l["symbol"]: (l["filled_qty"], l["filled_avg_price"]) for l in body["legs"]}
    assert fills == {LONG_PUT: (6.0, 2.30), SHORT_PUT: (3.0, 3.50)}
    expected = {e["symbol"]: e["qty"] for e in body["expected_leg_fills"]}
    assert expected == {LONG_PUT: 6, SHORT_PUT: 3}
    assert body["leg_state"] == "complete"


def test_cancel_by_caller_id_cancels_the_whole_combo(optapi):
    client, db, _, _, cancels, state = optapi
    headers = _key(db)
    assert _combo(client, headers, SPREAD).status_code == 200
    state["orders"] = [{**MLEG_BROKER, "id": "alpaca-mleg-9", "status": "new",
                        "filled_qty": "0", "filled_avg_price": None,
                        "legs": [{**l, "status": "new", "filled_qty": "0",
                                  "filled_avg_price": None} for l in MLEG_BROKER["legs"]]}]
    r = client.delete("/api/v1/orders/spread-1", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert cancels == [("alpaca-mleg-9", "ext-1-spread-1")]


def test_open_orders_surface_occ_rows_attributed_to_the_combo(optapi):
    client, db, _, _, _, state = optapi
    headers = _key(db)
    assert _combo(client, headers, SPREAD).status_code == 200
    state["orders"] = [{**MLEG_BROKER, "status": "new", "filled_qty": "0",
                        "filled_avg_price": None}]
    r = client.get("/api/v1/orders/open", headers=headers)
    assert r.status_code == 200
    combo = [o for o in r.json()["orders"] if o["client_order_id"] == "ext-1-spread-1"]
    assert len(combo) == 1 and combo[0]["legs"][0]["symbol"] == LONG_PUT


# ── requirement 5 (preflight): the dry run states the defined-risk math ─────────

def test_preflight_states_max_loss_headroom_and_the_convention(optapi):
    client, db, _, _, _, _ = optapi
    headers = _key(db)
    body = {"client_order_id": "spread-1", "order_type": "limit", "limit_price": 1.20,
            "legs": SPREAD}
    r = client.post("/api/v1/orders/preflight", json=body, headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True
    checks = {c["name"]: c for c in out["checks"]}
    assert checks["defined_risk"]["ok"] is True and checks["contract"]["ok"] is True
    assert out["option"]["max_loss"] == 120.0
    assert out["option"]["net_price_convention"].startswith("net limit price")
    assert out["headroom"]["daily_remaining"] == 49
    assert out["plan"]["children"] == [{"qty": 1, "client_order_id": "ext-1-spread-1"}]


def test_preflight_refuses_a_naked_short_without_placing(optapi):
    client, db, sent, mlegs, _, _ = optapi
    headers = _key(db)
    body = {"symbol": LONG_PUT, "qty": 1, "side": "sell", "client_order_id": "opt-1",
            "order_type": "limit", "limit_price": 2.40}
    r = client.post("/api/v1/orders/preflight", json=body, headers=headers)
    assert r.status_code == 200 and r.json()["ok"] is False
    checks = {c["name"]: c for c in r.json()["checks"]}
    assert checks["defined_risk"]["ok"] is False
    assert sent == [] and mlegs == []


# ── paper_orders.submit: intent rides single-leg orders only ─────────────────────

class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {"id": "alpaca-1", "status": "accepted"}

    def json(self):
        return self._body


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(json)
        return _Resp()


def test_submit_carries_position_intent_only_when_asked(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s3cr3t")
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = _Session()
    paper_orders.submit(LONG_PUT, 1, "buy", "manual-x", order_type="limit",
                        time_in_force="day", limit_price=2.4,
                        position_intent="buy_to_open", session=s)
    assert s.calls[0]["position_intent"] == "buy_to_open"
    s2 = _Session()
    paper_orders.submit("XLE", 1, "buy", "manual-y", order_type="market",
                        time_in_force="day", session=s2)
    assert "position_intent" not in s2.calls[0]  # the share body is byte-identical


# ── the form path: same validation, same defined-risk guard ─────────────────────

def _form(client, **over):
    body = {"symbol": LONG_PUT, "qty": 1, "side": "buy", "order_type": "limit",
            "limit_price": 2.40, "time_in_force": "day"}
    body.update(over)
    return client.post("/api/portfolio/orders", json=body)


def test_the_form_accepts_an_occ_single_leg(formapi):
    client, sent, _, _ = formapi
    r = _form(client)
    assert r.status_code == 200, r.text
    assert sent[0]["symbol"] == LONG_PUT and sent[0]["position_intent"] == "buy_to_open"
    assert sent[0]["time_in_force"] == "day" and sent[0]["book"] == "main"


def test_the_form_refuses_a_naked_short(formapi):
    client, sent, mlegs, _ = formapi
    r = _form(client, side="sell")
    assert r.status_code == 422 and "naked" in r.json()["detail"]
    assert sent == [] and mlegs == []


def test_the_form_refuses_opg_for_an_option(formapi):
    client, sent, _, _ = formapi
    r = _form(client, time_in_force="opg")
    assert r.status_code == 422 and "day" in r.json()["detail"]
    assert sent == []


def test_the_form_places_a_combo_as_one_mleg(formapi):
    client, _, mlegs, _ = formapi
    r = client.post("/api/portfolio/orders", json={
        "order_type": "limit", "limit_price": 0.90, "time_in_force": "day",
        "legs": [{"symbol": LONG_PUT, "side": "buy", "qty": 2},
                 {"symbol": SHORT_PUT, "side": "sell", "qty": 1}]})
    assert r.status_code == 200, r.text
    assert len(mlegs) == 1 and mlegs[0]["qty"] == 1
    assert [l["ratio_qty"] for l in mlegs[0]["legs"]] == [2, 1]
    assert r.json()["client_order_id"].startswith("manual-")
