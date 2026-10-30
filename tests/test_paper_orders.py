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
