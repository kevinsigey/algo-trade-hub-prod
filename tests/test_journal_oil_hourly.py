"""Tests for the Kalshi hourly WTI forecaster (`oil_wti_hourly`, `wti-hourly-v1`).

Data facts (verified live 2026-11-01): KXWTIH settles on the close of the 1-minute WTI
candlestick at the top of the hour (Pyth WTI; event KXWTIH-26NOV0122 closes 03:00Z for the
10:00 PM EST hour), ~30 `greater` strikes an event at $0.10 steps, events created ~90
minutes ahead. There is no Brent hourly and no 15-minute oil series on Kalshi. The model
is a live-price Normal with the trailing hourly sigma of Kalshi's own settled values,
scaled by sqrt(time-to-close); only settlements exactly one hour apart feed the sigma, so
the daily halt and the weekend gap never inflate it.
"""

import statistics
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from tradehub.backtest.pit import Observation
from tradehub.data.kalshi_live import KalshiLive, LiveMarket
from tradehub.data.wti import wti_last_price
from tradehub.edges import Quote
from tradehub.engines.oil_hourly import (
    event_hour,
    hourly_changes,
    hourly_prob,
    hourly_sigma,
    sigma_for,
)
from tradehub.journal.contract import CalendarEntry
from tradehub.journal.forecasters.oil_hourly import (
    MIN_CHANGES,
    HourlyInputs,
    OilHourlyPersistence,
    OilWtiHourly,
    build_oil_hourly,
)
from tradehub.journal.scoring import MIN_SETTLED
from tradehub.markets import parse_market

ET = ZoneInfo("America/New_York")
CLOSE = datetime(2026, 11, 2, 16, 0, tzinfo=UTC)    # 11:00 EST settlement hour, Mon Nov 2
NOW = CLOSE - timedelta(minutes=40)                  # inside the 65-minute freeze window


def _lm(strike, close=CLOSE, bid=0.40, ask=0.44):
    raw = {"ticker": f"KXWTIH-26NOV0211-T{strike}", "event_ticker": "KXWTIH-26NOV0211",
           "strike_type": "greater", "floor_strike": strike, "cap_strike": None,
           "open_time": "2026-11-02T14:30:00Z", "close_time": close.isoformat(),
           "title": "WTI hourly"}
    return LiveMarket(parse_market(raw), Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=5.0, yes_ask_size=5.0))


def _settled():
    """Settled hours: Fri Oct 30 08:00-17:00 ET, then Sun 18:00 ET through Mon 10:00 ET.

    The Fri->Sun pair spans the weekend halt and must NOT count as an hourly change.
    """
    hours = [datetime(2026, 10, 30, h, tzinfo=ET) for h in range(8, 18)]
    hours += [datetime(2026, 11, 1, h, tzinfo=ET) for h in range(18, 24)]
    hours += [datetime(2026, 11, 2, h, tzinfo=ET) for h in range(0, 11)]
    out = []
    value = 100.0
    for i, dt in enumerate(hours):
        if i:
            value += 0.15 if i % 2 else -0.05
        name = f"KXWTIH-{dt.strftime('%y%b%d').upper()}{dt.hour:02d}"
        # Kalshi publishes the settlement about a minute after the hour
        # (settlement_timer_seconds: 60 in the live market payload).
        out.append(Observation(name, round(value, 2),
                               (dt + timedelta(minutes=2)).astimezone(UTC)))
    return out


class FakeLive:
    def __init__(self, markets, settled=None):
        self.markets = markets
        self.settled = _settled() if settled is None else settled

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]

    def settled_values_recent(self, series, max_events):
        return self.settled

    def settled_values(self, series):
        return self.settled


def _inputs(live, price=101.20, price_age=timedelta(minutes=2)):
    obs = None if price is None else Observation("WTI:CL=F:last", price, NOW - price_age)
    return HourlyInputs(live, price_fn=lambda: obs)


def _fc(live, price=101.20, **kw):
    return OilWtiHourly(live, lambda ticker: None, _inputs(live, price, **kw))


# ---- engine ---------------------------------------------------------------

def test_event_hour_reads_the_eastern_hour_from_the_ticker():
    dt = event_hour("KXWTIH-26NOV0122")
    assert (dt.year, dt.month, dt.day, dt.hour) == (2026, 11, 1, 22)
    assert dt.utcoffset() == timedelta(hours=-5)  # EST in November


def test_hourly_changes_skip_the_weekend_gap():
    changes = hourly_changes(_settled())
    assert len(changes) == 25  # 9 Friday + 16 across Sun/Mon, the halt pair excluded
    assert changes == hourly_changes(list(reversed(_settled())))  # order-insensitive


def test_hourly_sigma_floors_and_uses_the_trailing_window():
    assert hourly_sigma([0.01, -0.01]) == 0.05
    changes = [((-1) ** i) * 0.2 for i in range(100)]
    assert hourly_sigma(changes) == max(0.05, statistics.stdev(changes[-72:]))


def test_sigma_scales_with_sqrt_time_to_close():
    assert sigma_for(0.30, 60) == 0.30
    assert abs(sigma_for(0.30, 15) - 0.15) < 1e-9
    assert sigma_for(0.30, 1) == sigma_for(0.30, 5.0)  # the five-minute floor


