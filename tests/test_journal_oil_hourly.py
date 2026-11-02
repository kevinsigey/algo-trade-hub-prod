"""Tests for the hourly WTI forecaster (`oil_wti_hourly`, `wti-hourly-v1`) and
the Brent daily sibling (`oil_brent`, `brent-v1`), built 2026-11-01.

Data facts: KXWTIH settles on the close of the 1-minute candle at the top of
the hour on the Pyth WTI index (the series' own rules text); its markets
close exactly at that hour. KXBRENTD is the daily Brent series, settling on
the Pyth Brent index. Kalshi lists no Brent hourly and no 15-minute oil
series at all -- the hourly row is WTI because it is what exists.
"""

import math
from datetime import UTC, datetime, timedelta

from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engines.oil import hourly_sigma
from tradehub.journal.forecasters.oil_hourly import HourlyInputs, build_oil_hourly
from tradehub.markets import parse_market

CLOSE = datetime(2026, 11, 2, 3, 0, tzinfo=UTC)  # the 22:00 EST candle, Nov 1
NOW = CLOSE - timedelta(minutes=30)


def _lm(strike=101.39, close=CLOSE, series="KXWTIH", event="KXWTIH-26NOV0122"):
    raw = {"ticker": f"{event}-T{strike}", "event_ticker": event, "strike_type": "greater",
           "floor_strike": strike, "cap_strike": None, "open_time": "2026-11-01T04:00:00Z",
           "close_time": close.isoformat(), "title": "WTI hourly"}
    return LiveMarket(parse_market(raw), Quote(yes_bid=0.40, yes_ask=0.44, yes_bid_size=5.0, yes_ask_size=5.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def _bars(n=200, start=100.0):
    """5-minute bars ending at NOW, alternating +-0.05% steps (a real vol)."""
    out, price = [], start
    t0 = NOW - timedelta(minutes=5 * n)
    for i in range(n):
        price *= 1.0005 if i % 2 else 0.9995
        out.append((t0 + timedelta(minutes=5 * (i + 1)), price))
    return out


def test_hourly_sigma_scales_five_minute_vol_to_an_hour():
    sigma = hourly_sigma(_bars())
    assert sigma is not None and sigma > 0.10  # above the calm-tape floor
    assert hourly_sigma(_bars(10)) is None    # too few returns to claim a vol


def test_the_hourly_forecaster_freezes_inside_its_window_only():
    live = FakeLive([_lm(),
                     _lm(102.39, close=CLOSE + timedelta(hours=3)),   # too far out
                     _lm(100.39, close=CLOSE - timedelta(minutes=28))])  # 2 min to close: too late
    inputs = HourlyInputs(bars_fn=_bars)
    fc, ki = build_oil_hourly(live, lambda t: None, inputs)
    assert (fc.name, fc.version, fc.cadence) == ("oil_wti_hourly", "wti-hourly-v1", "hourly")
    assert ki.name == "kalshi_implied_oil_hourly"

    [entry] = fc.targets(NOW)
    f = fc.forecast(entry, NOW)
    assert f is not None and 0.0 < f.probability < 1.0
    assert f.payload["spot"] == _bars()[-1][1]
    # sigma for 30 minutes is sigma_hour / sqrt(2)
    assert math.isclose(f.payload["sigma"], f.payload["sigma_hour"] / math.sqrt(2), rel_tol=0.02)
