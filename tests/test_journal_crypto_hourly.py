"""Tests for the Kalshi hourly crypto forecasters (`crypto_btc_hourly` /
`crypto_eth_hourly`, `*-hourly-v1`).

Data facts (verified live 2026-11-02): KXBTC/KXETH events run hourly around
the clock (event -26NOV0218 settles 18:00 ET), ~21-31 `greater` strikes an
event at $250 steps on BTC, settling on the CF Benchmarks value
(expiration_value, e.g. 97842.55). The model is the oil-hourly clone with
sigma from trailing 120-minute 1-minute realized volatility -- preregistered
variant 2, which passed its replay gate on both series (BTC +0.0048 +-
0.0015, ETH +0.0090 +- 0.0025 paired vs persistence) after variant 1's
settled-hourly sigma tied persistence and never shipped.
"""

import math
import statistics
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from tradehub.backtest.pit import Observation
from tradehub.data.crypto_bars import crypto_bars_1m
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engines.crypto_hourly import realized_sigma
from tradehub.journal.forecasters.crypto_hourly import (
    CryptoHourlyModel,
    CryptoHourlyPersistence,
    CryptoInputs,
    build_crypto_hourly,
)
from tradehub.markets import parse_market

ET = ZoneInfo("America/New_York")
CLOSE = datetime(2026, 11, 2, 23, 0, tzinfo=UTC)   # 18:00 EST settlement hour
NOW = CLOSE - timedelta(minutes=40)                # inside the 65-minute freeze window
BTC = {"series": "KXBTC", "family": "crypto_btc_hourly", "name": "crypto_btc_hourly",
       "version": "btc-hourly-v1"}


def _lm(strike, series="KXBTC", close=CLOSE, bid=0.40, ask=0.44):
    hh = "18"
    raw = {"ticker": f"{series}-26NOV02{hh}-T{strike}", "event_ticker": f"{series}-26NOV02{hh}",
           "strike_type": "greater", "floor_strike": strike, "cap_strike": None,
           "open_time": "2026-11-02T21:30:00Z", "close_time": close.isoformat(),
           "title": "BTC hourly"}
    return LiveMarket(parse_market(raw), Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=5.0, yes_ask_size=5.0))


def _bars(symbol="BTC-USD", minutes=130, end=NOW, step_pct=0.001, start_price=100_000.0):
    """1-minute closes ending at `end`, alternating +-step_pct log returns."""
    out = []
    price = start_price
    for i in range(minutes):
        stamp = end - timedelta(minutes=minutes - 1 - i)
        if i:
            price *= math.exp(step_pct if i % 2 else -step_pct)
        out.append(Observation(f"CRYPTO:{symbol}:1m", price, stamp))
    return out


def _settled(series="KXBTC", hours=30):
    out = []
    value = 99_000.0
    start = datetime(2026, 11, 1, 12, tzinfo=ET)
    for i in range(hours):
        if i:
            value += 120.0 if i % 2 else -60.0
        dt = start + timedelta(hours=i)
        name = f"{series}-{dt.strftime('%y%b%d').upper()}{dt.hour:02d}"
        out.append(Observation(name, round(value, 2), (dt + timedelta(minutes=2)).astimezone(UTC)))
    return out


class FakeLive:
    def __init__(self, markets, settled=None):
        self.markets = markets
        self.settled = settled if settled is not None else _settled()

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]

    def settled_values_recent(self, series, max_events):
        return [o for o in self.settled if o.name.startswith(series)]

    def settled_values(self, series):
        return self.settled_values_recent(series, 0)


def _inputs(live, bars=None):
    return CryptoInputs(live, bars_fn=lambda symbol: _bars(symbol) if bars is None else bars)


def _fc(live, bars=None, coin=BTC):
    return CryptoHourlyModel(live, lambda ticker: None, _inputs(live, bars), coin)


# ---- engine: realized vol ---------------------------------------------------

def test_realized_sigma_uses_adjacent_minute_log_returns():
    bars = _bars()
    sigma = realized_sigma(bars, 60)
    rets = [0.001 if i % 2 else -0.001 for i in range(1, 120)]
    assert abs(sigma - statistics.stdev(rets) * math.sqrt(60)) < 1e-9
    # time scaling: 15 minutes prices at half the 60-minute sigma
    assert abs(realized_sigma(bars, 15) - sigma / 2) < 1e-9


