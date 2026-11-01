"""Phase-3 §5: the tracked-markets board's summarizers and per-cell guards."""

from datetime import datetime, timedelta, timezone

from tradehub.crypto_board import implied, live_board, summarize_ladder, summarize_quarter
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.markets import KalshiMarket

NOW = datetime(2026, 11, 1, 16, 0, tzinfo=timezone.utc)


def _lm(floor, bid, ask, *, close):
    market = KalshiMarket(
        ticker="KXBTCD-T", event_ticker="KXBTCD-E", series_ticker="KXBTCD",
        strike_type="greater", floor_strike=floor, cap_strike=None,
        open_time=NOW - timedelta(hours=2), close_time=close, title="t",
    )
    quote = Quote(
        yes_bid=bid, yes_ask=ask,
        yes_bid_size=0.0, yes_ask_size=0.0,
    )
    return LiveMarket(market=market, quote=quote)


def test_implied_mid_one_sided_and_empty():
    assert implied(Quote(0.40, 0.60, 0.0, 0.0)) == (0.5, False)
    assert implied(Quote(0.40, None, 0.0, 0.0)) == (0.40, True)
    assert implied(Quote(None, 0.60, 0.0, 0.0)) == (0.60, True)
    assert implied(Quote(None, None, 0.0, 0.0)) == (None, True)


def test_ladder_picks_the_next_events_coin_flip_strike():
    close = NOW + timedelta(minutes=30)
    markets = [
        _lm(90_000.0, 0.90, 0.92, close=close),
        _lm(100_000.0, 0.48, 0.52, close=close),   # mid 0.50 -- the coin-flip line
        _lm(110_000.0, 0.05, 0.07, close=close),
        _lm(100_000.0, 0.99, None, close=NOW - timedelta(hours=1)),  # past event, ignored
        _lm(100_000.0, 0.01, 0.03, close=NOW + timedelta(hours=2)),  # later event, ignored
    ]
    out = summarize_ladder(markets, now=NOW)
    assert out["shape"] == "coin_flip"
    assert out["coin_flip_strike"] == 100_000.0
    assert out["implied_pct"] == 50.0
    assert out["strikes_quoted"] == 3


def test_ladder_reports_the_step_bracket_when_no_strike_trades_near_fifty():
    # The live shape (verified 2026-11-01): 99c one-sided below spot, 1c
    # one-sided above it -- a step, not a curve.
    close = NOW + timedelta(minutes=30)
    markets = [
        _lm(2_199.99, 0.99, None, close=close),
        _lm(2_239.99, 0.99, None, close=close),
        _lm(2_279.99, None, 0.01, close=close),
        _lm(2_319.99, None, 0.01, close=close),
    ]
    out = summarize_ladder(markets, now=NOW)
    assert out["shape"] == "step"
    assert out["bracket"] == [2_239.99, 2_279.99]


def test_ladder_with_no_quoted_next_event_is_none():
    markets = [_lm(100_000.0, None, None, close=NOW + timedelta(minutes=5))]
    assert summarize_ladder(markets, now=NOW) is None
    assert summarize_ladder([], now=NOW) is None


def test_quarter_takes_the_next_market_and_its_floor():
    markets = [
        _lm(2_262.42, 0.53, 0.54, close=NOW + timedelta(minutes=10)),
        _lm(2_300.0, 0.10, 0.12, close=NOW + timedelta(minutes=25)),
    ]
    out = summarize_quarter(markets, now=NOW)
    assert out["floor"] == 2_262.42
    assert out["implied_pct"] == 53.5
    assert out["one_sided"] is False


def test_live_board_nulls_only_the_failed_cell():
    def open_markets(series):
        if series == "KXETHD":
            raise RuntimeError("kalshi down")
        return [_lm(100.0, 0.49, 0.51, close=NOW + timedelta(minutes=20))]

    board = live_board(open_markets=open_markets, spot=lambda a: 123.0, now=NOW)
    assert board["hourly"]["BTC"]["implied_pct"] == 50.0
    assert board["hourly"]["ETH"] is None
    assert "kalshi down" in board["hourly"]["ETH_error"]
    assert board["spots"] == {"BTC": 123.0, "ETH": 123.0}
