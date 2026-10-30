from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from workshop_fake import DB

from tradehub.portfolio import paper_orders, service
from tradehub.portfolio.alpaca_paper import AccountNotConnected
from tradehub.scripts import paper_orders_run
from tradehub.workshop import store

MORNING = datetime.fromisoformat("2026-11-03T12:30:00+00:00")  # Tue 07:30 New York
IDX = pd.bdate_range("2020-01-02", "2026-11-02")
SPEC = {"title": "Hold GLD", "hold": ["GLD"], "claim": "beats_benchmark", "start": "2020-01-02"}


def closes(tickers, start):
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0.0002, 0.01, len(IDX))) for t in
                          ("GLD", "SLV", "SPY", "QQQ", "IWM")}, index=IDX)
    frame["GLD"] = frame["GLD"] / frame["GLD"].iloc[-1] * 300.0  # last close $300
    return frame[[t for t in tickers if t in frame]]


class Alpaca:
    def __init__(self, open_today=True, equity=100_000.0, fills=(), orders=(), positions=(), pending=()):
        self.open_today, self.equity = open_today, equity
        self.fills, self.orders, self.positions = list(fills), list(orders), list(positions)
        self.pending = list(pending)

    def __call__(self, path, params=None):
        if path == "/v2/calendar":
            days = [str(d.date()) for d in pd.bdate_range(params["start"], params["end"])]
            return [{"date": d} for d in days if self.open_today or d != params["end"]]
        if path == "/v2/orders" and (params or {}).get("status") == "open":
            return self.pending
        return {"/v2/account": {"account_number": "PA1", "equity": str(self.equity), "cash": str(self.equity)},
                "/v2/positions": self.positions, "/v2/account/activities/FILL": self.fills,
                "/v2/orders": self.orders}[path]


class Submit:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail or {}

    def __call__(self, symbol, qty, side, client_order_id, **kw):
        self.calls.append((symbol, side, qty, client_order_id, kw))
        if symbol in self.fail:
            raise self.fail[symbol]
        return {"id": f"alp-{len(self.calls)}"}


def live_idea(db, idea_id, spec=SPEC, auto=True):
    db.table("idea_runs").insert({"idea_id": idea_id, "variation": 1, "spec": spec, "verdict": "PASS", "result": {},
                                  "data_end": "2026-01-01"}).execute()
    db.db["ideas"][idea_id - 1].update({"live_at": "2026-11-02T15:00:00+00:00", "live_run_id": len(db.db["idea_runs"]),
                                        "size_pct": 20})
    if auto:
        store.set_auto(db, idea_id, True, "kevin")


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("TRADEHUB_PAPER_ORDERS", "on")
    d = DB()
    store.create_idea(d, "Hold GLD", "w")
    store.create_idea(d, "Hold SLV", "w")
    return d


def run(db, alpaca, submit, monkeypatch, now=MORNING):
    monkeypatch.setattr(service, "paper_get", alpaca)
    return paper_orders_run.run(now, db, submit=submit, closes=closes, fred=None)


def statuses(db):
    return [(r["idea_id"], r["symbol"], r["side"], r["qty"], r["status"]) for r in db.db.get("paper_orders", [])]


def test_holiday_sends_nothing(db, monkeypatch):
    live_idea(db, 1)
    sub = Submit()
    summary, failed = run(db, Alpaca(open_today=False), sub, monkeypatch)
    assert sub.calls == [] and summary == {"market": "closed"} and statuses(db) == []


def test_happy_path_sends_and_logs(db, monkeypatch):
    live_idea(db, 1)
    sub = Submit()
    summary, failed = run(db, Alpaca(), sub, monkeypatch)
    assert failed == {} and statuses(db) == [(1, "GLD", "buy", 66, "sent")]
    symbol, side, qty, cid, kw = sub.calls[0]
    assert cid == "idea-1-auto-20261103-GLD-open" and kw["time_in_force"] == "opg"
    assert db.db["paper_orders"][0]["alpaca_order_id"] == "alp-1"


def test_rerun_logs_already_sent(db, monkeypatch):
    live_idea(db, 1)
    run(db, Alpaca(), Submit(), monkeypatch)
    run(db, Alpaca(), Submit(fail={"GLD": paper_orders.DuplicateOrder("c")}), monkeypatch)
    assert [s[-1] for s in statuses(db)] == ["sent", "already sent"]


def test_master_switch_off_sends_nothing(db, monkeypatch):
    live_idea(db, 1)
    monkeypatch.delenv("TRADEHUB_PAPER_ORDERS")
    sub = Submit()
    run(db, Alpaca(), sub, monkeypatch)
    assert sub.calls == [] and statuses(db) == [(1, "GLD", "buy", 66, "skipped")]
    assert "TRADEHUB_PAPER_ORDERS" in db.db["paper_orders"][0]["reason"]


def test_one_idea_failing_does_not_stop_another(db, monkeypatch):
    live_idea(db, 1, spec={**SPEC, "hold": ["GONE"]})
    live_idea(db, 2, spec={**SPEC, "title": "Hold SLV", "hold": ["SLV"]})
    summary, failed = run(db, Alpaca(), Submit(), monkeypatch)
    assert list(failed) == [1] and [s[1] for s in statuses(db)] == ["SLV"]


