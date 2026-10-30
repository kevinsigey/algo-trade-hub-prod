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
