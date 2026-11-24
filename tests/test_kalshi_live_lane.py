"""Kalshi live micro-pilot lane (issue #590): sizing table, ceilings,
window cap, daily stop, floor halt, gates, idempotency, settlement and
the scoreboard. Every Kalshi call is stubbed (FakeLivePortfolio); the
DB is the house fake. No network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradehub import kalshi_demo, kalshi_live_lane as lane
from tradehub import oil_fifteen_rule as rule
from tradehub.core.kalshi_live_portfolio import NotLiveHostError
from tradehub.journal import store as journal_store
from tests.workshop_fake import DB

NOW = datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc)  # Mon 12:00 ET
WTI = "KXWTI15M"
BRENT = "KXBRENT15M"
GAS = "KXNATGAS15M"


class FakeLivePortfolio:
    def __init__(self, balance_cents=1000, refuse=False):
        self.balance_cents = balance_cents
        self.refuse = refuse
        self.placed: list[dict] = []
        self.fills: list[dict] = []
        self.live_ask_cents = 40.0
        self.live_market = True
        self.fill_count = "1.00"

    def assert_live_host(self):
        if self.refuse:
            raise NotLiveHostError("KALSHI_LIVE_ENABLED is not '1'")

    def get_balance(self):
        if self.balance_cents is None:
            return None
        return {"balance": self.balance_cents}

    def get_market_data(self, ticker):
        if not self.live_market:
            return None
        ask = self.live_ask_cents
        return {"market": {
            "yes_ask_dollars": f"{ask / 100:.4f}",
            "yes_bid_dollars": f"{(ask - 2) / 100:.4f}",
            "no_ask_dollars": f"{(102 - ask) / 100:.4f}",
            "no_bid_dollars": f"{(100 - ask) / 100:.4f}",
        }}

    def create_order(self, **kw):
        self.placed.append(kw)
        return {"order_id": f"ord-{len(self.placed)}",
                "fill_count": self.fill_count,
                "remaining_count": "0.00"}

    def get_orders(self, status=None):
        return []

    def get_fills(self, limit=200):
        return self.fills


def decision(series=WTI, minutes=0, **over):
    close = NOW + timedelta(minutes=10)
    ticker = f"{series}-26NOV23{1200 + minutes}-00"
    row = {
        "series": series, "target": f"kalshi:{ticker}", "ticker": ticker,
        "side": "yes", "cost": 0.40, "model_prob": 0.55,
        "frozen_at": (NOW - timedelta(minutes=2)).isoformat(),
        "close_time": close.isoformat(),
    }
    row.update(over)
    return row


@pytest.fixture()
def db():
    return DB()


@pytest.fixture(autouse=True)
def _seams(monkeypatch):
    """Decisions, settlements and the shared prod-fills settle are
    handed in per test through the fake DB."""
    monkeypatch.setattr(lane, "raw_open_decisions",
                        lambda supa, now: list(supa.db.get("_open", [])))
    monkeypatch.setattr(journal_store, "fetch_settlements",
                        lambda supa, targets: dict(supa.db.get("_settled", {})))
    monkeypatch.setattr(kalshi_demo, "_tracked_decisions", lambda supa: {})
    monkeypatch.setattr(kalshi_demo, "_settle_prod_fills",
                        lambda supa, tracked, now, summary: None)


def seed_open(db, decisions):
    db.db["_open"] = list(decisions)


def seed_rows(db, rows, table=lane.ORDERS):
    for r in rows:
        db.table(table).insert(r).execute()


def order_row(**over):
    row = {
        "series": WTI, "target": "kalshi:KXWTI15M-26NOV230900-00",
        "lane": lane.LANE, "ticker": "KXWTI15M-26NOV230900-00",
        "side": "yes", "frozen_quote": 0.40,
        "frozen_at": "2026-11-23T14:55:00+00:00",
        "window_close": (NOW - timedelta(hours=2)).isoformat(),
        "contracts_requested": 1, "contracts_filled": 0,
        "status": "filled", "created_at": "2026-11-23T15:00:00+00:00",
    }
    row.update(over)
    return row


def alerts(db):
    return db.db.get(lane.ALERTS_TABLE, [])


# -- pure terms ---------------------------------------------------------------

def test_fee_rounds_up_per_order():
    assert lane.taker_fee_usd(1, 0.40) == 0.02   # 1.68c rounds up to 2c
    assert lane.taker_fee_usd(1, 0.50) == 0.02   # 1.75c -> 2c
    assert lane.taker_fee_usd(0, 0.40) == 0.0
    assert lane.taker_fee_usd(5, 0.40) == 0.09   # 8.4c -> 9c


def test_sizing_table():
    assert lane.size_contracts(10.0, 0.40, False) == 1
    assert lane.size_contracts(44.99, 0.40, True) == 1
    assert lane.size_contracts(45.0, 0.40, False) == 1   # gate unpassed
    assert lane.size_contracts(45.0, 0.40, True) == 2    # floor(0.90/0.40)
    assert lane.size_contracts(200.0, 0.40, True) == 10


def test_ceilings_env_may_lower_never_raise(monkeypatch):
    monkeypatch.setenv("KALSHI_LIVE_MAX_CONTRACTS_PER_ORDER", "50")
    assert lane.max_per_order() == 5
    monkeypatch.setenv("KALSHI_LIVE_MAX_CONTRACTS_PER_ORDER", "2")
    assert lane.max_per_order() == 2
    monkeypatch.setenv("KALSHI_LIVE_MAX_NOTIONAL_PER_DAY_USD", "999")
    assert lane.max_notional_per_day_usd() == 25.0


# -- the pass -------------------------------------------------------------------

def test_guard_refusal_places_nothing(db):
    portfolio = FakeLivePortfolio(refuse=True)
    seed_open(db, [decision()])
    summary = lane.run_once(db, portfolio, NOW)
    assert "refused" in summary
    assert portfolio.placed == []
    assert db.db.get(lane.ORDERS, []) == []


def test_places_one_contract_under_45(db):
    portfolio = FakeLivePortfolio(balance_cents=1000)  # $10
    seed_open(db, [decision()])
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["placed"] == 1 and summary["filled"] == 1
    rows = db.db[lane.ORDERS]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "filled"
    assert row["contracts_requested"] == 1
    assert row["contracts_filled"] == 1
    assert row["fill_price"] == 0.40
    assert row["fee_usd"] == 0.02
    assert row["client_order_id"] == f"kl-{row['ticker']}"
    assert row["latency_s"] == 120.0
    assert any(a["evidence"]["event"] == "fill" for a in alerts(db))


def test_second_pass_on_same_decision_places_nothing(db):
    portfolio = FakeLivePortfolio()
    seed_open(db, [decision()])
    lane.run_once(db, portfolio, NOW)
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["candidates"] == 0
    assert len(portfolio.placed) == 1
    assert len(db.db[lane.ORDERS]) == 1


def test_window_cap_counts_open_contracts(db):
    seed_rows(db, [order_row(series=GAS, target="kalshi:KXNATGAS15M-x",
                             ticker="KXNATGAS15M-x", contracts_requested=2,
                             contracts_filled=2,
                             window_close=(NOW + timedelta(minutes=10)).isoformat(),
                             created_at="2026-11-23T16:55:00+00:00")])
    seed_open(db, [decision(WTI, 0), decision(BRENT, 1)])
    portfolio = FakeLivePortfolio()
    summary = lane.run_once(db, portfolio, NOW)
    # The seeded window already holds 2 contracts; WTI takes the last
    # slot, Brent is capped out of the same window.
    assert summary["placed"] == 1
    skips = [r for r in db.db[lane.ORDERS] if r["status"] == "skipped_cap"]
    assert len(skips) == 1 and skips[0]["skip_reason"] == "window_cap"


def test_daily_stop_at_exactly_two_dollars(db):
    seed_rows(db, [
        order_row(status="settled", pnl=-1.20,
                  created_at="2026-11-23T15:00:00+00:00"),
        order_row(status="settled", pnl=-0.80, target="kalshi:KXWTI15M-y",
                  ticker="KXWTI15M-y",
                  created_at="2026-11-23T16:00:00+00:00"),
    ])
    seed_open(db, [decision()])
    portfolio = FakeLivePortfolio()
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["daily_stop"] == 2.0
    assert portfolio.placed == []
    assert any(a["evidence"]["event"] == "daily_stop" for a in alerts(db))


def test_floor_halt_persists(db):
    portfolio = FakeLivePortfolio(balance_cents=499)  # $4.99
    seed_open(db, [decision()])
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["halted"] == "floor"
    assert portfolio.placed == []
    state = {r["key"]: r["value"] for r in db.db[lane.STATE_TABLE]}
    assert state["halt"]["reason"] == "floor"
    # A later pass with a healthy balance still refuses: halts are
    # never lifted automatically.
    portfolio.balance_cents = 5000
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["halted"] == "floor"
    assert portfolio.placed == []


def test_slippage_cap_skip(db):
    portfolio = FakeLivePortfolio()
    portfolio.live_ask_cents = 45.0  # frozen 40c, live 45c: +5c > 3c cap
    seed_open(db, [decision()])
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["placed"] == 0
    row = db.db[lane.ORDERS][0]
    assert row["status"] == "skipped_no_depth"
    assert row["skip_reason"] == "slippage_cap"


def test_edge_below_bar_at_live_ask_skip(db):
    portfolio = FakeLivePortfolio()
    portfolio.live_ask_cents = 50.0  # gross edge 0.55 - 0.50 = 5 points
    seed_open(db, [decision()])
    lane.run_once(db, portfolio, NOW)
    row = db.db[lane.ORDERS][0]
    assert row["skip_reason"] == "edge_below_bar_at_live_ask"
    assert portfolio.placed == []


def test_unreadable_book_skip(db):
    portfolio = FakeLivePortfolio()
    portfolio.live_market = False
    seed_open(db, [decision()])
    lane.run_once(db, portfolio, NOW)
    row = db.db[lane.ORDERS][0]
    assert row["skip_reason"] == "live_ask_unavailable"


def test_daily_notional_ceiling_skip(db, monkeypatch):
    monkeypatch.setenv("KALSHI_LIVE_MAX_NOTIONAL_PER_DAY_USD", "0.30")
    seed_open(db, [decision()])
    portfolio = FakeLivePortfolio()
    lane.run_once(db, portfolio, NOW)
    row = db.db[lane.ORDERS][0]
    assert row["status"] == "skipped_cap"
    assert row["skip_reason"] == "daily_notional_cap"


def test_balance_unavailable_pauses_without_rows(db):
    portfolio = FakeLivePortfolio(balance_cents=None)
    seed_open(db, [decision()])
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["balance_unavailable"] is True
    assert db.db.get(lane.ORDERS, []) == []


# -- settlement -------------------------------------------------------------------

def test_settle_computes_live_and_paper_pnl(db):
    seed_rows(db, [order_row(contracts_filled=1, fill_price=0.40,
                             fee_usd=0.02, kalshi_order_id="ord-1")])
    seed_rows(db, [{"series": WTI, "target": "kalshi:KXWTI15M-26NOV230900-00",
                    "created_at": "2026-11-23T15:05:00+00:00"}],
              table=lane.DECISIONS)
    db.db["_settled"] = {"kalshi:KXWTI15M-26NOV230900-00": 1}
    portfolio = FakeLivePortfolio()
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["settled"] == 1
    row = db.db[lane.ORDERS][0]
    assert row["status"] == "settled"
    assert row["pnl"] == 0.58            # 1 x (1 - 0.40) - 0.02 fee
    assert row["paper_pnl"] == rule.pnl("yes", 0.40, 1)
    assert row["decision_id"] == db.db[lane.DECISIONS][0]["id"]


# -- gates -------------------------------------------------------------------

def _seed_filled(db, n, fill_price):
    seed_rows(db, [order_row(
        target=f"kalshi:KXWTI15M-f{i}", ticker=f"KXWTI15M-f{i}",
        contracts_filled=1, fill_price=fill_price, live_ask=fill_price,
        created_at="2026-11-22T15:00:00+00:00") for i in range(n)])


def test_gate1_halts_on_mean_slippage_above_2c(db):
    _seed_filled(db, 50, 0.43)  # +3c over the frozen 40c
    portfolio = FakeLivePortfolio()
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["gate1"] == "halt"
    assert summary["halted"] == "execution_gate"
    state = {r["key"]: r["value"] for r in db.db[lane.STATE_TABLE]}
    assert state["gate1"]["mean_slippage_cents"] == 3.0
    assert state["halt"]["reason"] == "execution_gate"
    assert any(a["evidence"]["event"] == "gate1_halt" for a in alerts(db))


def test_gate1_passes_at_1c(db):
    _seed_filled(db, 50, 0.41)
    portfolio = FakeLivePortfolio()
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["gate1"] == "pass"
    assert "halted" not in summary


def _seed_settled(db, n, pnl, days=("2026-11-21", "2026-11-22")):
    rows = []
    for i in range(n):
        day = days[i % len(days)]
        rows.append(order_row(
            target=f"kalshi:KXWTI15M-s{i}", ticker=f"KXWTI15M-s{i}",
            status="settled", contracts_filled=1, pnl=pnl,
            paper_pnl=pnl, created_at=f"{day}T15:00:00+00:00",
            window_close=f"{day}T15:15:00+00:00"))
    seed_rows(db, rows)


def test_gate2_pass_unlocks_stage3(db):
    _seed_settled(db, 150, 0.05)
    portfolio = FakeLivePortfolio()
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["gate2"] == "pass"
    state = {r["key"]: r["value"] for r in db.db[lane.STATE_TABLE]}
    assert state["stage3"]["unlocked"] is True
    assert "halt" not in state


def test_gate2_halts_on_negative_low95(db):
    _seed_settled(db, 150, -0.05)
    portfolio = FakeLivePortfolio()
    summary = lane.run_once(db, portfolio, NOW)
    assert summary["gate2"] == "halt"
    state = {r["key"]: r["value"] for r in db.db[lane.STATE_TABLE]}
    assert state["halt"]["reason"] == "edge_gate"


# -- prod-book observation on all three series --------------------------------

def test_prod_observation_records_wti(db, monkeypatch):
    from tradehub import kalshi_prod_book
    monkeypatch.setattr(kalshi_prod_book, "read_market", lambda ticker: {
        "yes_ask_dollars": "0.4000", "yes_bid_dollars": "0.3800",
        "no_ask_dollars": "0.6200", "no_bid_dollars": "0.6000"})
    monkeypatch.setattr(kalshi_prod_book, "read_ask_size",
                        lambda ticker, side, ask: 10)
    seed_open(db, [decision(WTI)])
    portfolio = FakeLivePortfolio()
    lane.run_once(db, portfolio, NOW)
    rows = db.db[lane.PROD_FILLS]
    assert len(rows) == 1
    assert rows[0]["series"] == WTI
    assert rows[0]["gate_version"] == lane.LANE
    assert rows[0]["status"] == "would_fill"


# -- scoreboard -----------------------------------------------------------------

def test_scoreboard_math(db):
    seed_rows(db, [
        order_row(status="settled", contracts_filled=1, fill_price=0.41,
                  live_ask=0.41, pnl=0.57, paper_pnl=0.58, latency_s=100.0,
                  window_close="2026-11-22T15:15:00+00:00",
                  created_at="2026-11-22T15:00:00+00:00"),
        order_row(status="unfilled", contracts_filled=0,
                  target="kalshi:KXWTI15M-u", ticker="KXWTI15M-u",
                  created_at="2026-11-22T16:00:00+00:00"),
    ])
    board = lane.build_scoreboard(db, NOW, portfolio=FakeLivePortfolio())
    assert board["real_money"] is True
    assert board["balance"] == 10.0
    assert board["decisions"] == 2
    assert board["fills"] == 1
    assert board["fill_rate"] == 0.5
    assert board["mean_slippage_cents"] == 1.0
    assert board["live_net_per_contract"] == 0.57
    assert board["paper_net_per_contract"] == 0.58
    assert board["latency_median_s"] == 100.0
    assert board["gates"]["execution"]["state"] == "pending"
    assert board["pnl_since_start"] == 0.57