def test_rejection_is_logged_with_alpacas_reason(db, monkeypatch):
    live_idea(db, 1)
    run(db, Alpaca(), Submit(fail={"GLD": paper_orders.OrderRejected("insufficient buying power")}), monkeypatch)
    assert statuses(db)[0][-1] == "rejected" and db.db["paper_orders"][0]["reason"] == "insufficient buying power"


def test_switched_off_idea_closes_its_own_shares_only(db, monkeypatch):
    live_idea(db, 1)
    store.set_auto(db, 1, False, "kevin")
    fills = [{"id": "f1", "order_id": "a", "symbol": "GLD", "side": "buy", "qty": "66", "price": "300",
              "transaction_time": "2026-11-02T14:30:00Z"},
             {"id": "f2", "order_id": "m", "symbol": "GLD", "side": "buy", "qty": "10", "price": "300",
              "transaction_time": "2026-11-02T15:30:00Z"}]
    orders = [{"id": "a", "client_order_id": "idea-1-auto-20261102-GLD-open", "submitted_at": "t1"},
              {"id": "m", "client_order_id": "manual-1", "submitted_at": "t2"}]
    positions = [{"symbol": "GLD", "qty": "76", "market_value": "22800", "current_price": "300"}]
    sub = Submit()
    run(db, Alpaca(fills=fills, orders=orders, positions=positions), sub, monkeypatch)
    assert [(c[0], c[1], c[2]) for c in sub.calls] == [("GLD", "sell", 66)]
    assert sub.calls[0][3] == "idea-1-auto-20261103-GLD-close"


def test_account_not_connected(db, monkeypatch):
    live_idea(db, 1)

    def down(path, params=None):
        raise AccountNotConnected("no keys")
    sub = Submit()
    summary, failed = run(db, down, sub, monkeypatch)
    assert sub.calls == [] and summary == {"account": "not connected"}


def test_unknown_holdings_stop_the_run_instead_of_buying_again(db, monkeypatch):
    # If the order map can't be read, the idea's shares look manual and it would buy its full size twice.
    live_idea(db, 1)
    alpaca = Alpaca()

    def flaky(path, params=None):
        if path == "/v2/orders":
            raise RuntimeError("Alpaca 500")
        return alpaca(path, params)
    sub = Submit()
    monkeypatch.setattr(service, "paper_get", flaky)
    with pytest.raises(RuntimeError):
        paper_orders_run.run(MORNING, db, submit=sub, closes=closes, fred=None)
    assert sub.calls == []


def test_pending_orders_count_toward_the_25_percent_limit(db, monkeypatch):
    # Review C1: on a re-run, idea 2's GLD order is already waiting; idea 1 must still see it.
    live_idea(db, 1)
    live_idea(db, 2, spec={**SPEC, "title": "Also GLD"})
    pending = [{"symbol": "GLD", "side": "buy", "qty": "66", "limit_price": None,
                "client_order_id": "idea-2-auto-20261103-GLD-open"}]
    sub = Submit(fail={"GLD": paper_orders.DuplicateOrder("c")})
    run(db, Alpaca(pending=pending), sub, monkeypatch)
    by_idea = {r["idea_id"]: (r["status"], r["reason"]) for r in db.db["paper_orders"]}
    assert by_idea[2][0] == "already sent"
    assert by_idea[1][0] == "skipped" and "25%" in by_idea[1][1]


def test_no_equity_sends_nothing_and_fails(db, monkeypatch):
    # Review I1: equity 0 would size every target to 0 and sell everything the idea holds.
    live_idea(db, 1)
    sub = Submit()
    summary, failed = run(db, Alpaca(equity=0), sub, monkeypatch)
    assert sub.calls == [] and summary == {"account": "no equity"}
    assert paper_orders_run.exit_code(summary, failed) == 1


def test_rejections_and_disconnects_fail_the_job(db, monkeypatch):
    # Review I2: an all-rejected morning or refused keys must not exit 0.
    live_idea(db, 1)
    summary, failed = run(db, Alpaca(), Submit(fail={"GLD": paper_orders.OrderRejected("no")}), monkeypatch)
    assert failed == {1: "1 order(s) rejected"} and paper_orders_run.exit_code(summary, failed) == 1
    assert paper_orders_run.exit_code({"market": "closed"}, {}) == 0
    assert paper_orders_run.exit_code({"account": "not connected"}, {}) == 1


def test_stale_prices_skip_the_idea(db, monkeypatch):
    # Review I6: yesterday's bar missing means the target would be the day before's; skip and fail instead.
    live_idea(db, 1)

    def stale(tickers, start):
        return closes(tickers, start).iloc[:-1]
    monkeypatch.setattr(service, "paper_get", Alpaca())
    sub = Submit()
    summary, failed = paper_orders_run.run(MORNING, db, submit=sub, closes=stale, fred=None)
    assert sub.calls == [] and "2026-10-30" in failed[1] and "2026-11-02" in failed[1]
