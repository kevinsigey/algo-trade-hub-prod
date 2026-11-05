from datetime import UTC, datetime, timedelta

import pytest

from tradehub.backtest.pit import Observation
from tradehub.data.hyperliquid import HyperliquidUnavailable, hyperliquid_oil_price
from tradehub.journal.forecasters.oil_hl import HL_VERSION, build_oil_hl_shadow
from tradehub.oil_live import live_price

NOW = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
UNIVERSE = [{"universe": [{"name": "xyz:BRENTOIL"}, {"name": "xyz:CL"}]},
            [{"oraclePx": "102.89", "markPx": "102.9"}, {"oraclePx": "95.25", "markPx": "95.27"}]]


class Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _Hl:
    def __init__(self, body, status=200):
        self.body, self.status = body, status
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json))
        return Response(self.status, self.body)


def test_hyperliquid_reads_the_oil_perp_oracle_with_no_key():
    s = _Hl(UNIVERSE)
    ob = hyperliquid_oil_price(NOW, session=s)
    assert ob.value == 95.25 and ob.published_at == NOW
    assert s.calls[0][1] == {"type": "metaAndAssetCtxs", "dex": "xyz"}


@pytest.mark.parametrize("body, status", [
    (UNIVERSE, 500),
    ([{"universe": [{"name": "xyz:GOLD"}]}, [{"oraclePx": "1"}]], 200),
    ([{"universe": [{"name": "xyz:CL"}]}, [{"oraclePx": None}]], 200),
    ({"unexpected": True}, 200),
    ([{"universe": [{"name": "xyz:CL"}]}, [{"oraclePx": "NaN"}]], 200),
    ([{"universe": [{"name": "xyz:CL"}]}, [{"oraclePx": "inf"}]], 200),
])
def test_hyperliquid_failures_are_unavailable_not_a_price(body, status):
    with pytest.raises(HyperliquidUnavailable):
        hyperliquid_oil_price(NOW, session=_Hl(body, status))


def test_the_hyperliquid_shadow_is_its_own_row():
    live = type("L", (), {"open_markets": lambda self, s: [], "settled_values_recent": lambda self, s, n: []})()
    fc = build_oil_hl_shadow(live, fetch=lambda t: None)[0]
    assert fc.name == "oil_wti_hourly" and fc.version == HL_VERSION == "wti-hourly-v4-hl-shadow"


def test_the_board_uses_hyperliquid_then_says_when_it_fell_back_to_the_delayed_price():
    hl = Observation("hl", 95.2, NOW)
    delayed = Observation("cl", 95.0, NOW - timedelta(minutes=11))

    def down(_now):
        raise HyperliquidUnavailable("down")
    assert live_price(NOW, lambda: delayed, lambda now: hl) == (hl, "hyperliquid")
    assert live_price(NOW, lambda: delayed, down) == (delayed, "cl=f")


def test_the_pyth_run_around_is_gone():
    from tradehub.journal.registry import FORECASTERS
    assert not [f for f in FORECASTERS if "pyth" in f.version]
