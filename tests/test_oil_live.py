"""The live hourly ladder (Commodities hero): Kevin's roll rule -- inside
the last 20 minutes before a close the hero already shows the NEXT hour's
event -- and the v1 math recomputed off the live print."""
from datetime import timedelta

import pytest

from tests.test_journal_oil_hourly import CLOSE, NOW, FakeLive, _settled
from tradehub.backtest.pit import Observation
from tradehub.data.kalshi_live import LiveMarket
from tradehub.data.hyperliquid import HyperliquidUnavailable
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


@pytest.fixture(autouse=True)
def no_live_feeds(monkeypatch):
    """These tests pin the delayed-print path: no network call to the free feed."""
    def down(_now):
        raise HyperliquidUnavailable("down in tests")
    monkeypatch.setattr("tradehub.oil_live.hyperliquid_oil_price", down)


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


def test_live_ladder_tolerates_the_delayed_feed_and_stamps_the_age():
    # Yahoo's CL=F tape runs ~10-15 min behind the exchange; a 20-minute-old
    # print is that delay, not a stuck feed. The hero (never scored) stays
    # live and reports the age so the page can show it.
    live = FakeLive(_markets(), settled=_settled())
    delayed = HourlyInputs(live, price_fn=lambda: Observation("WTI:CL=F:last", 101.2, NOW - timedelta(minutes=20)))
    out = live_ladder(NOW, live=live, inputs=delayed, geo=False)
    assert out["state"] == "live" and out["price_age_minutes"] == 20.0


def test_stale_payload_still_names_the_event():
    live = FakeLive(_markets(), settled=_settled())
    stale = HourlyInputs(live, price_fn=lambda: Observation("WTI:CL=F:last", 101.2, NOW - timedelta(minutes=30)))
    out = live_ladder(NOW, live=live, inputs=stale, geo=False)
    assert out["event"] == EV_A and out["price_age_minutes"] == 30.0


# ---- the ITM line (Kevin, 2026-11-03) --------------------------------------

from datetime import timedelta  # noqa: E402

from tradehub.data.wti import wti_minute_tape  # noqa: E402
from tradehub.oil_live import pick_best_strike  # noqa: E402


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


def _quoted(*rows):
    return [{"strike": k, "ours": ours, "market": None, "yes_bid": bid, "yes_ask": ask} for k, ours, bid, ask in rows]


def test_best_strike_buys_yes_when_the_model_clears_the_ask():
    best, closest = pick_best_strike(_quoted((95.19, 0.55, 0.46, 0.48)))
    assert best["side"] == "yes" and best["strike"] == 95.19 and best["cost"] == 0.48
    assert best["prob"] == 0.55 and best["edge_pts"] == 7.0 and best["net_pts"] == pytest.approx(5.25, abs=0.01)
    assert closest == best


def test_best_strike_can_be_the_no_side_at_its_own_price():
    best, _ = pick_best_strike(_quoted((95.19, 0.30, 0.46, 0.48)))
    assert best["side"] == "no" and best["cost"] == 0.54 and best["prob"] == 0.70 and best["edge_pts"] == 16.0


def test_best_strike_takes_the_largest_edge_after_fees():
    best, _ = pick_best_strike(_quoted((95.0, 0.60, 0.50, 0.52), (95.5, 0.50, 0.33, 0.35), (96.0, 0.45, 0.40, 0.42)))
    assert best["strike"] == 95.5


def test_no_clear_strike_still_names_the_closest():
    best, closest = pick_best_strike(_quoted((95.0, 0.52, 0.47, 0.49)))
    assert best is None and closest["strike"] == 95.0 and closest["edge_pts"] == 3.0


def test_cheap_lottery_tickets_and_wide_spreads_do_not_qualify():
    assert pick_best_strike(_quoted((99.0, 0.25, 0.10, 0.12), (98.0, 0.70, 0.40, 0.60))) == (None, None)


def test_no_two_sided_quote_means_no_pick_and_no_invented_price():
    rows = _quoted((95.0, 0.60, None, 0.50), (95.5, 0.60, 0.40, None))
    assert pick_best_strike(rows) == (None, None)
