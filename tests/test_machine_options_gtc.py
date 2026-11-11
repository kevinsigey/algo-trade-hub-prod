"""Options GTC through the machine door (Kevin, 2026-11-10): the Nov 9 door
refused every non-day time-in-force for options on the premise that Alpaca
paper does not take gtc on an option order. The 2026-11-10 probe proved the
premise stale -- a single-leg GTC limit AND an mleg GTC combo were both
accepted on the big paper book with tif gtc stored, then cancelled unfilled.
So the door now admits tif "gtc" for LIMIT option orders (single-leg and
combos), namespaced into the same ext-<key>-gtc- family PR #474 opened for
share limits. Alpaca's own constraints ride along: no gtc MARKET option
orders (limit only), and opg/cls stay refused -- Alpaca paper still does not
take them on options, and nothing is silently downgraded to day.

The options exit test NETS resting option orders (the PR #474 guardrail,
extended to contracts): a close is an exit only up to the UNRESERVED held
contracts -- held minus the contracts resting option orders on the book are
already working, single-leg or mleg legs alike. Two resting closes can
therefore never each classify as an exit and together over-close a position.
"""
import requests
import pytest
from fastapi.testclient import TestClient
from workshop_fake import DB

from tradehub.api import machine_api, machine_keys, main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import alpaca_paper, options as options_mod, paper_orders

LONG_PUT = "SPY261113P00570000"        # SPY Nov 13 2026 $570 put
SHORT_PUT = "SPY261113P00565000"       # SPY Nov 13 2026 $565 put

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
        if any(s["client_order_id"] == client_order_id for s in sent + mlegs):
            raise paper_orders.DuplicateOrder(client_order_id)
        sent.append({ "reason": "test placement","symbol": symbol, "qty": qty, "side": side,
                     "client_order_id": client_order_id, **kwargs})
        return {"id": f"alpaca-{len(sent)}", "status": "accepted"}

    def fake_submit_mleg(legs, qty, limit_price, client_order_id, *,
                         book=None, time_in_force="day"):
        if any(s["client_order_id"] == client_order_id for s in sent + mlegs):
            raise paper_orders.DuplicateOrder(client_order_id)
        mlegs.append({ "reason": "test placement","legs": legs, "qty": qty, "limit_price": limit_price,
                      "client_order_id": client_order_id, "book": book,
                      "time_in_force": time_in_force})
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
    yield TestClient(main.app), db, sent, mlegs, fake_paper_get, state
    main.app.dependency_overrides.clear()


def _key(db, **caps):
    _, plaintext = machine_keys.create_key(db, "mac scripts",
                                           ["orders:place", "orders:read", "portfolio:read"], **caps)
    return {"Authorization": f"Bearer {plaintext}"}


def _single(client, headers, **over):
    body = { "reason": "test placement","symbol": LONG_PUT, "qty": 1, "side": "buy", "client_order_id": "opt-1",
            "order_type": "limit", "limit_price": 0.01, "time_in_force": "gtc"}
    body.update(over)
    return client.post("/api/v1/orders", json=body, headers=headers)


def _preflight(client, headers, **over):
    body = { "reason": "test placement","symbol": LONG_PUT, "qty": 1, "side": "buy", "client_order_id": "opt-1",
            "order_type": "limit", "limit_price": 0.01, "time_in_force": "gtc"}
    body.update(over)
    return client.post("/api/v1/orders/preflight", json=body, headers=headers)


SPREAD = [{"symbol": LONG_PUT, "side": "buy", "qty": 1},
          {"symbol": SHORT_PUT, "side": "sell", "qty": 1}]


def _combo(client, headers, legs, **over):
    body = { "reason": "test placement","client_order_id": "spread-1", "order_type": "limit", "limit_price": 0.01,
            "time_in_force": "gtc", "legs": legs}
    body.update(over)
    return client.post("/api/v1/orders", json=body, headers=headers)


# ── the door takes GTC limits, single-leg and combo ─────────────────────────

def test_a_gtc_single_leg_limit_places_in_the_gtc_family(optapi):
    client, db, sent, mlegs, _, _ = optapi
    r = _single(client, _key(db))
    assert r.status_code == 200, r.text
    assert len(sent) == 1 and mlegs == []
    order = sent[0]
    assert order["time_in_force"] == "gtc" and order["order_type"] == "limit"
    assert order["client_order_id"] == "ext-1-gtc-opt-1"
    assert r.json()["client_order_id"] == "ext-1-gtc-opt-1"


