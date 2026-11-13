"""The v4 shadow family (prereg 2026-11-14, revised 2026-11-13): each
candidate trades only inside its stated entry minutes at its stated
bar, the paired baseline is the live gate's minute-5 row, fresh means
window_open >= PREREG_AT, late dials are fill-checked against the
minute tape, and the house promotion criterion / stopping rule decide
eligibility and the kill."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from tradehub import fifteen_candidates as fc

AFTER = "2026-11-16T15:00:00Z"  # window opens after PREREG_AT (2026-11-15)
BEFORE = "2026-11-14T15:00:00Z"


def row(target="KXNATGAS15M-1", *, series="KXNATGAS15M", close=AFTER,
        offset=5, edge=0.15, pnl=0.10, outcome=1, side="yes", cost=0.50):
    return {"series": series, "target": target, "close_time": close,
            "offset_min": offset, "edge_net": edge, "side": side,
            "side_cost": cost, "pnl": pnl, "outcome": outcome}


def fills_for(r, *, yes=100.0, no=100.0):
    return {(r["series"], r["close_time"], r["offset_min"]):
            {"yes": yes, "no": no}}


def test_edge20_trades_minute_5_only():
    rows = [row(offset=3, edge=0.30, pnl=0.99),   # a bigger earlier edge: not its minute
            row(offset=5, edge=0.21, pnl=0.10)]
    result = fc.evaluate(rows, "v4-edge20-shadow",
                         now=datetime(2026, 11, 20, tzinfo=UTC))
    assert result["trades"] == 1
    assert result["net_per_contract"] == 0.10


def test_baseline_is_the_minute_5_row_not_the_earliest_trade():
    # A minute-1 trade exists and the candidate (late window, filled via
    # a generous tape) takes a minute-12 trade; the live gate never
    # traded (no minute-5 row), so the pair is against 0, not minute 1.
    late = row(offset=12, edge=0.15, pnl=0.20)
    rows = [row(offset=1, edge=0.30, pnl=-0.90), late]
    result = fc.evaluate(rows, "v4-late-window-shadow",
                         now=datetime(2026, 11, 20, tzinfo=UTC),
                         fills=fills_for(late))
    assert result["trades"] == 1 and result["paired_windows"] == 1
    assert result["net_per_contract"] == 0.20


def test_late_window_takes_the_earliest_of_11_to_13_only():
    rows = [row(offset=10, edge=0.15, pnl=0.99),
            row(offset=13, edge=0.15, pnl=0.30),
            row(offset=11, edge=0.15, pnl=0.20),
            row(offset=14, edge=0.15, pnl=0.99)]
    picked = fc.candidate_trade(rows, fc.CANDIDATES["v4-late-window-shadow"],
                                "KXNATGAS15M")
    assert picked["offset_min"] == 11


def test_per_commodity_dials():
    c = fc.CANDIDATES["v4-per-commodity-shadow"]
    gas = fc.candidate_trade(
        [row(offset=12, edge=0.30, pnl=0.99),
         row(offset=5, edge=0.15, pnl=0.10)], c, "KXNATGAS15M")
    assert gas["offset_min"] == 5  # late timing hurts gas: minute 5 only
    copper_thin = [row(series="KXCOPPER15M", offset=12, edge=0.15, pnl=0.10)]
    assert fc.candidate_trade(copper_thin, c, "KXCOPPER15M") is None
    copper_big = [row(series="KXCOPPER15M", offset=12, edge=0.22, pnl=0.10)]
    assert fc.candidate_trade(copper_big, c, "KXCOPPER15M") is not None
    gold = [row(series="KXGOLD15M", offset=5, edge=0.30, pnl=0.10)]
    assert fc.candidate_trade(gold, c, "KXGOLD15M") is None


def test_no_gold_is_the_live_minute_without_gold():
    c = fc.CANDIDATES["v4-no-gold-shadow"]
    assert fc.candidate_trade([row(offset=5, edge=0.15)], c, "KXNATGAS15M")
    assert fc.candidate_trade(
        [row(series="KXGOLD15M", offset=5, edge=0.15)], c, "KXGOLD15M") is None
    assert fc.candidate_trade([row(offset=6, edge=0.15)], c, "KXNATGAS15M") is None


def test_fresh_means_window_open_at_prereg():
    # Closes 10 minutes after PREREG_AT but opens 5 minutes before it:
    # not fresh under the blend's convention.
    edge = "2026-11-15T00:10:00Z"
    rows = [row("W-edge", close=edge, offset=5, edge=0.25, pnl=0.50)]
    result = fc.evaluate(rows, "v4-edge20-shadow",
                         now=datetime(2026, 11, 20, tzinfo=UTC))
    assert result["windows"] == 0 and result["trades"] == 0
    exact = "2026-11-15T00:15:00Z"  # opens exactly at PREREG_AT: fresh
    rows = [row("W-exact", close=exact, offset=5, edge=0.25, pnl=0.50)]
    result = fc.evaluate(rows, "v4-edge20-shadow",
                         now=datetime(2026, 11, 20, tzinfo=UTC))
    assert result["trades"] == 1


def test_evaluate_counts_only_settled_fresh_windows():
    rows = [
        row("W-old", close=BEFORE, pnl=9.9),              # pre-prereg: out
        row("W-open", outcome=None, pnl=None),            # unsettled: out
        row("W-1", offset=5, edge=0.25, pnl=0.20),        # edge20 trades
        row("W-2", offset=5, edge=0.15, pnl=-0.40),       # under its bar
    ]
    result = fc.evaluate(rows, "v4-edge20-shadow",
                         now=datetime(2026, 11, 20, tzinfo=UTC))
    assert result["windows"] == 2
    assert result["trades"] == 1
    assert result["net_per_contract"] == 0.20
    assert result["paired_windows"] == 2  # W-2 pairs its sit-out vs the gate
    assert not result["eligible"] and not result["killed"]


def test_fill_rule_counts_only_measured_deep_enough_trades():
    late = row(offset=12, edge=0.15, pnl=0.20, cost=0.50)
    now = datetime(2026, 11, 20, tzinfo=UTC)
    # demo needs max(1, floor(500*0.01/0.50)) = 10 contracts at 0.50
    deep = fc.evaluate([late], "v4-late-window-shadow", now=now,
                       fills=fills_for(late, yes=10.0))
    assert deep["trades"] == 1 and deep["fill_short"] == 0
    thin = fc.evaluate([late], "v4-late-window-shadow", now=now,
                       fills=fills_for(late, yes=9.0))
    assert thin["trades"] == 0 and thin["fill_short"] == 1
    unknown = fc.evaluate([late], "v4-late-window-shadow", now=now, fills={})
    assert unknown["trades"] == 0 and unknown["fill_unknown"] == 1
    assert unknown["paired_windows"] == 0  # unmeasured: window leaves scoring


def _many_good_trades(days=3, per_day=40):
    rows = []
    for d in range(days):
        close = (fc.PREREG_AT + timedelta(days=d + 1)).strftime(
            "%Y-%m-%dT15:00:00Z")
        for i in range(per_day):
            rows.append(row(f"W-{d}-{i}", close=close, offset=5,
                            edge=0.25, pnl=0.12))
    return rows


def test_a_candidate_identical_to_the_gate_never_clears_the_paired_leg():
    # no-gold on a gold-free record takes exactly the gate's minute-5
    # trades: every paired delta is 0, so low95 is 0 -- never eligible.
    result = fc.evaluate(_many_good_trades(), "v4-no-gold-shadow",
                         now=fc.PREREG_AT + timedelta(days=10))
    assert result["trades"] == 120 and result["paired_low95"] == 0.0
    assert not result["eligible"]


def test_eligible_when_the_frozen_bar_clears():
    # The gate takes minute 5 and loses; the late window sits it out
    # and takes the moderate late trade instead (fills measured deep).
    rows = []
    fills = {}
    for d in range(3):
        close = (fc.PREREG_AT + timedelta(days=d + 1)).strftime(
            "%Y-%m-%dT15:00:00Z")
        for i in range(40):
            target = f"W-{d}-{i}"
            rows.append(row(target, close=close, offset=5, edge=0.30,
                            pnl=-0.50))
            late = row(target, close=close, offset=12, edge=0.15, pnl=0.12)
            rows.append(late)
            fills.update(fills_for(late))
    result = fc.evaluate(rows, "v4-late-window-shadow",
                         now=fc.PREREG_AT + timedelta(days=10), fills=fills)
    assert result["trades"] == 120
    assert result["eligible"] and not result["killed"]


def test_killed_by_days_and_by_trades():
    few = [row("W-1", pnl=-0.05)]
    by_days = fc.evaluate(few, "v4-edge20-shadow",
                          now=fc.PREREG_AT + timedelta(days=61))
    assert by_days["killed"] and not by_days["eligible"]
    rows = []
    for i in range(300):
        rows.append(row(f"W-{i}", offset=5, edge=0.25, pnl=-0.05))
    by_trades = fc.evaluate(rows, "v4-edge20-shadow",
                            now=fc.PREREG_AT + timedelta(days=10))
    assert by_trades["trades"] == 300 and by_trades["killed"]


def test_per_series_breakdown_is_reported():
    rows = [row("W-gas", offset=5, edge=0.15, pnl=0.10),
            row("W-wti", series="KXWTI15M", offset=5, edge=0.15, pnl=-0.05)]
    result = fc.evaluate(rows, "v4-no-gold-shadow",
                         now=datetime(2026, 11, 20, tzinfo=UTC))
    assert result["by_series"]["KXNATGAS15M"]["trades"] == 1
    assert result["by_series"]["KXWTI15M"]["net_per_contract"] == -0.05


# -- the scorer: stable pagination and the terminal kill --------------------

class _FakeStore:
    """Captures select_all calls; serves canned rows per table."""

    def __init__(self, canned):
        self.canned = canned
        self.calls = []

    def __call__(self, client, table, build, order):
        self.calls.append((table, order))
        return list(self.canned.get(table, []))


@pytest.fixture()
def scorer(monkeypatch):
    from tradehub.scripts import fifteen_candidates_score as score
    monkeypatch.setattr(score, "get_client", lambda: object())
    monkeypatch.setattr(score, "fetch_ticks", lambda *a, **k: [])
    alerts = []
    monkeypatch.setattr(score, "write_gate_alert",
                        lambda client, **kw: alerts.append(kw) or True)
    return score, alerts


def test_scorer_pages_the_offset_read_in_a_stable_order(scorer, monkeypatch):
    score, _alerts = scorer
    fake = _FakeStore({})
    monkeypatch.setattr(score.store, "select_all", fake)
    score.main([])
    offset_orders = [order for table, order in fake.calls
                     if table == score.OFFSETS_TABLE]
    assert offset_orders == [("close_time", "series", "target", "offset_min")]


def test_a_killed_candidate_is_not_scored_again(scorer, monkeypatch, capsys):
    score, alerts = scorer
    canned = {score.ALERTS_TABLE: [
        {"evidence": {"version": "v4-edge20-shadow", "event": "killed"}}]}
    fake = _FakeStore(canned)
    monkeypatch.setattr(score.store, "select_all", fake)
    score.main([])
    report = json.loads(capsys.readouterr().out)
    edge = next(c for c in report["candidates"]
                if c["version"] == "v4-edge20-shadow")
    assert edge["killed"] is True and edge["scored"] is False
    assert alerts == []  # terminal: no later alert of any kind
