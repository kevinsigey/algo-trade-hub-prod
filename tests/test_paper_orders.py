import pytest

from tradehub.portfolio import paper_orders
from tradehub.portfolio.alpaca_paper import AccountNotConnected


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise paper_orders.requests.HTTPError(f"HTTP {self.status_code}")


class Session:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.resp

    def delete(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "method": "DELETE"})
        return self.resp


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s3cr3t")


def test_disabled_by_default(keys, monkeypatch):
    monkeypatch.delenv("TRADEHUB_PAPER_ORDERS", raising=False)
    s = Session(Resp(200))
    with pytest.raises(paper_orders.OrdersDisabled):
        paper_orders.submit("GLD", 3, "buy", "idea-1-auto-20261102-GLD-open", session=s)
    assert s.calls == [] and paper_orders.orders_enabled() is False
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "yes")  # only the exact word "on" enables
    assert paper_orders.orders_enabled() is False


def test_posts_one_order_to_paper(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200, {"id": "o-1", "status": "accepted"}))
    out = paper_orders.submit("GLD", 3, "buy", "idea-1-auto-20261102-GLD-open", session=s)
    assert out["id"] == "o-1"
    call = s.calls[0]
    assert call["url"] == "https://paper-api.alpaca.markets/v2/orders"
    assert call["json"] == {"symbol": "GLD", "qty": "3", "side": "buy", "type": "market", "time_in_force": "opg",
                            "client_order_id": "idea-1-auto-20261102-GLD-open"}
    s2 = Session(Resp(200, {"id": "o-2"}))
    paper_orders.submit("SPY", 2, "sell", "c", order_type="limit", time_in_force="cls", limit_price=512.34, session=s2)
    assert s2.calls[0]["json"]["type"] == "limit" and s2.calls[0]["json"]["limit_price"] == "512.34"
    assert s2.calls[0]["json"]["time_in_force"] == "cls"


def test_refuses_other_order_kinds_and_bad_qty(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200))
    for kw in ({"order_type": "stop"}, {"time_in_force": "gtc"}, {"order_type": "limit"}):
        with pytest.raises(ValueError):
            paper_orders.submit("GLD", 1, "buy", "c", session=s, **kw)
    with pytest.raises(ValueError):
        paper_orders.submit("GLD", 0, "buy", "c", session=s)
    assert s.calls == []


def test_duplicate_client_id(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(422, {"code": 40010001, "message": "client_order_id must be unique"}))
    with pytest.raises(paper_orders.DuplicateOrder):
        paper_orders.submit("GLD", 1, "buy", "c", session=s)


