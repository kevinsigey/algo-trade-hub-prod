import re
from pathlib import Path

import pytest

from tradehub.portfolio.alpaca_paper import AccountNotConnected, latest_spy_price, paper_get


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return self.response


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", '"k"')
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s3cr3t")


def test_missing_keys_raise_not_connected(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(AccountNotConnected):
        paper_get("/v2/account", session=FakeSession(FakeResponse(200, {})))


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_keys_raise_not_connected_without_leaking_them(keys, status):
    fake = FakeSession(FakeResponse(status))
    with pytest.raises(AccountNotConnected) as exc:
        paper_get("/v2/account", session=fake)
    assert "s3cr3t" not in str(exc.value)
    assert fake.calls[0]["url"] == "https://paper-api.alpaca.markets/v2/account"
    assert fake.calls[0]["headers"]["APCA-API-KEY-ID"] == "k"
    assert fake.calls[0]["headers"]["APCA-API-SECRET-KEY"] == "s3cr3t"


def test_ok_returns_json(keys):
    assert paper_get("/v2/positions", session=FakeSession(FakeResponse(200, [{"symbol": "GLD"}]))) == [
        {"symbol": "GLD"}
    ]


def test_latest_spy_price_reads_the_data_host(keys):
    fake = FakeSession(FakeResponse(200, {"symbol": "SPY", "trade": {"p": 512.34}}))
    assert latest_spy_price(session=fake) == 512.34
    assert fake.calls[0]["url"] == "https://data.alpaca.markets/v2/stocks/SPY/trades/latest"


def test_no_live_trading_host_anywhere_in_tradehub():
    for path in Path("tradehub").rglob("*.py"):
        assert not re.search(r"(?<!paper-)api\.alpaca\.markets", path.read_text()), path


def test_module_only_issues_gets():
    src = Path("tradehub/portfolio/alpaca_paper.py").read_text()
    assert not re.search(r"\.(post|patch|put|delete)\(", src)


def test_only_paper_orders_module_writes_to_alpaca():
    # Step 4: exactly one module may send anything but a GET to Alpaca, and it is the paper-only order path.
    # A file that can reach Alpaca names its host (or imports PAPER_BASE / the paper helpers).
    reaches = re.compile(r"alpaca\.markets|PAPER_BASE|DATA_BASE|alpaca_paper")
    writers = [p for p in Path("tradehub").rglob("*.py")
               if reaches.search(p.read_text()) and re.search(r"(?<!@app)\.(post|patch|put|delete)\(", p.read_text())]
    assert [str(p) for p in writers] == ["tradehub/portfolio/paper_orders.py"]


def test_paper_orders_posts_only_new_orders_to_the_paper_host():
    src = Path("tradehub/portfolio/paper_orders.py").read_text()
    assert len(re.findall(r"\.post\(", src)) == 1 and not re.search(r"\.(patch|put|delete)\(", src)
    assert '"/v2/orders"' in src and "PAPER_BASE" in src and "https://" not in src
