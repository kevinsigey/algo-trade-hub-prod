"""The 15-minute direction model (Kevin, 2026-11-04): KXWTI15M / KXBRENT15M /
KXNATGAS15M shadows. The contract is a single up/down per window (YES iff the
settlement candle closes at or above the window open); the model is the
drift-scaled random walk on Hyperliquid 1-minute candles, preregistered in
engines/fifteen_min.py. Strictness: no open candle, a stale tape, or a thin
sigma tape means no forecast -- never a swapped method.
"""
import math
from datetime import UTC, datetime, timedelta

import pytest

from tradehub.data.kalshi_live import LiveMarket
from tradehub.data.pyth import HyperliquidUnavailable, hyperliquid_candles
from tradehub.edges import Quote
from tradehub.engines.fifteen_min import SIGMA_FLOOR, prob_up, realized_sigma_1m
from tradehub.journal.forecasters.fifteen_min import FifteenMinInputs, build_fifteen_min
from tradehub.markets import KalshiMarket

T0 = datetime(2026, 11, 4, 5, 15, tzinfo=UTC)  # a window open


# ── the engine ────────────────────────────────────────────────────────────────

def test_no_move_is_a_coin_flip():
    assert prob_up(100.0, 100.0, 0.001, 10.0) == pytest.approx(0.5)


def test_a_move_up_prices_above_a_half_and_time_decays_it():
    soon = prob_up(100.0, 100.10, 0.001, 2.0)
    later = prob_up(100.0, 100.10, 0.001, 12.0)
    assert 0.5 < later < soon < 1.0
    assert prob_up(100.0, 99.90, 0.001, 2.0) < 0.5


def test_sigma_needs_a_real_tape_and_floors_on_a_flat_one():
    assert realized_sigma_1m([100.0] * 10) is None
    assert realized_sigma_1m([100.0] * 60) == SIGMA_FLOOR


# ── the Hyperliquid candle pull ───────────────────────────────────────────────

class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def test_candles_parse_to_open_time_and_close():
    rows = [{"t": 1793760000000, "c": "96.10"}, {"t": 1793759940000, "c": "96.00"}]

    class S:
        @staticmethod
        def post(url, json, timeout):
            assert json["req"]["coin"] == "xyz:CL" and json["req"]["interval"] == "1m"
            return _Resp(200, rows)
    out = hyperliquid_candles("xyz:CL", T0, T0 + timedelta(minutes=5), session=S)
    assert [v for _t, v in out] == [96.00, 96.10]  # sorted oldest first

    class Bad:
        @staticmethod
        def post(url, json, timeout):
            return _Resp(200, [{"nope": 1}])
    with pytest.raises(HyperliquidUnavailable):
        hyperliquid_candles("xyz:CL", T0, T0 + timedelta(minutes=5), session=Bad)


# ── the forecaster ────────────────────────────────────────────────────────────

def _market(close_time):
    return LiveMarket(
        market=KalshiMarket(ticker="KXWTI15M-26NOV040030-30", event_ticker="KXWTI15M-26NOV040030",
                            series_ticker="KXWTI15M", strike_type="greater_or_equal",
                            floor_strike=None, cap_strike=None,
                            open_time=close_time - timedelta(minutes=15), close_time=close_time,
                            title="WTI Oil price up in next 15 mins?"),
        quote=Quote(yes_bid=0.48, yes_ask=0.52, yes_bid_size=10.0, yes_ask_size=10.0))


class _Live:
    def __init__(self, markets):
        self._markets = markets

    def open_markets(self, series):
        return self._markets


def _tape(open_price=100.0, drift=0.30, minutes=150):
    """1-minute candles ending at T0+20m: noisy around 100, the candle closing
    at the window open (T0) is exactly open_price, then a drift into T0+5."""
    start = T0 - timedelta(minutes=minutes)
    out = []
    for i in range(minutes + 21):
        t = start + timedelta(minutes=i)
        base = 100.0 + 0.04 * math.sin(i * 1.7)
        if t == T0 - timedelta(minutes=1):
            base = open_price
        if t >= T0:
            base = open_price + drift * ((t - T0).total_seconds() / 300.0) + 0.01 * math.sin(i)
        out.append((t, round(base, 4)))
    return out


def _model(now, tape=None):
    live = _Live([_market(T0 + timedelta(minutes=15))])
    inputs = FifteenMinInputs(candles_fn=lambda coin, s, e: tape if tape is not None else _tape())
    models = [f for f in build_fifteen_min(live, inputs=inputs) if f.name == "oil_wti_15m"]
    return models[0]


def test_targets_only_inside_the_freeze_band():
    model = _model(T0)
    assert model.targets(T0 + timedelta(minutes=0.5)) == []
    assert len(model.targets(T0 + timedelta(minutes=5))) == 1
    assert model.targets(T0 + timedelta(minutes=14)) == []


def test_a_forecast_reads_the_open_candle_and_the_move():
    now = T0 + timedelta(minutes=5)
    model = _model(now)
    entry = model.targets(now)[0]
    fc = model.forecast(entry, now)
    assert fc is not None and 0.5 < fc.probability < 1.0
    assert fc.payload["open_price"] == 100.0
    assert fc.payload["remaining_min"] == 10.0 and fc.payload["elapsed_min"] == 5.0
    assert fc.payload["feed"] == "xyz:CL" and fc.market_prob == pytest.approx(0.50)


def test_no_open_candle_no_forecast():
    tape = [c for c in _tape() if c[0] != T0 - timedelta(minutes=1)]
    now = T0 + timedelta(minutes=5)
    model = _model(now, tape=tape)
    entry = model.targets(now)[0]
    assert model.forecast(entry, now) is None


def test_the_build_covers_all_three_series_and_their_market_rows():
    built = build_fifteen_min(_Live([]), inputs=FifteenMinInputs(candles_fn=lambda c, s, e: []))
    assert {f.name for f in built} == {
        "oil_wti_15m", "oil_brent_15m", "natgas_15m",
        "kalshi_implied_oil_wti_15m", "kalshi_implied_oil_brent_15m", "kalshi_implied_natgas_15m"}
    assert all(f.cadence == "15min" for f in built if hasattr(f, "cadence"))
