"""The production-book reader: GET-only against the public host.

The hard guard (Kevin's ruling, 2026-11-17): this code path can only
GET from production. Two pins: every request the module issues is a
GET to api.elections.kalshi.com with no credentials, and the module's
source carries no write verb at all -- a future edit that adds one
fails here before it can ship.
"""

from __future__ import annotations

import inspect
import urllib.request

from tradehub import kalshi_prod_book as pb


class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


def _capture(monkeypatch, payloads: dict[str, bytes]):
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(req)
        return _Resp(payloads[req.full_url])

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


def test_every_request_is_an_unauthenticated_get_to_production(monkeypatch):
    market_url = f"{pb.PROD_BASE}/markets/TICKER"
    book_url = f"{pb.PROD_BASE}/markets/TICKER/orderbook"
    seen = _capture(monkeypatch, {
        market_url: b'{"market": {"ticker": "TICKER", "yes_ask_dollars": "0.3800"}}',
        book_url: b'{"orderbook_fp": {"yes_dollars": [], "no_dollars": [["0.6200", "25.00"]]}}',
    })
    market = pb.read_market("TICKER")
    assert market == {"ticker": "TICKER", "yes_ask_dollars": "0.3800"}
    assert pb.read_ask_size("TICKER", "yes", 0.38) == 25
    assert len(seen) == 2
    for req in seen:
        assert req.get_method() == "GET"
        assert req.full_url.startswith("https://api.elections.kalshi.com/")
        headers = {k.lower() for k in req.headers}
        assert "authorization" not in headers
        assert "kalshi-access-key" not in headers


def test_the_module_source_has_no_write_verb():
    src = inspect.getsource(pb)
    for verb in ('method="POST"', "method='POST'", 'method="PUT"',
                 'method="DELETE"', 'method="PATCH"', ".post(", ".put(",
                 ".delete(", ".patch("):
        assert verb not in src, f"write verb found in kalshi_prod_book: {verb}"
    # One transport call in the whole module, and it never carries a
    # body: a GET with data= would be a write-shaped request against
    # the production host (Claude's #560 review).
    assert "data=" not in src
    assert src.count("urlopen(") == 1


def test_ask_size_reads_the_mirror_level():
    # The YES ask at 0.38 is priced by NO bids at 0.62; the NO ask at
    # 0.63 is priced by YES bids at 0.37.
    book = {"yes_dollars": [["0.3600", "10.00"], ["0.3700", "7.00"]],
            "no_dollars": [["0.6200", "25.00"], ["0.6100", "3.00"]]}
    import json
    payload = json.dumps({"orderbook_fp": book}).encode()

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return payload

    import urllib.request as u
    orig = u.urlopen
    u.urlopen = lambda req, timeout=None: R()
    try:
        assert pb.read_ask_size("T", "yes", 0.38) == 25
        assert pb.read_ask_size("T", "no", 0.63) == 7
        # No level priced at the mirror -> nothing on offer at that ask.
        assert pb.read_ask_size("T", "yes", 0.40) == 0
    finally:
        u.urlopen = orig


def test_unreadable_book_is_none_not_zero(monkeypatch):
    def boom(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert pb.read_market("T") is None
    assert pb.read_ask_size("T", "yes", 0.38) is None