def test_rejected_keys_not_connected_without_leaking(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    with pytest.raises(AccountNotConnected) as e:
        paper_orders.submit("GLD", 1, "buy", "c", session=Session(Resp(401)))
    assert "s3cr3t" not in str(e.value)


def test_other_rejection_carries_alpaca_message(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    with pytest.raises(paper_orders.OrderRejected, match="not shortable"):
        paper_orders.submit("XYZ", 1, "sell", "c", session=Session(Resp(422, {"message": "asset XYZ is not shortable"})))


def test_403_is_an_order_refusal_not_bad_keys(keys, monkeypatch):
    # Review I3: Alpaca answers 403 for insufficient buying power / wash trade; only 401 means the keys.
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    with pytest.raises(paper_orders.OrderRejected, match="insufficient buying power"):
        paper_orders.submit("GLD", 1, "buy", "c", session=Session(Resp(403, {"message": "insufficient buying power"})))
    with pytest.raises(AccountNotConnected):
        paper_orders.submit("GLD", 1, "buy", "c", session=Session(Resp(401)))



STOP_ID = "idea-3-stop-20261103-GLD-sl"


def test_stop_and_trailing_orders_only_with_a_stop_tag(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200, {"id": "o-1"}))
    paper_orders.submit("GLD", 5, "sell", STOP_ID, order_type="stop", time_in_force="gtc", stop_price=285.5,
                        session=s)
    assert s.calls[0]["json"] == {"symbol": "GLD", "qty": "5", "side": "sell", "type": "stop", "time_in_force": "gtc",
                                  "client_order_id": STOP_ID, "stop_price": "285.50"}
    paper_orders.submit("GLD", 5, "sell", "idea-3-stop-20261103-GLD-tr", order_type="trailing_stop",
                        time_in_force="gtc", trail_percent=8, session=s)
    assert s.calls[1]["json"]["trail_percent"] == "8" and s.calls[1]["json"]["type"] == "trailing_stop"
    paper_orders.submit("GLD", 5, "sell", "idea-3-stop-20261103-GLD-tp", order_type="limit", time_in_force="gtc",
                        limit_price=330, session=s)
    for bad in ({"order_type": "stop", "time_in_force": "gtc", "stop_price": 1.0},
                {"order_type": "market", "time_in_force": "gtc"}):
        with pytest.raises(ValueError):
            paper_orders.submit("GLD", 5, "sell", "idea-3-auto-20261103-GLD-open", session=s, **bad)
    with pytest.raises(ValueError):
        paper_orders.submit("GLD", 5, "sell", STOP_ID, order_type="stop", time_in_force="gtc", session=s)
    assert len(s.calls) == 3


def test_a_machine_stop_tag_is_the_second_sanctioned_protective_family(keys, monkeypatch):
    """2026-11-02: the machine API's ext-<key>-stop- tags may carry stops (the mirror
    book's door); every other ext- or plain tag still refuses a protective shape."""
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200, {"id": "o-9"}))
    paper_orders.submit("XLE", 115, "sell", "ext-1-stop-mirror-xle-20261102", order_type="stop",
                        time_in_force="gtc", stop_price=65.55, session=s)
    assert s.calls[0]["json"]["stop_price"] == "65.55" and s.calls[0]["json"]["type"] == "stop"
    for tag, kw in (("ext-1-mirror-xle", {"order_type": "stop", "time_in_force": "gtc", "stop_price": 1.0}),
                    ("ext-1-stop-mirror-xle", {"order_type": "stop", "time_in_force": "day", "stop_price": 1.0}),
                    ("ext-1-stop-mirror-xle", {"order_type": "market", "time_in_force": "gtc"}),
                    ("manual-x", {"order_type": "stop", "time_in_force": "gtc", "stop_price": 1.0})):
        with pytest.raises(ValueError):
            paper_orders.submit("XLE", 5, "sell", tag, session=s, **kw)
    assert len(s.calls) == 1


def test_cancel_only_the_hubs_own_stops(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(204))
    paper_orders.cancel("o-9", STOP_ID, session=s)
    assert s.calls == [{"url": "https://paper-api.alpaca.markets/v2/orders/o-9", "method": "DELETE"}]
    for cid in ("idea-3-auto-20261103-GLD-open", "manual-1", "", "xidea-3-stop-1"):
        with pytest.raises(ValueError):
            paper_orders.cancel("o-9", cid, session=s)
    with pytest.raises(ValueError):
        paper_orders.cancel("../account", STOP_ID, session=s)
    assert len(s.calls) == 1
    monkeypatch.delenv("TRADEHUB_PAPER_ORDERS")
    with pytest.raises(paper_orders.OrdersDisabled):
        paper_orders.cancel("o-9", STOP_ID, session=s)


def test_cancel_of_an_order_already_gone(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    with pytest.raises(paper_orders.OrderGone):
        paper_orders.cancel("o-9", STOP_ID, session=Session(Resp(422, {"message": "order is already in filled state"})))


def test_oco_take_profit_and_stop_only_as_a_protective_order(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200, {"id": "o-1"}))
    paper_orders.submit("GLD", 5, "sell", "idea-3-stop-20261103-GLD-oco", order_type="limit", time_in_force="gtc",
                        order_class="oco", take_profit_price=330, stop_price=285, session=s)
    assert s.calls[0]["json"] == {"symbol": "GLD", "qty": "5", "side": "sell", "type": "limit", "time_in_force": "gtc",
                                  "client_order_id": "idea-3-stop-20261103-GLD-oco", "order_class": "oco",
                                  "take_profit": {"limit_price": "330.00"}, "stop_loss": {"stop_price": "285.00"}}
    with pytest.raises(ValueError):
        paper_orders.submit("GLD", 5, "sell", "idea-3-auto-20261103-GLD-open", order_type="limit",
                            time_in_force="day", order_class="oco", take_profit_price=330, stop_price=285, session=s)


