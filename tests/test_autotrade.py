from datetime import date

import pytest

from tradehub.portfolio.autotrade import close_out, plan
from tradehub.workshop.spec import Execution

DAY = date(2026, 11, 2)
MOO = Execution()


def rows(r):
    return [(x["symbol"], x["side"], x["qty"], x["status"]) for x in r]


def test_equal_split_whole_shares_and_tags():
    out = plan(7, {"GLD": 0.5, "SLV": 0.5}, 20, 100_000, {"GLD": 300.0, "SLV": 30.0}, {}, {}, DAY, MOO)
    assert rows(out) == [("GLD", "buy", 33, "send"), ("SLV", "buy", 333, "send")]
    assert out[0]["client_order_id"] == "idea-7-auto-20261102-GLD-open"
    assert out[0]["order_type"] == "market" and out[0]["time_in_force"] == "opg" and out[0]["limit_price"] is None


def test_switch_sells_before_it_buys():
    out = plan(7, {"SPY": 1.0}, 20, 100_000, {"GLD": 300.0, "SPY": 500.0}, {"GLD": 66}, {"GLD": 19_800}, DAY, MOO)
    assert rows(out) == [("GLD", "sell", 66, "send"), ("SPY", "buy", 40, "send")]
    assert out[0]["client_order_id"].endswith("GLD-close")


def test_short_target_and_flip_closes_first_and_opens_tomorrow():
    # Review I4: Alpaca won't take the short sale while the long is still held, so a flip is two days.
    out = plan(7, {"QQQ": -1.0}, 10, 100_000, {"QQQ": 400.0}, {"QQQ": 5}, {"QQQ": 2_000}, DAY, MOO)
    assert rows(out) == [("QQQ", "sell", 5, "send"), ("QQQ", "sell", 25, "skip")]
    assert "tomorrow" in out[1]["reason"]
    fresh = plan(7, {"QQQ": -1.0}, 10, 100_000, {"QQQ": 400.0}, {}, {}, DAY, MOO)
    assert rows(fresh) == [("QQQ", "sell", 25, "send")]
    assert fresh[0]["client_order_id"].endswith("QQQ-open")


def test_too_small_is_skipped_but_a_close_never_is():
    out = plan(7, {"GLD": 1.0}, 20, 100_000, {"GLD": 300.0}, {"GLD": 66}, {"GLD": 19_800}, DAY, MOO)
    assert out == []  # already there
    out = plan(7, {"GLD": 1.0}, 20, 100_000, {"GLD": 300.0}, {"GLD": 65.8}, {"GLD": 19_740}, DAY, MOO)
    assert out == [] or out[0]["status"] == "skip"
    out = plan(7, {"BRK.A": 1.0}, 0.1, 100_000, {"BRK.A": 700_000.0}, {}, {}, DAY, MOO)
    assert rows(out) == [("BRK.A", "buy", 0, "skip")] and "too small" in out[0]["reason"]
    tiny = close_out(7, {"GLD": 0.2, "SLV": 3}, {"GLD": 300.0, "SLV": 30.0}, DAY)
    assert rows(tiny) == [("SLV", "sell", 3, "send")]  # fractional remainder can't be traded; whole shares close


def test_25_percent_limit_counts_the_whole_account_and_this_run():
    book = {"GLD": 20_000.0}  # another idea and Kevin already hold $20k of GLD
    out = plan(7, {"GLD": 1.0}, 10, 100_000, {"GLD": 300.0}, {}, book, DAY, MOO)
    assert rows(out) == [("GLD", "buy", 33, "skip")] and "30%" in out[0]["reason"] and "25%" in out[0]["reason"]
    short = plan(7, {"QQQ": -1.0}, 30, 100_000, {"QQQ": 400.0}, {}, {}, DAY, MOO)
    assert short[0]["status"] == "skip"  # |short| counts too


def test_never_sells_shares_the_idea_does_not_own():
    out = plan(7, {}, 20, 100_000, {"GLD": 300.0}, {"GLD": 10}, {"GLD": 30_000}, DAY, MOO)
    assert rows(out) == [("GLD", "sell", 10, "send")]  # Kevin's other 90 shares stay


def test_limit_prices_move_against_us():
    lim = Execution(order_type="limit", timing="close", limit_offset_bps=20)
    out = plan(7, {"SPY": 1.0}, 20, 100_000, {"GLD": 300.0, "SPY": 500.0}, {"GLD": 66}, {"GLD": 19_800}, DAY, lim)
    sell, buy = out
    assert sell["limit_price"] == pytest.approx(300.6) and buy["limit_price"] == pytest.approx(499.0)
    assert sell["time_in_force"] == buy["time_in_force"] == "cls"


def test_no_equity_no_orders():
    out = plan(7, {"GLD": 1.0}, 20, 0, {"GLD": 300.0}, {}, {}, DAY, MOO)
    assert rows(out) == [("GLD", "buy", 0, "skip")]


def test_never_opens_against_someone_elses_position():
    # Review C2: Kevin is short 100 GLD by hand; the idea must not buy into it (FIFO would net it away daily).
    out = plan(7, {"GLD": 1.0}, 1, 100_000, {"GLD": 100.0}, {}, {"GLD": -10_000}, DAY, MOO)
    assert rows(out) == [("GLD", "buy", 10, "skip")] and "opposite side" in out[0]["reason"]
    mine = plan(7, {"GLD": 1.0}, 2, 100_000, {"GLD": 100.0}, {"GLD": 10}, {"GLD": 1_000}, DAY, MOO)
    assert rows(mine) == [("GLD", "buy", 10, "send")]  # adding to its own long is fine


def test_close_out_is_always_market_at_the_open():
    # Review I7: a kill closes at the next open, whatever order type the idea traded with.
    out = close_out(7, {"GLD": 5}, {"GLD": 300.0}, DAY)
    assert out[0]["order_type"] == "market" and out[0]["time_in_force"] == "opg" and out[0]["limit_price"] is None
