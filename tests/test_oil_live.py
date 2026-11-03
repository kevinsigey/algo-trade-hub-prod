"""The live hourly ladder (Commodities hero): Kevin's roll rule -- inside
the last 20 minutes before a close the hero already shows the NEXT hour's
event -- and the v1 math recomputed off the live print."""
from datetime import timedelta

from tests.test_journal_oil_hourly import CLOSE, NOW, FakeLive, _settled
from tradehub.backtest.pit import Observation
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.journal.forecasters.oil_hourly import HourlyInputs
from tradehub.markets import parse_market
from tradehub.oil_live import live_ladder, pick_event


def _lm2(event, hh, strike, close, bid=0.40, ask=0.44):
    raw = {"ticker": f"{event}-T{strike}", "event_ticker": event,
           "strike_type": "greater", "floor_strike": strike, "cap_strike": None,
           "open_time": "2026-11-02T14:30:00Z", "close_time": close.isoformat(),
           "title": "WTI hourly"}
    return LiveMarket(parse_market(raw), Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=5.0, yes_ask_size=5.0))


EV_A, EV_B = "KXWTIH-26NOV0211", "KXWTIH-26NOV0212"
CLOSE_B = CLOSE + timedelta(hours=1)


def _markets():
    return ([_lm2(EV_A, 11, s, CLOSE) for s in (100, 101, 102)]
            + [_lm2(EV_B, 12, s, CLOSE_B) for s in (100, 101, 102)])


def test_pick_event_rolls_to_the_next_hour_inside_twenty_minutes():
    events = {EV_A: _markets()[:3], EV_B: _markets()[3:]}
    event, _ = pick_event(events, CLOSE - timedelta(minutes=40))
    assert event == EV_A                      # 40 out: still this hour's event
    event, _ = pick_event(events, CLOSE - timedelta(minutes=10))
    assert event == EV_B                      # 10 out: already the next hour (Kevin's rule)


def test_live_ladder_recomputes_off_the_live_print():
    live = FakeLive(_markets(), settled=_settled())
    inputs = HourlyInputs(live, price_fn=lambda: Observation("WTI:CL=F:last", 101.2, NOW - timedelta(minutes=2)))
    out = live_ladder(NOW, live=live, inputs=inputs, geo=False)
    assert out["state"] == "live" and out["event"] == EV_A
    assert out["live_price"] == 101.2 and out["minutes_to_close"] == 40.0
    strikes = [r["strike"] for r in out["rows"]]
    assert strikes == sorted(strikes) and len(strikes) == 3
    assert out["our_level"] is not None and 100 < out["our_level"] < 102
    assert out["rows"][0]["market"] == 0.42   # the quote mid rides along


def test_live_ladder_names_a_stale_print_instead_of_dressing_it_up():
    live = FakeLive(_markets(), settled=_settled())
    stale = HourlyInputs(live, price_fn=lambda: Observation("WTI:CL=F:last", 101.2, NOW - timedelta(minutes=30)))
    out = live_ladder(NOW, live=live, inputs=stale, geo=False)
    assert out["state"] == "unavailable" and "stale" in out["reason"]