def test_a_gtc_combo_places_as_one_mleg_order_with_gtc(optapi):
    client, db, sent, mlegs, _, _ = optapi
    r = _combo(client, _key(db), SPREAD)
    assert r.status_code == 200, r.text
    assert sent == [] and len(mlegs) == 1
    placed = mlegs[0]
    assert placed["time_in_force"] == "gtc"
    assert placed["client_order_id"] == "ext-1-gtc-spread-1"
    assert placed["qty"] == 1 and placed["limit_price"] == 0.01
    body = r.json()
    assert body["net_limit_price"] == 0.01 and "debit" in body["net_price_convention"]


def test_the_preflight_plan_names_the_gtc_family(optapi):
    client, db, _, _, _, _ = optapi
    r = _preflight(client, _key(db))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True
    assert out["plan"]["children"] == [{"qty": 1, "client_order_id": "ext-1-gtc-opt-1"}]
    assert out["option"]["time_in_force"] == "gtc"


def test_a_day_option_order_still_rides_the_plain_family(optapi):
    client, db, sent, mlegs, _, _ = optapi
    r = _single(client, _key(db), time_in_force="day", limit_price=2.40)
    assert r.status_code == 200, r.text
    assert sent[0]["time_in_force"] == "day"
    assert sent[0]["client_order_id"] == "ext-1-opt-1"


# ── the refusals that stay ───────────────────────────────────────────────────

def test_a_gtc_market_option_order_is_refused(optapi):
    client, db, sent, mlegs, _, _ = optapi
    r = _single(client, _key(db), order_type="market", limit_price=None)
    assert r.status_code == 422, r.text
    assert "limit" in r.json()["detail"]
    assert sent == [] and mlegs == []


def test_opg_and_cls_stay_refused_and_the_text_no_longer_disowns_gtc(optapi):
    client, db, sent, mlegs, _, _ = optapi
    headers = _key(db)
    for tif in ("opg", "cls"):
        r = _single(client, headers, time_in_force=tif, client_order_id=f"tif-{tif}")
        assert r.status_code == 422, (tif, r.text)
        assert "good-till-cancelled" in r.json()["detail"]
    assert sent == [] and mlegs == []


def test_a_gtc_stop_option_order_is_refused(optapi):
    client, db, sent, _, _, _ = optapi
    r = _single(client, _key(db), order_type="stop", limit_price=None, stop_price=2.0)
    assert r.status_code == 422
    assert sent == []


# ── exit classification rides GTC exactly like day ───────────────────────────

def test_a_gtc_close_is_an_exit_and_consumes_no_daily_count(optapi):
    client, db, sent, mlegs, _, state = optapi
    state["positions"] = [{"symbol": LONG_PUT, "qty": "3"}]
    headers = _key(db, max_qty=2, daily_cap=1)  # 3 contracts breaks the qty cap -- unless an exit
    r = _preflight(client, headers, side="sell", qty=3, limit_price=2.40,
                   position_intent="sell_to_close")
    assert r.json()["exit"]["is_exit"] is True
    r = _single(client, headers, side="sell", qty=3, limit_price=2.40,
                position_intent="sell_to_close", client_order_id="close-gtc")
    assert r.status_code == 200, r.text
    assert sent[0]["time_in_force"] == "gtc"
    assert machine_api.placed_today(db, 1) == 0


# ── the exit test nets resting option orders ─────────────────────────────────