# ── Multi-leg orders (Kevin, 2026-11-03: verticals placed as one order) ───────────

MLEG_LEGS = [
    {"symbol": "NVDA  261204C00200000", "side": "buy", "ratio_qty": 1, "position_intent": "buy_to_open"},
    {"symbol": "NVDA  261204C00220000", "side": "sell", "ratio_qty": 1, "position_intent": "sell_to_open"},
]


def test_submit_mleg_posts_one_order_with_both_legs(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200, {"id": "mleg-1", "order_class": "mleg"}))
    out = paper_orders.submit_mleg(MLEG_LEGS, 1, 2.0, "idea-50-auto-20261103-mleg", session=s)
    assert out["id"] == "mleg-1" and len(s.calls) == 1
    body = s.calls[0]["json"]
    assert body["order_class"] == "mleg" and body["type"] == "limit" and body["time_in_force"] == "day"
    assert body["qty"] == "1" and body["limit_price"] == "2.00"
    assert [(l["symbol"], l["side"], l["position_intent"]) for l in body["legs"]] == [
        ("NVDA  261204C00200000", "buy", "buy_to_open"),
        ("NVDA  261204C00220000", "sell", "sell_to_open")]


def test_submit_mleg_validates_legs_and_switch(keys, monkeypatch):
    s = Session(Resp(200))
    with pytest.raises(ValueError):  # a stock is not a leg
        paper_orders.submit_mleg([{**MLEG_LEGS[0], "symbol": "NVDA"}, MLEG_LEGS[1]], 1, 2.0, "x", session=s)
    with pytest.raises(ValueError):  # one leg is not a spread
        paper_orders.submit_mleg(MLEG_LEGS[:1], 1, 2.0, "x", session=s)
    with pytest.raises(paper_orders.OrdersDisabled):  # the switch defaults off
        paper_orders.submit_mleg(MLEG_LEGS, 1, 2.0, "x", session=s)
    assert s.calls == []


def test_submit_mleg_rejection_carries_alpacas_reason(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(403, {"message": "account not eligible to trade uncovered option contracts"}))
    with pytest.raises(paper_orders.OrderRejected, match="uncovered"):
        paper_orders.submit_mleg(MLEG_LEGS, 1, 2.0, "x", session=s)


# ── stop-limit orders ──


def test_stop_limit_needs_both_prices(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200))
    with pytest.raises(ValueError, match="a stop-limit order needs a stop price and a limit price"):
        paper_orders.submit("GLD", 1, "buy", "c", order_type="stop_limit", time_in_force="day", stop_price=100.0, session=s)
    with pytest.raises(ValueError, match="a stop-limit order needs a stop price and a limit price"):
        paper_orders.submit("GLD", 1, "buy", "c", order_type="stop_limit", time_in_force="day", limit_price=101.0, session=s)
    s = Session(Resp(200, {"id": "o-sl"}))
    paper_orders.submit("GLD", 1, "buy", "c", order_type="stop_limit", time_in_force="day", stop_price=100.0, limit_price=101.0, session=s)
    body = s.calls[0]["json"]
    assert body["type"] == "stop_limit"
    assert body["stop_price"] == "100.00"
    assert body["limit_price"] == "101.00"