def test_realized_sigma_counts_only_adjacent_pairs_and_needs_sixty():
    bars = _bars()
    gapped = [b for b in bars if not (50 <= (NOW - b.published_at).total_seconds() // 60 <= 55)]
    # 6 bars removed inside the window -> still >= 60 pairs -> a value
    assert realized_sigma(gapped, 60) is not None
    assert realized_sigma(bars[:40], 60) is None        # too few returns
    assert realized_sigma([], 60) is None


# ---- bars loader --------------------------------------------------------------

def test_bars_loader_parses_the_chart_payload_and_swallows_failures():
    t0 = 1762200000
    payload = {"chart": {"result": [{"timestamp": [t0, t0 + 60, t0 + 120],
                                      "indicators": {"quote": [{"close": [100.0, None, 101.5]}]}}]}}
    bars = crypto_bars_1m("BTC-USD", fetch=lambda symbol: payload)
    assert [b.value for b in bars] == [100.0, 101.5]
    assert crypto_bars_1m("BTC-USD", fetch=lambda symbol: 1 / 0) == []


# ---- forecaster ---------------------------------------------------------------

def test_targets_and_forecast_price_off_the_anchor_with_rv_sigma():
    fc = _fc(FakeLive([_lm(100_250.0)]))
    targets = fc.targets(NOW)
    assert [t.target for t in targets] == ["kalshi:KXBTC-26NOV0218-T100250.0"]
    assert targets[0].family == "crypto_btc_hourly" and targets[0].cadence == "hourly"
    forecast = fc.forecast(targets[0], NOW)
    bars = _bars()
    assert forecast is not None and forecast.forecaster == "crypto_btc_hourly"
    assert forecast.forecaster_version == "btc-hourly-v1"
    assert forecast.payload["live_price"] == bars[-1].value
    assert forecast.payload["minutes_to_close"] == 40.0
    assert abs(forecast.payload["sigma_price"] - bars[-1].value * forecast.payload["sigma_rel"]) < 1e-6
    assert 0.0 < forecast.probability < 1.0


def test_forecast_refuses_stale_thin_and_missing_tapes():
    stale = _fc(FakeLive([_lm(100_250.0)]), bars=_bars(end=NOW - timedelta(minutes=30)))
    assert stale.forecast(stale.targets(NOW)[0], NOW) is None
    thin = _fc(FakeLive([_lm(100_250.0)]), bars=_bars(minutes=40))
    assert thin.forecast(thin.targets(NOW)[0], NOW) is None
    missing = _fc(FakeLive([_lm(100_250.0)]), bars=[])
    assert missing.forecast(missing.targets(NOW)[0], NOW) is None


def test_persistence_anchors_on_the_last_settled_hour():
    live = FakeLive([_lm(100_250.0)])
    fc = CryptoHourlyPersistence(live, lambda ticker: None, _inputs(live), BTC)
    assert fc.name == "baseline_persistence_crypto_btc_hourly"
    forecast = fc.forecast(fc.targets(NOW)[0], NOW)
    assert forecast is not None
    assert forecast.payload["last_settlement"] == _settled()[-1].value


def test_build_registers_six_rows_and_the_registry_carries_cautious():
    names = [(f.name, f.cadence) for f in build_crypto_hourly(FakeLive([]))]
    assert names == [("crypto_btc_hourly", "hourly"), ("kalshi_implied_crypto_btc_hourly", "hourly"),
                     ("baseline_persistence_crypto_btc_hourly", "hourly"),
                     ("crypto_eth_hourly", "hourly"), ("kalshi_implied_crypto_eth_hourly", "hourly"),
                     ("baseline_persistence_crypto_eth_hourly", "hourly")]

    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    assert ("crypto_btc_hourly", "btc-hourly-v1") in keys
    assert ("crypto_eth_hourly", "eth-hourly-v1") in keys
    assert ("crypto_btc_hourly_cautious", "btc-hourly-v1+w25") in keys
    assert ("crypto_eth_hourly_cautious", "eth-hourly-v1+w25") in keys
    assert len(set(keys)) == len(keys)