def test_resting_option_reserved_sums_singles_legs_and_partial_fills(monkeypatch):
    orders = [
        { "reason": "test placement","symbol": LONG_PUT, "side": "sell", "qty": "2", "filled_qty": "0",
         "status": "new", "client_order_id": "ext-1-gtc-a"},
        {"symbol": "GLD", "side": "sell", "qty": "50", "filled_qty": "0"},  # a share order: ignored
        {"symbol": LONG_PUT, "side": "buy", "qty": "1", "filled_qty": "1"},  # filled: reserves nothing
        {"order_class": "mleg", "qty": "3", "filled_qty": "1", "status": "new",
         "legs": [{"symbol": LONG_PUT, "side": "sell", "ratio_qty": "2"},
                  {"symbol": SHORT_PUT, "side": "buy", "ratio_qty": "1"}]},
    ]
    monkeypatch.setattr(alpaca_paper, "paper_get", lambda path, params=None, **kw: orders)
    reserved = machine_api.resting_option_reserved()
    # single 2 sells + mleg (3-1) parents x ratio 2 = 4 sells of LONG_PUT
    assert reserved[LONG_PUT] == {"buy": 0.0, "sell": 6.0}
    assert reserved[SHORT_PUT] == {"buy": 2.0, "sell": 0.0}
    assert "GLD" not in reserved


def test_a_resting_close_reserves_its_contracts(optapi):
    client, db, sent, mlegs, _, state = optapi
    state["positions"] = [{"symbol": LONG_PUT, "qty": "3"}]
    state["orders"] = [{ "reason": "test placement","symbol": LONG_PUT, "side": "sell", "qty": "2", "filled_qty": "0",
                        "status": "new", "client_order_id": "ext-1-gtc-first-close"}]
    headers = _key(db)
    # Day orders on purpose: the netting is TIF-independent -- it closes a
    # hole that exists for today's day closes too, not just GTC ones.
    # 2 <= 3 held, but only 1 contract is unreserved: NOT an exit.
    r = _preflight(client, headers, side="sell", qty=2, limit_price=2.40,
                   time_in_force="day", position_intent="sell_to_close")
    assert r.json()["exit"]["is_exit"] is False
    assert "reserved" in r.json()["exit"]["detail"]
    # The 1 unreserved contract still classifies.
    r = _preflight(client, headers, side="sell", qty=1, limit_price=2.40,
                   time_in_force="day", position_intent="sell_to_close")
    assert r.json()["exit"]["is_exit"] is True


def test_a_second_gtc_close_cannot_overclose_the_first(optapi):
    client, db, sent, mlegs, _, state = optapi
    state["positions"] = [{"symbol": LONG_PUT, "qty": "3"}]
    headers = _key(db, max_qty=2)
    # First close of all 3 rests as a GTC order (an exit: no caps, no daily count).
    r = _single(client, headers, side="sell", qty=3, limit_price=2.40,
                position_intent="sell_to_close", client_order_id="close-1")
    assert r.status_code == 200, r.text
    # It now rests on the book; a second close of the same contracts is no
    # longer an exit, so the caps refuse it (3 > the 2-contract cap).
    state["orders"] = [{ "reason": "test placement","symbol": LONG_PUT, "side": "sell", "qty": "3", "filled_qty": "0",
                        "status": "new", "client_order_id": "ext-1-gtc-close-1"}]
    r = _single(client, headers, side="sell", qty=3, limit_price=2.40,
                position_intent="sell_to_close", client_order_id="close-2")
    assert r.status_code == 429, r.text
    assert len(sent) == 1


def test_a_resting_mleg_close_reserves_each_leg(optapi):
    client, db, sent, mlegs, _, state = optapi
    state["positions"] = [{"symbol": LONG_PUT, "qty": "2"}, {"symbol": SHORT_PUT, "qty": "-2"}]
    state["orders"] = [{ "reason": "test placement","order_class": "mleg", "qty": "2", "filled_qty": "0", "status": "new",
                        "client_order_id": "ext-1-gtc-unwind",
                        "legs": [{"symbol": LONG_PUT, "side": "sell", "ratio_qty": "1"},
                                 {"symbol": SHORT_PUT, "side": "buy", "ratio_qty": "1"}]}]
    headers = _key(db)
    # Both legs' full holdings are already reserved by the resting unwind.
    r = _preflight(client, headers, side="sell", qty=1, limit_price=2.40,
                   time_in_force="day", position_intent="sell_to_close")
    assert r.json()["exit"]["is_exit"] is False
    r = _preflight(client, headers, symbol=SHORT_PUT, side="buy", qty=1, limit_price=1.40,
                   time_in_force="day", position_intent="buy_to_close")
    assert r.json()["exit"]["is_exit"] is False


