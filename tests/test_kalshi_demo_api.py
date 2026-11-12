"""GET /api/kalshi-demo: the Portfolio tab's read side.

Every Kalshi call is stubbed (FakePortfolio); the DB is the house fake.
The live-account read is cached ~15s; the history, curves and stats come
from kalshi_demo_orders joined to the decisions table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradehub import kalshi_demo as kd
from tradehub.api import main
from tests.workshop_fake import DB

NOW = datetime(2026, 11, 12, 17, 0, tzinfo=timezone.utc)  # Thu 12:00 ET
TICKER = "KXNATGAS15M-26NOV121215-00"
TARGET = f"kalshi:{TICKER}"
TICKER2 = "KXNATGAS15M-26NOV121200-00"
TARGET2 = f"kalshi:{TICKER2}"


@pytest.fixture(autouse=True)
def clear_summary_cache():
    kd._summary_cache = None
    yield
    kd._summary_cache = None


class FakePortfolio:
    def __init__(self):
        self.balance_calls = 0

    def assert_demo_host(self):
        return None  # the fake is a demo client by construction

    def get_balance(self):
        self.balance_calls += 1
        return {"balance": 50500, "portfolio_value": 250}  # $505.00 + $2.50

    def get_positions(self):
        return [{"ticker": TICKER, "position": 12,
                 "total_traded": 492, "market_exposure": 540}]

    def get_positions_strict(self):
        return self.get_positions()

    def get_market_data(self, ticker):
        return {"market": {
            "ticker": ticker, "floor_strike": 2.5,
            "close_time": (NOW + timedelta(minutes=5)).isoformat(),
            "yes_bid_dollars": "0.4500", "yes_ask_dollars": "0.4700",
            "no_bid_dollars": "0.5300", "no_ask_dollars": "0.5500",
        }}


def order_row(**over):
    row = {
        "id": 1, "series": kd.SERIES, "target": TARGET, "ticker": TICKER,
        "side": "yes", "gate_version": "v1", "contracts": 12,
        "contracts_filled": 0, "limit_price": 0.40, "frozen_quote": 0.40,
        "ask_size": 90, "kalshi_order_id": "ord-9",
        "client_order_id": f"kd-{TICKER}", "status": "resting",
        "skip_reason": None, "fill_price": None, "filled_at": None,
        "settlement_pnl": None, "outcome": None,
        "window_close": (NOW + timedelta(minutes=5)).isoformat(),
        "created_at": NOW.isoformat(),
    }
    row.update(over)
    return row


def decision(**over):
    row = {
        "series": kd.SERIES, "target": TARGET, "ticker": TICKER,
        "action": "buy", "side": "yes", "cost": 0.40, "gate_version": "v1",
        "outcome": 1, "pnl": 0.55,
        "close_time": (NOW - timedelta(hours=1)).isoformat(),
        "frozen_at": (NOW - timedelta(hours=1, minutes=5)).isoformat(),
    }
    row.update(over)
    return row


def seeded_db():
    db = DB()
    db.db[kd.ORDERS] = [
        # a settled winner: filled 12 @ 0.41 against a 0.40 frozen quote
        order_row(id=1, status="settled", contracts_filled=12,
                  fill_price=0.41, filled_at=NOW.isoformat(),
                  settlement_pnl=6.60, outcome=1,
                  window_close=(NOW - timedelta(hours=1)).isoformat(),
                  created_at=(NOW - timedelta(hours=1, minutes=10)).isoformat()),
        # a settled loser on the other target
        order_row(id=2, target=TARGET2, ticker=TICKER2,
                  client_order_id=f"kd-{TICKER2}", status="settled",
                  contracts_filled=10, fill_price=0.40,
                  filled_at=NOW.isoformat(), settlement_pnl=-4.30,
                  outcome=0,
                  window_close=(NOW - timedelta(hours=2)).isoformat(),
                  created_at=(NOW - timedelta(hours=2, minutes=10)).isoformat()),
        # the open position's order, still resting
        order_row(id=3),
        # terminal skips and a missed placement
        order_row(id=4, status="skipped_cap", contracts=0,
                  kalshi_order_id=None, skip_reason="daily_loss_cap"),
        order_row(id=5, status="skipped_no_depth", contracts=0,
                  kalshi_order_id=None, ask_size=0),
        order_row(id=6, status="cancelled", kalshi_order_id=None,
                  skip_reason="placement_interrupted"),
    ]
    db.db[kd.DECISIONS] = [
        # TARGET: shadow pnl +0.50/contract -- deliberately NOT the demo
        # settlement's +0.55/contract, so a build_report that copied the
        # demo curve into the shadow curve would fail the assertions.
        decision(pnl=0.50),
        decision(target=TARGET2, ticker=TICKER2, pnl=-0.43, outcome=0,
                 close_time=(NOW - timedelta(hours=2)).isoformat()),
    ]
    return db


def test_report_shape_and_stats():
    report = kd.build_report(seeded_db(), FakePortfolio(), NOW)
    assert report["state"] == "live"
    assert report["balance"] == 505.0
    assert report["starting_balance"] == 500.0
    # (505.00 cash + 2.50 positions) - 500 start
    assert report["pnl_since_start"] == 7.5
    # both settled windows closed today (ET): 6.60 - 4.30
    assert report["pnl_today"] == 2.30
    assert "Demo fills don't prove the edge" in report["note"]

    (pos,) = report["positions"]
    assert pos["ticker"] == TICKER and pos["series"] == "KXNATGAS15M"
    assert pos["side"] == "yes" and pos["contracts"] == 12
    assert pos["strike"] == 2.5
    assert pos["avg_price"] == 0.40  # the resting order's limit (no fill yet)
    assert pos["yes_bid"] == 0.45 and pos["yes_ask"] == 0.47
    assert pos["open_pnl"] == 0.60  # (0.45 - 0.40) * 12

    perf = report["performance"]
    assert [p["pnl"] for p in perf["demo_curve"]] == [-4.30, 2.30]
    assert [p["pnl"] for p in perf["shadow_curve"]] == [-4.30, 1.70]
    assert [p["pnl"] for p in perf["shadow_curve_per_contract"]] == [-0.43, 0.07]
    assert perf["fill_rate"] == round(2 / 3, 4)  # 2 of 3 placed orders filled
    assert perf["avg_slippage_cents"] == 0.5     # (+1.0 and 0.0) / 2
    assert perf["win_rate"] == 0.5
    assert perf["pnl_per_contract"] == round(2.30 / 22, 4)
    assert perf["decisions_not_traded"] == {"caps": 1, "no_depth": 1, "missed": 1}
    assert len(report["orders"]) == 6


def test_live_summary_is_cached_for_15s():
    clock_now = [1000.0]
    clock = lambda: clock_now[0]  # noqa: E731
    portfolio = FakePortfolio()
    db = seeded_db()
    kd.build_report(db, portfolio, NOW, clock=clock)
    kd.build_report(db, portfolio, NOW, clock=clock)
    assert portfolio.balance_calls == 1
    clock_now[0] += 16.0
    kd.build_report(db, portfolio, NOW, clock=clock)
    assert portfolio.balance_calls == 2


def test_endpoint_not_connected(monkeypatch):
    monkeypatch.setattr(
        "tradehub.core.kalshi_portfolio.check_portfolio_available",
        lambda: False)
    out = main.get_kalshi_demo(supabase=DB())
    assert out["state"] == "not_connected"
    assert out["demo"] is True
    assert "Demo fills don't prove the edge" in out["note"]


def test_endpoint_live(monkeypatch):
    monkeypatch.setattr(
        "tradehub.core.kalshi_portfolio.check_portfolio_available",
        lambda: True)
    monkeypatch.setattr(
        "tradehub.core.kalshi_portfolio.KalshiPortfolio", FakePortfolio)
    out = main.get_kalshi_demo(supabase=seeded_db())
    assert out["state"] == "live"
    assert out["balance"] == 505.0
    assert len(out["positions"]) == 1


class PositionsDownPortfolio(FakePortfolio):
    def get_positions_strict(self):
        raise RuntimeError("positions read failed")


def test_positions_read_failure_is_flagged_and_not_cached():
    clock_now = [1000.0]
    clock = lambda: clock_now[0]  # noqa: E731
    report = kd.build_report(seeded_db(), PositionsDownPortfolio(), NOW,
                             clock=clock)
    # A failed read is NOT a flat book: flagged, and the position count
    # must not be served as a successful empty read.
    assert report["positions"] == []
    assert report["positions_unavailable"] is True
    # ...and it is not cached: the very next read at the same clock with a
    # healthy client returns the real position.
    report = kd.build_report(seeded_db(), FakePortfolio(), NOW, clock=clock)
    assert report["positions_unavailable"] is False
    assert len(report["positions"]) == 1


def test_avg_price_fallback_uses_remaining_cost_basis():
    # market_exposure_dollars: the still-held contracts' cost basis.
    pos = {"market_exposure_dollars": "4.9200"}
    assert kd._avg_price_of(pos, 12, None) == 0.41
    # The cents twin field works too.
    assert kd._avg_price_of({"market_exposure": 492}, 12, None) == 0.41
    # Historical traded totals are NOT a fallback: they count exits too.
    assert kd._avg_price_of({"total_traded_dollars": "9.8400"}, 12,
                            None) is None
    assert kd._avg_price_of({"total_traded": 984}, 12, None) is None


def test_endpoint_refuses_a_non_demo_host(monkeypatch):
    from tradehub.core.kalshi_portfolio import NotDemoHostError

    class LiveHostPortfolio(FakePortfolio):
        def assert_demo_host(self):
            raise NotDemoHostError("resolved host is the live host")

    instance = LiveHostPortfolio()
    monkeypatch.setattr(
        "tradehub.core.kalshi_portfolio.check_portfolio_available",
        lambda: True)
    monkeypatch.setattr(
        "tradehub.core.kalshi_portfolio.KalshiPortfolio", lambda: instance)
    out = main.get_kalshi_demo(supabase=seeded_db())
    assert out["state"] == "not_connected"
    # The guard fired before any account read reached the live host.
    assert instance.balance_calls == 0
