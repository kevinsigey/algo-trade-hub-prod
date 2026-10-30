import pytest

from tradehub.portfolio.book import MANUAL, closed_trades, composition, curve, positions_view, scoreboard, win_rate


def snap(t, equity, spy, account="PA1", cash=0.0):
    return {"taken_at": t, "account_number": account, "equity": equity, "cash": cash, "spy_price": spy}


def series(equities):
    return [snap(f"2026-11-{2 + i:02d}T20:00:00+00:00", e, 500) for i, e in enumerate(equities)]


def fill(symbol, side, qty, price, day):
    return {"symbol": symbol, "side": side, "qty": str(qty), "price": str(price),
            "transaction_time": f"{day}T15:00:00Z"}


def test_scoreboard_vs_spy():
    s = scoreboard([snap("2026-11-02T15:00:00+00:00", 100_000, 500), snap("2026-11-03T15:00:00+00:00", 104_820, 510.5)])
    assert s["start_at"] == "2026-11-02T15:00:00+00:00"
    assert s["equity"] == 104_820
    assert s["return_pct"] == pytest.approx(4.82)
    assert s["spy_return_pct"] == pytest.approx(2.1)
    assert s["ahead_pts"] == pytest.approx(2.72)


def test_scoreboard_single_snapshot_is_unknown_not_zero():
    s = scoreboard([snap("2026-11-02T15:00:00+00:00", 100_000, 500)])
    assert s["equity"] == 100_000
    assert s["return_pct"] is None and s["spy_return_pct"] is None and s["ahead_pts"] is None
    assert s["max_drawdown_pct"] is None and s["sharpe"] is None


def test_scoreboard_no_snapshots():
    assert scoreboard([])["equity"] is None


def test_max_drawdown():
    assert scoreboard(series([100, 110, 99, 120]))["max_drawdown_pct"] == pytest.approx(-10.0)


def test_sharpe_needs_five_days_and_uses_daily_closes():
    assert scoreboard(series([100, 101, 102, 103]))["sharpe"] is None
    # two snapshots on the same day: only the last one counts
    snaps = series([100, 101, 100, 102, 101, 103])
    snaps.insert(1, snap("2026-11-02T15:00:00+00:00", 50, 500))
    snaps.sort(key=lambda r: r["taken_at"])
    assert scoreboard(snaps)["sharpe"] == pytest.approx(scoreboard(series([100, 101, 100, 102, 101, 103]))["sharpe"])


def test_curve_rebased_to_zero():
    c = curve([snap("t0", 100, 500), snap("t1", 110, 505)])
    assert c == [{"t": "t0", "portfolio_pct": 0.0, "spy_pct": 0.0},
                 {"t": "t1", "portfolio_pct": pytest.approx(10.0), "spy_pct": pytest.approx(1.0)}]


def test_short_position_pct_uses_abs_value():
    rows = positions_view({"equity": "10000", "cash": "12000"},
                          [{"symbol": "XLE", "qty": "-20", "side": "short", "market_value": "-2000",
                            "unrealized_pl": "50"}])
    xle = next(r for r in rows if r["symbol"] == "XLE")
    assert xle["qty"] == -20 and xle["market_value"] == -2000
    assert xle["pct_of_book"] == pytest.approx(20.0) and xle["idea"] == MANUAL
    assert rows[-1]["symbol"] == "Cash" and rows[-1]["pct_of_book"] == pytest.approx(120.0)


def test_composition_groups_by_idea():
    rows = positions_view({"equity": "100000", "cash": "50000"}, [
        {"symbol": "GLD", "qty": "60", "side": "long", "market_value": "30000", "unrealized_pl": "600"},
        {"symbol": "XLE", "qty": "250", "side": "long", "market_value": "20000", "unrealized_pl": "-200"},
    ])
    assert composition(rows) == [{"idea": MANUAL, "pct_of_book": pytest.approx(50.0), "unrealized_pl": pytest.approx(400)}]


def test_fifo_closed_trades_with_partial_fills():
    t = closed_trades([fill("GLD", "buy", 10, 200, "2026-11-02"), fill("GLD", "buy", 10, 210, "2026-11-03"),
                       fill("GLD", "sell", 15, 220, "2026-11-05")])
    assert [(x["qty"], x["entry_price"], x["exit_price"]) for x in t] == [(10, 200, 220), (5, 210, 220)]
    assert sum(x["pnl"] for x in t) == pytest.approx(10 * 20 + 5 * 10)
    assert t[0]["held_days"] == 3 and t[0]["return_pct"] == pytest.approx(10.0)
    assert t[0]["idea"] == MANUAL


def test_short_round_trip():
    t = closed_trades([fill("XLE", "sell", 20, 100, "2026-11-02"), fill("XLE", "buy", 20, 90, "2026-11-04")])
    assert len(t) == 1 and t[0]["qty"] == -20 and t[0]["pnl"] == pytest.approx(200)


def test_empty_inputs():
    assert closed_trades([]) == [] and win_rate([]) is None
    assert positions_view({"equity": "100000", "cash": "100000"}, [])[-1]["symbol"] == "Cash"


def test_win_rate():
    assert win_rate([{"pnl": 5}, {"pnl": -1}, {"pnl": 2}, {"pnl": 0}]) == pytest.approx(50.0)
