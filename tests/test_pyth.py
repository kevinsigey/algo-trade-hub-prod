from datetime import UTC, datetime, timedelta

import pytest

from tradehub.data.pyth import PYTHOIL_ID, PythUnavailable, pyth_oil_price
from tradehub.journal.forecasters.oil_pyth import VERSION, build_oil_pyth_shadow


class Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def session(status=200, price="9512345", us=1793760000000000):
    calls = []

    class S:
        @staticmethod
        def post(url, json, headers, timeout):
            calls.append((url, json, headers, timeout))
            return Response(status, {"parsed": {"timestampUs": str(us),
                                                "priceFeeds": [{"priceFeedId": PYTHOIL_ID, "price": price,
                                                                "feedUpdateTimestamp": us}]}})
    S.calls = calls
    return S


def test_reads_the_settlement_feed_with_the_key_as_a_bearer_token(monkeypatch):
    monkeypatch.setenv("PYTH_API_KEY", "abc")
    s = session()
    ob = pyth_oil_price(session=s)
    assert ob.value == pytest.approx(95.12345) and ob.published_at == datetime.fromtimestamp(1793760000, UTC)
    url, body, headers, _ = s.calls[0]
    assert url.endswith("/v1/latest_price") and body["priceFeedIds"] == [3063] and headers["Authorization"] == "Bearer abc"


def test_no_key_says_so_without_calling_out(monkeypatch):
    monkeypatch.delenv("PYTH_API_KEY", raising=False)
    s = session()
    with pytest.raises(PythUnavailable, match="no API key"):
        pyth_oil_price(session=s)
    assert s.calls == []


@pytest.mark.parametrize("status", [401, 403, 500])
def test_a_refused_call_names_the_status_and_never_the_key(monkeypatch, status):
    monkeypatch.setenv("PYTH_API_KEY", "supersecret")
    with pytest.raises(PythUnavailable) as err:
        pyth_oil_price(session=session(status=status))
    assert str(status) in str(err.value) and "supersecret" not in str(err.value)


@pytest.mark.parametrize("price", ["0", "not-a-number", None])
def test_a_nonsense_price_is_refused_not_used(monkeypatch, price):
    monkeypatch.setenv("PYTH_API_KEY", "abc")
    with pytest.raises(PythUnavailable):
        pyth_oil_price(session=session(price=price))


def test_the_shadow_is_a_separate_row_and_a_dead_feed_is_a_gap(monkeypatch):
    live = type("L", (), {"open_markets": lambda self, s: [], "settled_values_recent": lambda self, s, n: []})()
    fc = build_oil_pyth_shadow(live, fetch=lambda t: None)[0]
    assert fc.name == "oil_wti_hourly" and fc.version == VERSION and "pyth" in VERSION
    monkeypatch.delenv("PYTH_API_KEY", raising=False)
    assert fc._inputs._price_fn() is None  # no key: no anchor, so the row is a gap and never a stale price


def test_the_live_ladder_says_which_price_it_used(monkeypatch):
    from tradehub.backtest.pit import Observation
    from tradehub.oil_live import live_price

    now = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
    fresh = Observation("pyth", 95.1, now - timedelta(seconds=1))
    delayed = Observation("cl", 95.0, now - timedelta(minutes=11))
    assert live_price(now, lambda: fresh, lambda: delayed) == (fresh, "pyth", None)

    def refused():
        raise PythUnavailable("Pyth answered 403")
    assert live_price(now, refused, lambda: delayed) == (delayed, "cl=f", "Pyth answered 403")
    stale = Observation("pyth", 95.1, now - timedelta(minutes=5))
    price, source, why = live_price(now, lambda: stale, lambda: delayed)
    assert source == "cl=f" and "old" in why