def test_a_resting_buy_reserves_against_a_held_short(optapi):
    client, db, sent, mlegs, _, state = optapi
    state["positions"] = [{"symbol": SHORT_PUT, "qty": "-3"}]
    state["orders"] = [{ "reason": "test placement","symbol": SHORT_PUT, "side": "buy", "qty": "2", "filled_qty": "0",
                        "status": "new", "client_order_id": "ext-1-gtc-first"}]
    headers = _key(db)
    r = _preflight(client, headers, symbol=SHORT_PUT, side="buy", qty=2, limit_price=1.40,
                   time_in_force="day", position_intent="buy_to_close")
    assert r.json()["exit"]["is_exit"] is False
    r = _preflight(client, headers, symbol=SHORT_PUT, side="buy", qty=1, limit_price=1.40,
                   time_in_force="day", position_intent="buy_to_close")
    assert r.json()["exit"]["is_exit"] is True


def test_an_unreadable_resting_book_fails_toward_the_caps(optapi, monkeypatch):
    client, db, sent, mlegs, fake_paper_get, state = optapi
    state["positions"] = [{"symbol": LONG_PUT, "qty": "3"}]

    def selective_boom(path, params=None, **kw):
        if path == "/v2/orders":
            raise RuntimeError("broker down")
        return fake_paper_get(path, params, **kw)

    monkeypatch.setattr(alpaca_paper, "paper_get", selective_boom)
    r = _preflight(client, _key(db), side="sell", qty=3, limit_price=2.40,
                   time_in_force="day", position_intent="sell_to_close")
    assert r.json()["exit"]["is_exit"] is False
    assert "resting" in r.json()["exit"]["detail"]


# ── paper_orders: the mleg tif + the submit fence for option shapes ─────────

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


@pytest.fixture
def book_on(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s3cr3t")
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")


MLEG_LEGS = [{"symbol": LONG_PUT, "side": "buy", "ratio_qty": 1, "position_intent": "buy_to_open"},
             {"symbol": SHORT_PUT, "side": "sell", "ratio_qty": 1, "position_intent": "sell_to_open"}]


def test_submit_mleg_carries_gtc_under_the_gtc_tag(book_on):
    s = _Session()
    paper_orders.submit_mleg(MLEG_LEGS, 1, 0.01, "ext-2-gtc-probe",
                             time_in_force="gtc", session=s)
    assert s.calls[0]["time_in_force"] == "gtc"
    assert s.calls[0]["order_class"] == "mleg" and s.calls[0]["type"] == "limit"


def test_submit_mleg_gtc_is_refused_under_any_other_tag(book_on):
    s = _Session()
    for cid in ("ext-2-probe", "idea-50-auto-x", "manual-x"):
        with pytest.raises(ValueError, match="gtc"):
            paper_orders.submit_mleg(MLEG_LEGS, 1, 0.01, cid, time_in_force="gtc", session=s)
    assert s.calls == []


def test_submit_mleg_refuses_a_non_day_non_gtc_tif(book_on):
    s = _Session()
    with pytest.raises(ValueError, match="time in force"):
        paper_orders.submit_mleg(MLEG_LEGS, 1, 0.01, "ext-2-gtc-probe",
                                 time_in_force="opg", session=s)
    assert s.calls == []


def test_submit_mleg_day_default_is_unchanged(book_on):
    s = _Session()
    paper_orders.submit_mleg(MLEG_LEGS, 1, 0.01, "idea-50-auto-x", session=s)
    assert s.calls[0]["time_in_force"] == "day"


def test_submit_single_leg_option_gtc_needs_the_gtc_tag(book_on):
    s = _Session()
    paper_orders.submit(LONG_PUT, 1, "buy", "ext-2-gtc-probe", order_type="limit",
                        time_in_force="gtc", limit_price=0.01,
                        position_intent="buy_to_open", session=s)
    assert s.calls[0]["time_in_force"] == "gtc" and s.calls[0]["position_intent"] == "buy_to_open"
    s2 = _Session()
    with pytest.raises(ValueError, match="sanctioned"):
        paper_orders.submit(LONG_PUT, 1, "buy", "ext-2-probe", order_type="limit",
                            time_in_force="gtc", limit_price=0.01,
                            position_intent="buy_to_open", session=s2)
    assert s2.calls == []