def test_stop_limit_day_allowed_with_plain_tag(keys, monkeypatch):
    """stop_limit with day tif is not protective; plain idea-N-auto tag is fine."""
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200, {"id": "o-sl2"}))
    paper_orders.submit("GLD", 1, "buy", "idea-5-auto-20261103-GLD-open", order_type="stop_limit",
                        time_in_force="day", stop_price=100.0, limit_price=101.0, session=s)
    assert s.calls[0]["json"]["type"] == "stop_limit"
    # gtc stop_limit follows protective rule
    s2 = Session(Resp(200))
    with pytest.raises(ValueError):
        paper_orders.submit("GLD", 1, "buy", "idea-5-auto-20261103-GLD-open", order_type="stop_limit",
                            time_in_force="gtc", stop_price=100.0, limit_price=101.0, session=s2)


# ── extended-hours ──


def test_extended_hours_on_day_limit_adds_flag(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200, {"id": "o-eh"}))
    paper_orders.submit("GLD", 1, "buy", "c", order_type="limit", time_in_force="day",
                        limit_price=100.0, extended_hours=True, session=s)
    body = s.calls[0]["json"]
    assert body["extended_hours"] is True
    assert body["type"] == "limit"
    assert body["time_in_force"] == "day"


def test_extended_hours_on_gtc_limit_adds_flag(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200, {"id": "o-eh2"}))
    paper_orders.submit("GLD", 1, "buy", "c", order_type="limit", time_in_force="gtc",
                        limit_price=100.0, extended_hours=True, session=s)
    body = s.calls[0]["json"]
    assert body["extended_hours"] is True
    assert body["time_in_force"] == "gtc"


def test_extended_hours_on_market_raises(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200))
    with pytest.raises(ValueError, match="extended-hours orders must be day or gtc limit orders"):
        paper_orders.submit("GLD", 1, "buy", "c", order_type="market", time_in_force="day",
                            extended_hours=True, session=s)


def test_extended_hours_on_stop_raises(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200))
    with pytest.raises(ValueError, match="extended-hours orders must be day or gtc limit orders"):
        paper_orders.submit("GLD", 1, "buy", "c", order_type="stop", time_in_force="gtc",
                            stop_price=100.0, extended_hours=True, session=s)


def test_normal_market_order_has_no_extended_hours_key(keys, monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    s = Session(Resp(200, {"id": "o-normal"}))
    paper_orders.submit("GLD", 1, "buy", "c", order_type="market", time_in_force="opg", session=s)
    body = s.calls[0]["json"]
    assert "extended_hours" not in body


# ── asset_flags / can_short ──


class AssetSession:
    def __init__(self, status, body=None):
        self.resp = Resp(status, body)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        return self.resp


def test_asset_flags_maps_json(keys, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    from tradehub.portfolio.alpaca_paper import asset_flags
    s = AssetSession(200, {"tradable": True, "shortable": True, "easy_to_borrow": True, "fractionable": False})
    flags = asset_flags("GLD", session=s)
    assert flags == {"tradable": True, "shortable": True, "easy_to_borrow": True, "fractionable": False}


def test_asset_flags_404_returns_false(keys, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    from tradehub.portfolio.alpaca_paper import asset_flags
    s = AssetSession(404, {})
    flags = asset_flags("XYZ", session=s)
    assert flags == {"tradable": False, "shortable": False, "easy_to_borrow": False, "fractionable": False}


def test_can_short_true_only_when_shortable_and_easy_to_borrow(keys, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    from tradehub.portfolio.alpaca_paper import asset_flags
    from tradehub.portfolio import paper_orders

    # Both true
    class S1:
        def get(self, url, headers=None, timeout=None):
            return Resp(200, {"shortable": True, "easy_to_borrow": True})
    assert paper_orders.can_short("GLD", session=S1()) is True

    # shortable false
    class S2:
        def get(self, url, headers=None, timeout=None):
            return Resp(200, {"shortable": False, "easy_to_borrow": True})
    assert paper_orders.can_short("GLD", session=S2()) is False

    # easy_to_borrow false
    class S3:
        def get(self, url, headers=None, timeout=None):
            return Resp(200, {"shortable": True, "easy_to_borrow": False})
    assert paper_orders.can_short("GLD", session=S3()) is False

    # 404
    class S4:
        def get(self, url, headers=None, timeout=None):
            return Resp(404, {})
    assert paper_orders.can_short("GLD", session=S4()) is False
