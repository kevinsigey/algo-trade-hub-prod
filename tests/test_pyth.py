from datetime import UTC, datetime, timedelta

import pytest

from tradehub.data.pyth import (
    PYTHOIL_ID,
    HyperliquidUnavailable,
    PythUnavailable,
    hyperliquid_oil_price,
    pyth_oil_price,
)
from tradehub.journal.forecasters.oil_pyth import HL_VERSION, VERSION, build_oil_hl_shadow, build_oil_pyth_shadow


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


def test_the_age_comes_from_the_feed_not_the_response_wrapper(monkeypatch):
    monkeypatch.setenv("PYTH_API_KEY", "abc")

    class Old:
        @staticmethod
        def post(url, json, headers, timeout):
            assert "feedUpdateTimestamp" in json["properties"]
            return Response(200, {"parsed": {"timestampUs": "1793760000000000", "priceFeeds": [
                {"priceFeedId": PYTHOIL_ID, "price": "9512345", "feedUpdateTimestamp": 1793750000000000}]}})
    assert pyth_oil_price(session=Old).published_at == datetime.fromtimestamp(1793750000, UTC)


@pytest.mark.parametrize("stamp", [None, "junk", 9999999999999999])
def test_a_missing_or_future_feed_time_is_refused(monkeypatch, stamp):
    monkeypatch.setenv("PYTH_API_KEY", "abc")

    class Bad:
        @staticmethod
        def post(url, json, headers, timeout):
            return Response(200, {"parsed": {"timestampUs": "1793760000000000", "priceFeeds": [
                {"priceFeedId": PYTHOIL_ID, "price": "9512345", "feedUpdateTimestamp": stamp}]}})
    with pytest.raises(PythUnavailable):
        pyth_oil_price(session=Bad, now=datetime.fromtimestamp(1793760000, UTC))


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
    def no_hl(_now):
        raise HyperliquidUnavailable("down")
    assert live_price(now, lambda: fresh, lambda: delayed, no_hl) == (fresh, "pyth", None)

    def refused():
        raise PythUnavailable("Pyth answered 403")
    assert live_price(now, refused, lambda: delayed, no_hl) == (delayed, "cl=f", "Pyth answered 403")
    stale = Observation("pyth", 95.1, now - timedelta(minutes=5))
    price, source, why = live_price(now, lambda: stale, lambda: delayed, no_hl)
    assert source == "cl=f" and "old" in why


# ── the free Hyperliquid feed ──

class _Hl:
    def __init__(self, body, status=200):
        self.body, self.status = body, status
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json))
        return Response(self.status, self.body)


UNIVERSE = [{"universe": [{"name": "xyz:BRENTOIL"}, {"name": "xyz:CL"}]},
            [{"oraclePx": "102.89", "markPx": "102.9"}, {"oraclePx": "95.25", "markPx": "95.27"}]]
NOW = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)


def test_hyperliquid_reads_the_oil_perp_oracle_with_no_key(monkeypatch):
    monkeypatch.delenv("PYTH_API_KEY", raising=False)
    s = _Hl(UNIVERSE)
    ob = hyperliquid_oil_price(NOW, session=s)
    assert ob.value == 95.25 and ob.published_at == NOW
    assert s.calls[0][1] == {"type": "metaAndAssetCtxs", "dex": "xyz"}


@pytest.mark.parametrize("body, status", [
    (UNIVERSE, 500),
    ([{"universe": [{"name": "xyz:GOLD"}]}, [{"oraclePx": "1"}]], 200),
    ([{"universe": [{"name": "xyz:CL"}]}, [{"oraclePx": None}]], 200),
    ({"unexpected": True}, 200),
])
def test_hyperliquid_failures_are_unavailable_not_a_price(body, status):
    with pytest.raises(HyperliquidUnavailable):
        hyperliquid_oil_price(NOW, session=_Hl(body, status))


def test_the_hyperliquid_shadow_is_its_own_row(monkeypatch):
    live = type("L", (), {"open_markets": lambda self, s: [], "settled_values_recent": lambda self, s, n: []})()
    fc = build_oil_hl_shadow(live, fetch=lambda t: None)[0]
    assert fc.name == "oil_wti_hourly" and fc.version == HL_VERSION and fc.version != VERSION


def test_the_board_prefers_pyth_then_hyperliquid_then_the_delayed_price():
    from tradehub.backtest.pit import Observation
    from tradehub.oil_live import live_price

    fresh = Observation("pyth", 95.1, NOW)
    hl = Observation("hl", 95.2, NOW)
    delayed = Observation("cl", 95.0, NOW - timedelta(minutes=11))

    def no_pyth():
        raise PythUnavailable("no API key set")

    def no_hl(now):
        raise HyperliquidUnavailable("down")
    assert live_price(NOW, lambda: fresh, lambda: delayed, lambda now: hl)[1] == "pyth"
    assert live_price(NOW, no_pyth, lambda: delayed, lambda now: hl)[:2] == (hl, "hyperliquid")
    assert live_price(NOW, no_pyth, lambda: delayed, no_hl)[:2] == (delayed, "cl=f")
