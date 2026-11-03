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


# ---- the ITM line (Kevin, 2026-11-03) --------------------------------------

from datetime import timedelta  # noqa: E402

from tradehub.data.wti import wti_minute_tape  # noqa: E402
from tradehub.oil_live import pick_itm_line  # noqa: E402


def _tape(now, prices):
    """1-minute closes ending at `now`, oldest first."""
    n = len(prices)
    return [(now - timedelta(minutes=n - 1 - i), p) for i, p in enumerate(prices)]


def _rows(*specs):
    return [{"strike": k, "ours": o, "market": m} for k, o, m in specs]


def test_wti_minute_tape_sorts_and_skips_nan():
    import pandas as pd

    idx = pd.to_datetime(["2026-11-03T14:02:00Z", "2026-11-03T14:01:00Z", "2026-11-03T14:03:00Z"])
    frame = pd.DataFrame({"Close": [98.2, 98.1, float("nan")]}, index=idx)
    tape = wti_minute_tape(history_fn=lambda: frame)
    assert [p for _ts, p in tape] == [98.1, 98.2]


def test_itm_pick_qualifies_above_the_tape():
    # Price ran at 98.5-98.7 for 10 minutes; strike 98.00 sits below the
    # whole window (never the level), we price it 65% vs Kalshi's 58%.
    pick = pick_itm_line(_rows((98.0, 0.65, 0.58)), _tape(NOW, [98.5] * 10), NOW, 98.6)
    assert pick is not None and pick["strike"] == 98.0 and pick["gap_pts"] == 7.0
    assert pick["clear_bars"] == 10


def test_itm_pick_rejects_a_strike_the_tape_crossed():
    # The tape dipped through 98.00 inside the window: it WAS the level.
    prices = [98.5] * 5 + [97.9] + [98.5] * 4
    assert pick_itm_line(_rows((98.0, 0.65, 0.58)), _tape(NOW, prices), NOW, 98.6) is None


def test_itm_pick_rejects_thin_tape_small_gap_and_off_band():
    tape = _tape(NOW, [98.5] * 10)
    assert pick_itm_line(_rows((98.0, 0.65, 0.58)), tape[:4], NOW, 98.6) is None  # thin tape
    assert pick_itm_line(_rows((98.0, 0.65, 0.63)), tape, NOW, 98.6) is None  # gap < 3 pts
    assert pick_itm_line(_rows((98.0, 0.52, 0.40)), tape, NOW, 98.6) is None  # below the band
    assert pick_itm_line(_rows((98.0, 0.80, 0.60)), tape, NOW, 98.6) is None  # above the band
    assert pick_itm_line(_rows((98.0, 0.65, None)), tape, NOW, 98.6) is None  # no market price


def test_itm_pick_prefers_the_strike_closest_to_the_money():
    rows = _rows((97.5, 0.70, 0.60), (98.0, 0.65, 0.58), (98.25, 0.60, 0.52))
    pick = pick_itm_line(rows, _tape(NOW, [98.5] * 10), NOW, 98.5)
    assert pick is not None and pick["strike"] == 98.25
