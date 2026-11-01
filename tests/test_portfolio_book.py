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


def tfill(symbol, side, qty, price, day, order_id):
    return {**fill(symbol, side, qty, price, day), "order_id": order_id}


TITLES = {1: "Gold when rates rise", 2: "Energy ballast"}


def test_tag_fills_label_beats_tag_and_unknown_is_manual():
    from tradehub.portfolio.book import tag_fills
    fills = [tfill("GLD", "buy", 1, 1, "2026-11-02", o) for o in ("a", "b", "c", "d", "e")]
    client_ids = {"a": "idea-1-001", "b": "idea-2-x", "c": "idea-9-001", "d": "my-own-id", "e": "idea-1-002"}
    out = tag_fills(fills, client_ids, {"b": 1, "e": None}, TITLES)
    assert [f["idea"] for f in out] == [TITLES[1], TITLES[1], MANUAL, MANUAL, MANUAL]
    assert [f["idea_id"] for f in out] == [1, 1, None, None, None]


def test_closed_trades_carry_the_entry_idea():
    fills = [{**fill("GLD", "buy", 10, 200, "2026-11-02"), "idea": TITLES[1]},
             {**fill("GLD", "sell", 10, 220, "2026-11-05"), "idea": TITLES[2]}]
    assert closed_trades(fills)[0]["idea"] == TITLES[1]


def test_open_lots_split_two_ideas_in_one_symbol():
    from tradehub.portfolio.book import open_lots
    fills = [{**fill("GLD", "buy", 10, 200, "2026-11-02"), "idea": TITLES[1]},
             {**fill("GLD", "buy", 30, 210, "2026-11-03"), "idea": TITLES[2]},
             {**fill("GLD", "sell", 15, 220, "2026-11-05"), "idea": MANUAL},
             {**fill("XLE", "sell", 20, 100, "2026-11-02"), "idea": TITLES[2]}]
    assert open_lots(fills) == {"GLD": {TITLES[2]: 25.0}, "XLE": {TITLES[2]: -20.0}}


def test_positions_split_by_open_lots_with_manual_remainder():
    rows = positions_view({"equity": "100000", "cash": "50000"},
                          [{"symbol": "GLD", "qty": "40", "side": "long", "market_value": "40000",
                            "unrealized_pl": "400"}],
                          {"GLD": {TITLES[1]: 10.0, TITLES[2]: 20.0}})
    gld = [(r["idea"], r["qty"], r["market_value"]) for r in rows if r["symbol"] == "GLD"]
    assert gld == [(TITLES[1], 10.0, 10000.0), (TITLES[2], 20.0, 20000.0), (MANUAL, 10.0, 10000.0)]
    assert {g["idea"]: g["pct_of_book"] for g in composition(rows)} == pytest.approx(
        {TITLES[1]: 10.0, TITLES[2]: 20.0, MANUAL: 10.0})


def test_a_sale_closes_its_own_ideas_lots_first():
    # Review finding 5: B's sale must close B's position, not A's older lot.
    from tradehub.portfolio.book import open_lots
    fills = [{**fill("GLD", "buy", 10, 200, "2026-11-02"), "idea": TITLES[1]},
             {**fill("GLD", "buy", 10, 210, "2026-11-03"), "idea": TITLES[2]},
             {**fill("GLD", "sell", 10, 220, "2026-11-05"), "idea": TITLES[2]}]
    trades = closed_trades(fills)
    assert [(t["idea"], t["entry_price"]) for t in trades] == [(TITLES[2], 210)]
    assert open_lots(fills) == {"GLD": {TITLES[1]: 10.0}}
    manual_sale = fills[:2] + [{**fill("GLD", "sell", 15, 220, "2026-11-05"), "idea": MANUAL}]
    assert [(t["idea"], t["qty"]) for t in closed_trades(manual_sale)] == [(TITLES[1], 10), (TITLES[2], 5)]


def test_open_cost_gives_qty_and_average_entry_per_idea():
    from tradehub.portfolio.book import open_cost
    fills = [{**fill("GLD", "buy", 10, 200, "2026-11-02"), "idea": 1},
             {**fill("GLD", "buy", 30, 220, "2026-11-03"), "idea": 1},
             {**fill("GLD", "sell", 15, 230, "2026-11-05"), "idea": 1},
             {**fill("QQQ", "sell", 5, 400, "2026-11-02"), "idea": 2}]
    out = open_cost(fills)
    assert out["GLD"][1] == (25.0, pytest.approx(220.0)) and out["QQQ"][2] == (-5.0, pytest.approx(400.0))