def test_hourly_probability_centres_on_the_live_price():
    market = _lm(101.2).market
    p = hourly_prob(market, 101.20, 0.30, 40)
    assert 0.40 < p < 0.50  # strike at the price: just under half (the half-cent interval)
    assert hourly_prob(_lm(103.2).market, 101.20, 0.30, 40) < 0.01
    # the same strike prices tighter five minutes out than fifty-five out
    near = hourly_prob(market, 101.20, 0.30, 5)
    far = hourly_prob(_lm(101.8).market, 101.20, 0.30, 55)
    assert hourly_prob(_lm(101.8).market, 101.20, 0.30, 5) < far
    assert 0.0 < near < 1.0


# ---- live price + bounded settled pull ------------------------------------

def test_wti_last_price_takes_the_last_fresh_bar():
    t0 = datetime(2026, 11, 2, 15, 18, tzinfo=UTC)
    frame = {"Close": {t0: 101.0, t0 + timedelta(minutes=1): float("nan"),
                       t0 + timedelta(minutes=2): 101.2}}
    obs = wti_last_price(history_fn=lambda: frame)
    assert obs is not None and obs.value == 101.2
    assert obs.published_at == t0 + timedelta(minutes=2)
    assert wti_last_price(history_fn=lambda: None) is None
    assert wti_last_price(history_fn=lambda: {"Close": {}}) is None


def test_settled_values_recent_stops_once_it_has_enough_events():
    pages = []

    def fake_get(path, params):
        pages.append(params)
        n = len(pages)
        markets = [{"ticker": f"KXWTIH-E{n}-{i}", "event_ticker": f"KXWTIH-26NOV0{n}{i:02d}",
                    "expiration_value": "101.25", "settlement_ts": "2026-11-02T16:01:00Z"}
                   for i in range(10)]
        return {"markets": markets, "cursor": f"c{n}" if n < 5 else ""}

    live = KalshiLive.__new__(KalshiLive)
    live._get = fake_get
    values = live.settled_values_recent("KXWTIH", max_events=15)
    assert len(pages) == 2  # 10 events a page: two pages cover the 15 asked for
    assert len(values) == 20


# ---- forecaster -------------------------------------------------------------

def test_targets_freeze_only_inside_the_65_minute_window():
    inside = _lm(101.2)
    outside = _lm(101.2, close=CLOSE + timedelta(hours=1))
    fc = _fc(FakeLive([inside, outside]))
    targets = fc.targets(NOW)
    assert [t.target for t in targets] == ["kalshi:KXWTIH-26NOV0211-T101.2"]
    assert targets[0].cadence == "hourly" and targets[0].family == "oil_hourly"


def test_forecast_prices_off_the_live_print_and_records_its_workings():
    fc = _fc(FakeLive([_lm(101.2)]))
    entry = fc.targets(NOW)[0]
    forecast = fc.forecast(entry, NOW)
    assert forecast is not None and forecast.forecaster == "oil_wti_hourly"
    assert forecast.forecaster_version == "wti-hourly-v1"
    assert 0.40 < forecast.probability < 0.50
    assert forecast.payload["live_price"] == 101.20
    assert forecast.payload["minutes_to_close"] == 40.0
    assert forecast.payload["changes_used"] == MIN_CHANGES + 1


def test_forecast_refuses_a_stale_price_and_a_thin_sigma_history():
    stale = _fc(FakeLive([_lm(101.2)]), price_age=timedelta(minutes=16))
    assert stale.forecast(stale.targets(NOW)[0], NOW) is None
    thin = _fc(FakeLive([_lm(101.2)], settled=_settled()[:10]))
    assert thin.forecast(thin.targets(NOW)[0], NOW) is None
    missing = _fc(FakeLive([_lm(101.2)]), price=None)
    assert missing.forecast(missing.targets(NOW)[0], NOW) is None


def test_persistence_anchors_on_the_last_settled_hour():
    live = FakeLive([_lm(101.2)])
    fc = OilHourlyPersistence(live, lambda ticker: None, _inputs(live))
    assert fc.name == "baseline_persistence_oil_hourly"
    forecast = fc.forecast(fc.targets(NOW)[0], NOW)
    settled = _settled()
    assert forecast is not None
    assert forecast.payload["last_settlement"] == settled[-1].value
    assert forecast.payload["span_minutes"] == 60.0  # Mon 10:00 ET settled -> 11:00 close


def test_registry_carries_the_hourly_rows_with_unique_keys():
    from tradehub.journal.registry import FORECASTERS as _live, RETIRED

    FORECASTERS = _live + RETIRED  # retired rows are still built; they just stop freezing

    keys = [(f.name, f.version) for f in FORECASTERS]
    assert ("oil_wti_hourly", "wti-hourly-v1") in keys
    assert ("oil_wti_hourly_cautious", "wti-hourly-v1+w25") in keys
    assert ("kalshi_implied_oil_hourly", "v1") in keys
    assert ("baseline_persistence_oil_hourly", "v1") in keys
    assert len(set(keys)) == len(keys)


def test_build_oil_hourly_registers_the_trio_and_hourly_is_a_real_cadence():
    names = [(f.name, f.cadence) for f in build_oil_hourly(FakeLive([]))]
    assert names == [("oil_wti_hourly", "hourly"), ("kalshi_implied_oil_hourly", "hourly"),
                     ("baseline_persistence_oil_hourly", "hourly")]
    entry = CalendarEntry("kalshi:X", "oil_hourly", "hourly", CLOSE, market_linked=True)
    assert entry.cadence == "hourly"
    assert MIN_SETTLED["hourly"] == 200
