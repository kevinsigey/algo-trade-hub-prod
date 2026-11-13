"""Kalshi demo gas runner: demo-host guard, sizing, caps, reconcile.

Every Kalshi call is stubbed (FakePortfolio); the DB is the house fake.
No network: the A7 fixture poisons real requests on top of this.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import json as json_mod
import pytest

from tradehub import kalshi_demo as kd
from tradehub import oil_fifteen_rule as rule
from tradehub.core.kalshi_portfolio import (
    KalshiPortfolio,
    KalshiWriteError,
    NotDemoHostError,
    check_portfolio_available,
)
from tests.workshop_fake import DB

NOW = datetime(2026, 11, 12, 17, 0, tzinfo=timezone.utc)  # Thu 12:00 ET
TICKER = "KXNATGAS15M-26NOV121215-00"
TARGET = f"kalshi:{TICKER}"


class FakePortfolio:
    def __init__(self, balance_cents=50000, refuse=False):
        self.balance_cents = balance_cents
        self.refuse = refuse
        self.placed: list[dict] = []
        self.cancelled: list[str] = []
        self.fills: list[dict] = []

    def assert_demo_host(self):
        if self.refuse:
            raise NotDemoHostError("KALSHI_ENV is 'live', not 'demo'")

    def get_balance(self):
        return {"balance": self.balance_cents}

    def create_order(self, **kw):
        self.placed.append(kw)
        return {"order_id": f"ord-{len(self.placed)}"}

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return {}

    def get_order(self, order_id):
        return None

    def get_orders(self, status=None):
        return []

    def get_fills(self, limit=200):
        return self.fills


def decision(**over):
    close = NOW + timedelta(minutes=10)
    row = {
        "series": kd.SERIES, "target": TARGET, "ticker": TICKER,
        "action": "buy", "side": "yes", "cost": 0.40,
        "gate_version": "v1", "outcome": None, "pnl": None,
        "close_time": close.isoformat(),
        "frozen_at": (NOW - timedelta(minutes=2)).isoformat(),
    }
    row.update(over)
    return row


REAL_OPEN_DECISIONS = kd.fifteen_tracking.open_decisions


@pytest.fixture(autouse=True)
def _open_decisions(monkeypatch):
    """The runner's candidates are open-window decisions; most tests here
    hand them in directly (seed(open_=...)) and exercise the guards. The
    production-shaped test below runs the real open_decisions instead."""
    monkeypatch.setattr(kd.fifteen_tracking, "open_decisions",
                        lambda supa, now, series_set=None: list(supa.db.get("_open", [])))


def seed(db, decisions=(), orders=(), ticks=(), open_=()):
    db.db["_open"] = list(open_)
    db.db[kd.DECISIONS] = list(decisions)
    db.db[kd.ORDERS] = list(orders)
    db.db[kd.TICKS] = list(ticks)
    return db


def order_row(**over):
    row = {
        "id": 1, "series": kd.SERIES, "target": TARGET, "ticker": TICKER,
        "side": "yes", "gate_version": "v1", "contracts": 12,
        "contracts_filled": 0, "limit_price": 0.40, "frozen_quote": 0.40,
        "kalshi_order_id": "ord-9", "client_order_id": f"kd-{TICKER}",
        "status": "resting", "fill_price": None, "settlement_pnl": None,
        "window_close": (NOW + timedelta(minutes=10)).isoformat(),
        "created_at": NOW.isoformat(),
    }
    row.update(over)
    return row


# -- the demo guard ------------------------------------------------------------

def test_runner_refuses_when_not_demo():
    db = seed(DB(), open_=[decision()])
    out = kd.run_once(db, FakePortfolio(refuse=True), NOW)
    assert "refused" in out
    assert db.db[kd.ORDERS] == []


def _rsa_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()


@pytest.fixture()
def live_client(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID", "test-key-id")
    monkeypatch.setenv("KALSHI_API_KEY", _rsa_pem())
    return KalshiPortfolio()


def test_assert_demo_host_matrix(monkeypatch, live_client):
    monkeypatch.delenv("KALSHI_ENV", raising=False)
    with pytest.raises(NotDemoHostError):
        live_client.assert_demo_host()
    monkeypatch.setenv("KALSHI_ENV", "live")
    with pytest.raises(NotDemoHostError):
        live_client.assert_demo_host()
    monkeypatch.setenv("KALSHI_ENV", "demo")  # default base IS the demo host
    live_client.assert_demo_host()
    live = KalshiPortfolio(api_base="https://api.elections.kalshi.com")
    with pytest.raises(NotDemoHostError):
        live.assert_demo_host()


def test_create_order_never_fires_without_demo(monkeypatch, live_client):
    monkeypatch.delenv("KALSHI_ENV", raising=False)
    called = []
    monkeypatch.setattr("tradehub.core.kalshi_portfolio.requests.request",
                        lambda *a, **k: called.append(a))
    with pytest.raises(NotDemoHostError):
        live_client.create_order(ticker=TICKER, side="yes", count=1,
                                 limit_price_cents=40, client_order_id="x",
                                 expiration_ts=1)
    assert called == []


def _capture(monkeypatch, status=201, payload=None):
    seen = {}
    payload = payload if payload is not None else {}

    class Resp:
        status_code = status
        text = json_mod.dumps(payload)

        def json(self):
            return payload

    def fake_request(method, url, headers=None, json=None, timeout=None):
        seen.update(method=method, url=url, body=json)
        return Resp()

    monkeypatch.setattr("tradehub.core.kalshi_portfolio.requests.request",
                        fake_request)
    return seen


def test_create_order_v2_no_side(monkeypatch, live_client):
    monkeypatch.setenv("KALSHI_ENV", "demo")
    seen = _capture(monkeypatch, payload={"order_id": "abc", "client_order_id": "kd-x"})
    out = live_client.create_order(
        ticker=TICKER, side="no", count=12, limit_price_cents=40,
        client_order_id="kd-x", expiration_ts=1794500000)
    assert out["order_id"] == "abc"
    assert seen["method"] == "POST"
    assert seen["url"] == ("https://demo-api.kalshi.co/trade-api/v2"
                           "/portfolio/events/orders")
    # buy NO @40c == ask YES @60c
    assert seen["body"] == {
        "ticker": TICKER, "client_order_id": "kd-x", "side": "ask",
        "count": "12.00", "price": "0.6000",
        "time_in_force": "good_till_canceled", "expiration_time": 1794500000,
        "self_trade_prevention_type": "taker_at_cross"}


def test_create_order_v2_yes_side(monkeypatch, live_client):
    monkeypatch.setenv("KALSHI_ENV", "demo")
    seen = _capture(monkeypatch, payload={"order_id": "abc"})
    live_client.create_order(ticker=TICKER, side="yes", count=3,
                             limit_price_cents=7, client_order_id="c",
                             expiration_ts=1)
    assert seen["body"]["side"] == "bid" and seen["body"]["price"] == "0.0700"
    assert seen["body"]["count"] == "3.00"


def test_cancel_order_v2_path_and_guard(monkeypatch, live_client):
    monkeypatch.setenv("KALSHI_ENV", "demo")
    seen = _capture(monkeypatch, status=200,
                    payload={"order_id": "abc", "reduced_by": "12.00", "ts_ms": 1})
    assert live_client.cancel_order("abc")["reduced_by"] == "12.00"
    assert seen["method"] == "DELETE"
    assert seen["url"].endswith("/trade-api/v2/portfolio/events/orders/abc")
    monkeypatch.setenv("KALSHI_ENV", "live")
    with pytest.raises(NotDemoHostError):
        live_client.cancel_order("abc")


def test_live_host_still_refused_for_create(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID", "k")
    monkeypatch.setenv("KALSHI_API_KEY", _rsa_pem())
    monkeypatch.setenv("KALSHI_ENV", "demo")
    called = []
    monkeypatch.setattr("tradehub.core.kalshi_portfolio.requests.request",
                        lambda *a, **k: called.append(a))
    live = KalshiPortfolio(api_base="https://api.elections.kalshi.com")
    with pytest.raises(NotDemoHostError):
        live.create_order(ticker=TICKER, side="yes", count=1,
                          limit_price_cents=40, client_order_id="x",
                          expiration_ts=1)
    assert called == []


def test_fills_v2_dollar_fields():
    pf = FakePortfolio()
    pf.fills = [
        {"order_id": "o1", "outcome_side": "no", "no_price_dollars": "0.4000",
         "yes_price_dollars": "0.6000", "count_fp": "5.00",
         "created_time": "2026-11-12T17:00:00Z"},
        {"order_id": "o1", "outcome_side": "no", "no_price_dollars": "0.4200",
         "yes_price_dollars": "0.5800", "count_fp": "5.00",
         "created_time": "2026-11-12T16:59:00Z"}]
    agg = kd._fills_by_order(pf)["o1"]
    assert agg["count"] == 10 and agg["avg_price"] == pytest.approx(0.41)
    assert agg["first_ts"] == "2026-11-12T16:59:00Z"


def test_find_by_client_order_id_v2_shape():
    pf = FakePortfolio()
    pf.get_orders = lambda status=None: [
        {"order_id": "a", "client_order_id": "x", "status": "resting"},
        {"order_id": "b", "client_order_id": "y", "status": "executed"}]
    assert kd._find_by_client_order_id(pf, "y")["order_id"] == "b"
    assert kd._find_by_client_order_id(pf, "z") is None


def test_write_error_raises(monkeypatch, live_client):
    monkeypatch.setenv("KALSHI_ENV", "demo")

    class Resp:
        status_code = 400
        text = "bad order"

        def json(self):
            return {}

    monkeypatch.setattr("tradehub.core.kalshi_portfolio.requests.request",
                        lambda *a, **k: Resp())
    with pytest.raises(KalshiWriteError):
        live_client.create_order(ticker=TICKER, side="yes", count=1,
                                 limit_price_cents=40, client_order_id="x",
                                 expiration_ts=1)


def test_availability_accepts_key_file(monkeypatch, tmp_path):
    pem = tmp_path / "kalshi_demo.pem"
    pem.write_text("key")
    monkeypatch.setenv("KALSHI_API_KEY_ID", "id")
    monkeypatch.delenv("KALSHI_API_KEY", raising=False)
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", str(pem))
    assert check_portfolio_available() is True
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", str(tmp_path / "nope.pem"))
    monkeypatch.delenv("KALSHI_KEY_FILE", raising=False)
    assert check_portfolio_available() is False


def test_guard_only_kalshi_portfolio_writes_orders():
    # The Kalshi endpoint fragment as an exact string token. (The hub's own
    # Alpaca route "/api/portfolio/orders" contains the substring but is a
    # different string and a different service entirely.)
    root = Path("tradehub")
    offenders = [str(p) for p in root.rglob("*.py")
                 if '"/portfolio/events/orders' in p.read_text(errors="ignore")
                 and p != root / "core" / "kalshi_portfolio.py"]
    assert offenders == []
    for mod in ("tradehub/kalshi_demo.py", "tradehub/scripts/kalshi_demo_run.py"):
        assert "requests." not in Path(mod).read_text()


# -- sizing (Kevin's 1% rule) ----------------------------------------------------

@pytest.mark.parametrize("balance,price,want", [
    (500, 0.30, 16), (500, 0.40, 12), (500, 0.60, 8),
    (750, 0.30, 25), (750, 0.40, 18), (1000, 0.40, 25), (1000, 0.60, 16),
    (40, 0.60, 1),   # floor is 0 -> the minimum-1 rule still trades
])
def test_size_contracts(balance, price, want):
    assert kd.size_contracts(balance, price, 0.01) == want


# -- placement -------------------------------------------------------------------

def test_places_only_gated_gas_buys():
    db = seed(DB(), open_=[
        decision(),
        decision(target="kalshi:KXNATGAS15M-26NOV121230-00",
                 ticker="KXNATGAS15M-26NOV121230-00", action="skip"),
        decision(target="kalshi:KXWTI15M-26NOV121215-00",
                 ticker="KXWTI15M-26NOV121215-00", series="KXWTI15M"),
        decision(target="kalshi:KXNATGAS15M-26NOV121245-00",
                 ticker="KXNATGAS15M-26NOV121245-00", gate_version="v2-blend"),
        decision(target="kalshi:KXNATGAS15M-26NOV121300-00",
                 ticker="KXNATGAS15M-26NOV121300-00",
                 frozen_at=(NOW - timedelta(minutes=30)).isoformat()),
    ])
    pf = FakePortfolio()
    out = kd.run_once(db, pf, NOW)
    assert out["candidates"] == 1 and out["placed"] == 1
    assert out["other_gate_versions"] == 1  # the blend row, counted not traded
    placed = pf.placed[0]
    assert placed["ticker"] == TICKER and placed["count"] == 12  # $500 x 1% / $0.40
    assert placed["limit_price_cents"] == 40
    assert placed["client_order_id"] == f"kd-{TICKER}"
    close = NOW + timedelta(minutes=10)
    assert placed["expiration_ts"] == int((close - timedelta(seconds=60)).timestamp())
    row = db.db[kd.ORDERS][0]
    assert row["status"] == "resting" and row["contracts"] == 12
    assert row["balance_at_sizing"] == 500.0 and row["budget_pct"] == 0.01


def test_blend_shadow_decisions_never_traded():
    db = seed(DB(), open_=[decision(gate_version="v2-blend")])
    pf = FakePortfolio()
    out = kd.run_once(db, pf, NOW)
    assert pf.placed == [] and out["candidates"] == 0


def test_never_orders_twice():
    db = seed(DB(), open_=[decision()])
    pf = FakePortfolio()
    kd.run_once(db, pf, NOW)
    kd.run_once(db, pf, NOW)
    assert len(pf.placed) == 1


def test_production_shaped_trades_the_open_window(monkeypatch):
    # Production on 2026-11-12: the record pass writes a window's decision
    # row only after it closes, so the decisions table never holds an open
    # window. Here it holds only closed windows (1,200 stale buys and a
    # just-closed one); the one open window has a frozen forecast with an
    # edge. The real open_decisions must find it and place exactly once.
    from tradehub import fifteen_tracking as tracking
    monkeypatch.setattr(kd.fifteen_tracking, "open_decisions", REAL_OPEN_DECISIONS)
    closed = []
    for i in range(1200):
        ticker = f"KXNATGAS15M-26NOV110000-{i:04d}"
        closed.append(decision(
            target=f"kalshi:{ticker}", ticker=ticker,
            close_time=(NOW - timedelta(days=1, minutes=i % 60)).isoformat(),
            frozen_at=(NOW - timedelta(days=1)).isoformat()))
    just_closed = "KXNATGAS15M-26NOV121200-00"
    closed.append(decision(target=f"kalshi:{just_closed}", ticker=just_closed,
                           close_time=(NOW - timedelta(minutes=5)).isoformat(),
                           frozen_at=(NOW - timedelta(minutes=15)).isoformat()))
    calendar = [
        {"target": f"kalshi:{just_closed}", "cutoff_at": (NOW - timedelta(minutes=5)).isoformat()},
        {"target": TARGET, "cutoff_at": (NOW + timedelta(minutes=10)).isoformat()},
        # opens later; no forecast frozen yet -- not a decision
        {"target": "kalshi:KXNATGAS15M-26NOV121230-00",
         "cutoff_at": (NOW + timedelta(minutes=25)).isoformat()},
    ]
    forecasts = [{"target": TARGET, "probability": 0.70,
                  "frozen_at": (NOW - timedelta(minutes=1)).isoformat(),
                  "payload": {"yes_ask": 0.40, "yes_bid": 0.38}}]
    monkeypatch.setattr(tracking, "fetch_targets", lambda supa, family, since, until: [
        c for c in calendar if family == "natgas_15m"
        and since <= datetime.fromisoformat(c["cutoff_at"]) <= until])
    monkeypatch.setattr(tracking.store, "fetch_forecasts",
                        lambda supa, f, v, targets=None: [
                            r for r in forecasts if f == "natgas_15m" and r["target"] in targets])
    db = seed(DB(), decisions=closed)
    assert all(kd._dt(d["close_time"]) < NOW for d in db.db[kd.DECISIONS])
    pf = FakePortfolio()
    out = kd.run_once(db, pf, NOW)
    assert out["gate_version"] == "v1"
    assert out["candidates"] == 1 and out["placed"] == 1
    assert [p["ticker"] for p in pf.placed] == [TICKER]
    assert pf.placed[0]["side"] == "yes" and pf.placed[0]["limit_price_cents"] == 40
    assert kd.run_once(db, pf, NOW + timedelta(minutes=5))["placed"] == 0
    assert len(pf.placed) == 1  # never twice


def test_decision_mismatch_counted_against_the_tracking_row():
    # The record pass's row for an order's window, once it lands, must say
    # what the runner traded on. A different side or cost is counted.
    other = "KXNATGAS15M-26NOV120900-00"
    db = seed(DB(), decisions=[decision(side="no", cost=0.60),
                               decision(target=f"kalshi:{other}", ticker=other)],
              orders=[order_row(status="settled", settlement_pnl=1.0),
                      order_row(id=2, target=f"kalshi:{other}", ticker=other,
                                status="settled", settlement_pnl=1.0)])
    out = kd.run_once(db, FakePortfolio(), NOW)
    assert out["decision_mismatch"] == 1
    kd._summary_cache = None
    pf = FakePortfolio()
    pf.get_positions = lambda: []
    report = kd.build_report(db, pf, NOW)
    kd._summary_cache = None
    assert report["performance"]["decision_mismatch"] == 1


class LostResponsePortfolio(FakePortfolio):
    """The first create is accepted by the exchange, then its response is
    lost (a timeout): the order exists, but the runner saw an exception."""

    def __init__(self):
        super().__init__()
        self.accepted: list[dict] = []
        self.create_calls = 0

    def create_order(self, **kw):
        self.create_calls += 1
        if self.create_calls == 1:
            self.accepted.append({"order_id": "ord-lost", "status": "resting",
                                  "client_order_id": kw["client_order_id"]})
            raise TimeoutError("response lost after acceptance")
        return super().create_order(**kw)

    def get_orders(self, status=None):
        return list(self.accepted)


def test_timed_out_placement_is_adopted_not_replaced():
    db = seed(DB(), open_=[decision()])
    pf = LostResponsePortfolio()
    first = kd.run_once(db, pf, NOW)
    assert first["placed"] == 0 and pf.create_calls == 1
    row = db.db[kd.ORDERS][0]
    assert row["status"] == "pending" and row.get("kalshi_order_id") is None

    second = kd.run_once(db, pf, NOW + timedelta(minutes=1))
    assert second["adopted"] == 1
    assert pf.create_calls == 1  # adopted by client_order_id, never re-placed
    row = db.db[kd.ORDERS][0]
    assert row["status"] == "resting" and row["kalshi_order_id"] == "ord-lost"


def test_depth_under_one_skips():
    close = (NOW + timedelta(minutes=10)).isoformat()
    db = seed(DB(), open_=[decision()], ticks=[{
        "series": kd.SERIES, "close_time": close, "at": NOW.isoformat(),
        "yes_ask_size": 0, "no_ask_size": 9}])
    pf = FakePortfolio()
    out = kd.run_once(db, pf, NOW)
    assert pf.placed == [] and out["skipped_no_depth"] == 1
    row = db.db[kd.ORDERS][0]
    assert row["status"] == "skipped_no_depth" and row["ask_size"] == 0


def test_depth_measured_and_recorded():
    close = (NOW + timedelta(minutes=10)).isoformat()
    db = seed(DB(), open_=[decision()], ticks=[{
        "series": kd.SERIES, "close_time": close, "at": NOW.isoformat(),
        "yes_ask_size": 147, "no_ask_size": 3}])
    kd.run_once(db, FakePortfolio(), NOW)
    assert db.db[kd.ORDERS][0]["ask_size"] == 147


def test_contract_cap_skips(monkeypatch):
    monkeypatch.setenv("KALSHI_DEMO_MAX_CONTRACTS_PER_DAY", "12")
    earlier = "kalshi:KXNATGAS15M-26NOV120900-00"
    db = seed(DB(), open_=[decision()],
              orders=[order_row(id=7, target=earlier,
                                ticker="KXNATGAS15M-26NOV120900-00",
                                kalshi_order_id="ord-8", contracts=12,
                                status="settled", settlement_pnl=1.0)])
    pf = FakePortfolio()
    out = kd.run_once(db, pf, NOW)
    assert pf.placed == [] and out["skipped_cap"] == 1
    skip = [r for r in db.db[kd.ORDERS] if r["status"] == "skipped_cap"]
    assert skip and skip[0]["skip_reason"] == "daily_contract_cap"


def test_loss_cap_skips(monkeypatch):
    earlier = "kalshi:KXNATGAS15M-26NOV120900-00"
    db = seed(DB(), open_=[decision()],
              orders=[order_row(id=7, target=earlier,
                                ticker="KXNATGAS15M-26NOV120900-00",
                                kalshi_order_id="ord-8", contracts=5,
                                status="settled", settlement_pnl=-19.0)])
    pf = FakePortfolio()
    out = kd.run_once(db, pf, NOW)
    assert pf.placed == [] and out["skipped_cap"] == 1
    skip = [r for r in db.db[kd.ORDERS] if r["status"] == "skipped_cap"]
    assert skip and skip[0]["skip_reason"] == "daily_loss_cap"


# -- reconcile -------------------------------------------------------------------

def test_unfilled_order_cancelled_at_cutoff():
    db = seed(DB(), orders=[order_row(
        window_close=(NOW - timedelta(minutes=1)).isoformat())])
    pf = FakePortfolio()
    out = kd.run_once(db, pf, NOW)
    assert pf.cancelled == ["ord-9"] and out["cancelled"] == 1
    assert db.db[kd.ORDERS][0]["status"] == "cancelled"


def test_filled_order_settles_not_cancelled():
    db = seed(DB(), decisions=[decision(outcome=1)],
              orders=[order_row(
                  window_close=(NOW - timedelta(minutes=1)).isoformat())])
    pf = FakePortfolio()
    pf.fills = [{"order_id": "ord-9", "side": "yes", "yes_price": 40,
                 "count_fp": "12.00", "created_ts": NOW.isoformat()}]
    out = kd.run_once(db, pf, NOW)
    row = db.db[kd.ORDERS][0]
    assert pf.cancelled == []
    assert row["status"] == "settled" and row["contracts_filled"] == 12
    assert row["fill_price"] == pytest.approx(0.40)
    assert row["settlement_pnl"] == pytest.approx(12 * rule.pnl("yes", 0.40, 1))
    assert out["settled"] == 1


def test_partial_fill_recorded():
    db = seed(DB(), orders=[order_row(contracts=12)])
    pf = FakePortfolio()
    pf.fills = [{"order_id": "ord-9", "side": "yes", "yes_price": 41,
                 "count_fp": "2.00", "created_ts": NOW.isoformat()}]
    kd.run_once(db, pf, NOW)
    row = db.db[kd.ORDERS][0]
    assert row["status"] == "filled" and row["contracts_filled"] == 2
    assert row["fill_price"] == pytest.approx(0.41)


def test_pending_past_cutoff_cancelled():
    db = seed(DB(), orders=[order_row(
        status="pending", kalshi_order_id=None,
        window_close=(NOW - timedelta(minutes=1)).isoformat())])
    out = kd.run_once(db, FakePortfolio(), NOW)
    row = db.db[kd.ORDERS][0]
    assert row["status"] == "cancelled"
    assert row["skip_reason"] == "placement_interrupted"
    assert out["cancelled"] == 1


def test_lost_response_on_last_pass_is_adopted_at_cutoff():
    # The last pass before cutoff: the create is accepted on the exchange,
    # its response is lost. The next pass is past the cutoff -- the row is
    # no longer a candidate, so only reconcile sees it. It must adopt the
    # real order by client_order_id, not write it off as interrupted.
    db = seed(DB(), open_=[decision()])
    pf = LostResponsePortfolio()
    last = NOW + timedelta(minutes=8)  # close is NOW+10, cutoff NOW+9
    assert kd.run_once(db, pf, last)["placed"] == 0
    assert db.db[kd.ORDERS][0]["status"] == "pending"
    db.db["_open"] = []
    pf.fills = [{"order_id": "ord-lost", "side": "yes", "yes_price": 40,
                 "count_fp": "12.00", "created_ts": last.isoformat()}]
    out = kd.run_once(db, pf, NOW + timedelta(minutes=9, seconds=30))
    row = db.db[kd.ORDERS][0]
    assert out["adopted"] == 1 and out["cancelled"] == 0
    assert row["kalshi_order_id"] == "ord-lost" and row.get("skip_reason") is None
    assert row["status"] == "filled" and row["contracts_filled"] == 12
    assert pf.create_calls == 1
