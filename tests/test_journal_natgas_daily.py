"""Tests for the Kalshi daily natural-gas forecaster (`natgas_daily`, `natgas-v1`).

Data facts (verified live 2026-11-03): KXNATGASD ("Natural Gas Daily") settles on the
Pyth NATGAS index at 5:00 PM Eastern -- settlement source "Pyth - NATGAS", events like
KXNATGASD-26NOV0417 -- with ~60 `greater` strikes an event at $0.005 steps near the
money. The model mirrors the hourly WTI construction at a daily grain: a Normal centred
on the live NG=F print with sigma = the trailing stdev of Kalshi's own settled DAILY
changes, scaled by sqrt(time-to-close / 1 day); only settlements exactly one day apart
feed the sigma, so a weekend gap never inflates it. NG=F is the anchor tape; any futures
basis against the Pyth index is the graded record's to measure, as CL=F's was for WTI.
"""

import statistics
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tradehub.backtest.pit import Observation
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engines.natgas_daily import (
    daily_changes,
    daily_sigma,
    event_time,
    natgas_prob,
    sigma_for,
)
from tradehub.journal.forecasters.natgas_daily import (
    MIN_CHANGES,
    DailyInputs,
    NatgasDaily,
    NatgasDailyPersistence,
    build_natgas_daily,
)
from tradehub.markets import parse_market

ET = ZoneInfo("America/New_York")
CLOSE = datetime(2026, 11, 4, 22, 0, tzinfo=UTC)    # the Nov 4 event settles 17:00 EST
NOW = CLOSE - timedelta(minutes=105)                 # inside the 125-minute freeze window


def _lm(strike, close=CLOSE, bid=0.40, ask=0.44):
    raw = {"ticker": f"KXNATGASD-26NOV0417-T{strike}", "event_ticker": "KXNATGASD-26NOV0417",
           "strike_type": "greater", "floor_strike": strike, "cap_strike": None,
           "open_time": "2026-11-03T22:00:00Z", "close_time": close.isoformat(),
           "title": "Natural gas daily"}
    return LiveMarket(parse_market(raw), Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=5.0, yes_ask_size=5.0))


def _settled(days=40):
    """Consecutive daily settlements ending Mon Nov 2 2026, values wandering by
    +/- 0.04 -- plus one Fri->Mon pair in the middle that must not count."""
    out = []
    value = 3.0
    start = datetime(2026, 11, 2, 17, 0, tzinfo=ET) - timedelta(days=days - 1)
    for i in range(days):
        if i:
            value += 0.04 if i % 2 else -0.03
        dt = start + timedelta(days=i)
        name = f"KXNATGASD-{dt.strftime('%y%b%d').upper()}17"
        out.append(Observation(name, round(value, 3), (dt + timedelta(minutes=5)).astimezone(UTC)))
    return out


class FakeLive:
    def __init__(self, markets, settled=None):
        self.markets = markets
        self.settled = _settled() if settled is None else settled

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]

    def settled_values_recent(self, series, max_events):
        return self.settled[-max_events:]


def _inputs(live, price=3.10, age_minutes=2):
    obs = Observation("NATGAS:NG=F:last", price, NOW - timedelta(minutes=age_minutes))
    return DailyInputs(live, price_fn=lambda: obs)


def test_event_time_reads_the_1700_eastern_settlement():
    assert event_time("KXNATGASD-26NOV0417") == datetime(2026, 11, 4, 17, 0, tzinfo=ET)


def test_daily_changes_count_only_exact_day_pairs():
    settled = _settled(10)
    fri = Observation("KXNATGASD-26OCT3017", 3.5, datetime(2026, 10, 30, 21, 5, tzinfo=UTC))
    mon = Observation("KXNATGASD-26NOV0217", 3.9, datetime(2026, 11, 2, 22, 5, tzinfo=UTC))
    changes = daily_changes(settled + [fri, mon])
    assert len(changes) == 9                      # the Fri->Mon jump is not a daily change
    assert 0.4 not in changes


def test_daily_sigma_floors_and_windows():
    assert daily_sigma([0.05] * 3) >= 0.01
    changes = [0.02] * 60 + [0.50] * 5
    assert daily_sigma(changes) == statistics.stdev(changes[-60:])


def test_sigma_scales_with_sqrt_time_to_close():
    assert sigma_for(0.08, 1440) == 0.08
    assert sigma_for(0.08, 360) == pytest.approx(0.04)
    assert sigma_for(0.08, 1) == sigma_for(0.08, 15)   # the floor: never under 15 minutes


def test_natgas_prob_prices_a_greater_strike():
    market = _lm(3.0).market
    assert natgas_prob(market, 3.0, 0.08, 1440) == pytest.approx(0.5, abs=0.02)
    assert natgas_prob(market, 3.30, 0.08, 1440) > 0.99


def test_forecaster_speaks_with_enough_history_and_a_fresh_price():
    live = FakeLive([_lm(3.0)])
    model = NatgasDaily(live, None, _inputs(live))
    targets = model.targets(NOW)
    assert len(targets) == 1
    forecast = model.forecast(targets[0], NOW)
    assert forecast is not None and 0.0 < forecast.probability < 1.0
    assert forecast.payload["changes_used"] >= MIN_CHANGES
    assert forecast.payload["sigma_d"] > 0 and forecast.payload["minutes_to_close"] == 105.0


def test_forecaster_stays_silent_on_a_stale_price_or_thin_history():
    live = FakeLive([_lm(3.0)])
    stale = NatgasDaily(live, None, _inputs(live, age_minutes=45))
    assert stale.forecast(stale.targets(NOW)[0], NOW) is None
    thin_live = FakeLive([_lm(3.0)], settled=_settled(MIN_CHANGES))
    thin = NatgasDaily(thin_live, None, _inputs(thin_live))
    assert thin.forecast(thin.targets(NOW)[0], NOW) is None


def test_persistence_uses_the_last_settled_value():
    live = FakeLive([_lm(3.0)])
    base = NatgasDailyPersistence(live, None, _inputs(live))
    forecast = base.forecast(base.targets(NOW)[0], NOW)
    assert forecast is not None
    assert forecast.payload["last_settlement"] == _settled()[-1].value


def test_build_returns_the_model_market_and_persistence_rows():
    rows = [(f.name, f.cadence) for f in build_natgas_daily(FakeLive([_lm(3.0)]))]
    assert rows == [("natgas_daily", "daily"), ("kalshi_implied_natgas_daily", "daily"),
                    ("baseline_persistence_natgas_daily", "daily")]
