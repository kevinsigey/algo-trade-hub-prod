"""The minute tape (Kevin, 2026-11-05): the model's chance and Kalshi's quotes on every open 15-minute window,
once a minute, so a first-time-the-edge-clears rule can be tested against the minute-5 freeze."""
from datetime import UTC, datetime

from workshop_fake import DB

from tradehub.scripts import fifteen_min_tape as tape

NOW = datetime(2026, 11, 6, 15, 7, tzinfo=UTC)


def _read(now):
    return {"state": "live", "as_of": now.isoformat(), "markets": [
        {"series": "KXWTI15M", "state": "live", "ticker": "KXWTI15M-26NOV061015-15", "close_time": "2026-11-06T15:15:00+00:00",
         "elapsed_min": 7.0, "minutes_left": 8.0, "prob_up": 0.6123, "yes_bid": 0.52, "yes_ask": 0.54,
         "price": 91.2, "open_price": 91.0},
        {"series": "KXBRENT15M", "state": "unavailable", "reason": "no window open right now"},
    ]}


def test_one_row_per_live_market_and_none_for_an_unreadable_one():
    db = DB()
    out = tape.run(db, NOW, read=_read, book=lambda ticker: (120.0, 35.5))
    assert out == {"recorded": 1, "skipped": 1}
    [row] = db.db["fifteen_min_ticks"]
    assert row["series"] == "KXWTI15M" and row["ticker"].endswith("-15") and row["elapsed_min"] == 7.0
    assert row["prob_up"] == 0.6123 and row["yes_bid"] == 0.52 and row["yes_ask"] == 0.54
    assert row["at"] == NOW.isoformat()
    assert row["yes_ask_size"] == 120.0 and row["no_ask_size"] == 35.5


def test_ask_sizes_come_from_the_other_sides_top_bid():
    book = {"orderbook_fp": {"no_dollars": [["0.4500", "80.00"], ["0.4700", "12.50"], ["0.0100", "5000"]],
                             "yes_dollars": [["0.5100", "40"], ["0.3000", "900"]]}}
    urls = []
    sizes = tape.book_sizes("KXNATGAS15M-X", get_json=lambda url: urls.append(url) or book)
    assert sizes == (12.5, 40.0)  # YES ask = 1 - 0.47 has 12.5 on offer; NO ask = 1 - 0.51 has 40
    assert urls[0].endswith("/markets/KXNATGAS15M-X/orderbook")
    assert tape.book_sizes("T", get_json=lambda url: {}) == (None, None)


def test_a_failed_book_read_still_records_the_quote_row():
    def boom(ticker):
        raise RuntimeError("book down")
    db = DB()
    assert tape.run(db, NOW, read=_read, book=boom) == {"recorded": 1, "skipped": 1}
    [row] = db.db["fifteen_min_ticks"]
    assert row["yes_ask"] == 0.54 and row["yes_ask_size"] is None and row["no_ask_size"] is None


def test_a_failed_read_records_nothing_and_says_so():
    def boom(now):
        raise RuntimeError("kalshi down")
    db = DB()
    assert tape.run(db, NOW, read=boom) == {"recorded": 0, "error": "RuntimeError: kalshi down"}
    assert not db.db.get("fifteen_min_ticks")
