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
        if path.startswith("/v2/orders/"):  # a cancel's progress check: done at once in these tests
            return {"id": path.rsplit("/", 1)[1], "status": "canceled"}
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
    assert cid == "idea-1-auto-20261103-GLD-open" and kw["time_in_force"] == "day"
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


def test_a_stop_exit_closes_with_its_reason(db, monkeypatch):
    live_idea(db, 1, spec={**SPEC, "exits": {"stop_loss_pct": 5}})

    def crashed(tickers, start):
        frame = closes(tickers, start).copy()
        if "GLD" in frame:
            frame["GLD"] = 300.0  # flat since 2020, so no earlier exit or cooldown...
            frame.loc[frame.index[-1], "GLD"] = 240.0  # ...then -20% on the last close
        return frame
    fills = [{"id": "f1", "order_id": "a", "symbol": "GLD", "side": "buy", "qty": "66", "price": "300",
              "transaction_time": "2026-10-28T14:30:00Z"}]
    orders = [{"id": "a", "client_order_id": "idea-1-auto-20261028-GLD-open", "submitted_at": "t1"}]
    positions = [{"symbol": "GLD", "qty": "66", "market_value": "15840", "current_price": "240"}]
    monkeypatch.setattr(service, "paper_get", Alpaca(fills=fills, orders=orders, positions=positions))
    sub = Submit()
    summary, failed = paper_orders_run.run(MORNING, db, submit=sub, closes=crashed, fred=None)
    assert failed == {}, failed
    assert [(c[0], c[1], c[2]) for c in sub.calls] == [("GLD", "sell", 66)]
    assert db.db["paper_orders"][0]["reason"] == "stop-loss 5% hit"


INTRADAY = {**SPEC, "exits": {"stop_loss_pct": 5, "mode": "intraday"}}


def flat_bars(tickers, start):
    frame = closes(tickers, start)
    return {t: pd.DataFrame({"open": frame[t], "high": frame[t], "low": frame[t], "close": frame[t]})
            for t in tickers}


def test_protective_order_is_cancelled_before_the_close(db, monkeypatch):
    # Step 5 B: Alpaca holds the shares for the resting stop, so the close would be refused unless it goes first.
    live_idea(db, 1, spec=INTRADAY)
    store.set_auto(db, 1, False, "kevin")
    fills = [{"id": "f1", "order_id": "a", "symbol": "GLD", "side": "buy", "qty": "66", "price": "300",
              "transaction_time": "2026-11-02T14:30:00Z"}]
    orders = [{"id": "a", "client_order_id": "idea-1-auto-20261102-GLD-open", "submitted_at": "t1"}]
    resting = [{"id": "r1", "client_order_id": "idea-1-stop-20261102-GLD-sl", "symbol": "GLD", "qty": "66",
                "side": "sell", "type": "stop", "stop_price": "285.00", "limit_price": None}]
    positions = [{"symbol": "GLD", "qty": "66", "market_value": "19800", "current_price": "300"}]
    log = []

    def submit(symbol, qty, side, cid, **kw):
        log.append(("submit", symbol, side, qty))
        return {"id": "x"}
    monkeypatch.setattr(service, "paper_get", Alpaca(fills=fills, orders=orders, positions=positions, pending=resting))
    paper_orders_run.run(MORNING, db, submit=submit, closes=closes, fred=None, bars=flat_bars,
                         cancel=lambda oid, cid: log.append(("cancel", oid)))
    assert log == [("cancel", "r1"), ("submit", "GLD", "sell", 66)]


def test_no_buy_back_after_a_real_stop_fired(db, monkeypatch):
    # Step 5 B review focus 5: the stop sold yesterday; the rule (no condition) must wait out its cooldown.
    live_idea(db, 1, spec=INTRADAY)
    fills = [{"id": "f1", "order_id": "a", "symbol": "GLD", "side": "buy", "qty": "66", "price": "300",
              "transaction_time": "2026-10-28T14:30:00Z"},
             {"id": "f2", "order_id": "leg", "symbol": "GLD", "side": "sell", "qty": "66", "price": "285",
              "transaction_time": "2026-11-02T15:10:00Z"}]
    orders = [{"id": "a", "client_order_id": "idea-1-auto-20261028-GLD-open", "submitted_at": "t1"},
              {"id": "leg", "client_order_id": "idea-1-stop-20261029-GLD-sl", "submitted_at": "t2"}]
    sub = Submit()
    monkeypatch.setattr(service, "paper_get", Alpaca(fills=fills, orders=orders))
    paper_orders_run.run(MORNING, db, submit=sub, closes=closes, fred=None, bars=flat_bars, cancel=lambda *a: None)
    assert sub.calls == []
    row = db.db["paper_orders"][0]
    assert row["status"] == "skipped" and "stopped out on 2026-11-02" in row["reason"]


def test_a_stop_resting_on_no_shares_is_cancelled_in_the_morning(db, monkeypatch):
    # Step 5 B review C1: the idea holds nothing (its close filled), so any stop it left is cancelled.
    live_idea(db, 1, spec={**INTRADAY, "hold": [], "short": ["GLD"]})
    resting = [{"id": "r1", "client_order_id": "idea-1-stop-20261102-GLD-sl", "symbol": "GLD", "qty": "66",
                "side": "buy", "type": "stop", "stop_price": "315.00", "limit_price": None}]
    log = []
    monkeypatch.setattr(service, "paper_get", Alpaca(pending=resting))
    paper_orders_run.run(MORNING, db, submit=lambda *a, **k: log.append(("submit",) + a) or {"id": "x"},
                         closes=closes, fred=None, bars=flat_bars, cancel=lambda oid, cid: log.append(("cancel", oid)))
    assert log[0] == ("cancel", "r1")


def test_analyst_rule_calls_analyst(db, monkeypatch):
    spec = {**SPEC, "rules": {"enter": {"conditions": [{"source": "analyst", "series": "GLD", "measure": "net_upgrades",
                                                         "lookback_days": 5, "op": ">", "threshold": 0}]}}}
    live_idea(db, 1, spec=spec)
    seen = []

    def fake_analyst(ticker):
        seen.append(ticker)
        return pd.DataFrame({"action": ["up"], "target": [float("nan")]},
                            index=pd.DatetimeIndex([pd.Timestamp("2020-01-02")]))
    monkeypatch.setattr(service, "paper_get", Alpaca())
    sub = Submit()
    paper_orders_run.run(MORNING, db, submit=sub, closes=closes, fred=None, analyst=fake_analyst)
    assert seen == ["GLD"]


def test_if_the_stop_filled_while_cancelling_the_close_is_not_sent(db, monkeypatch):
    # Review I4: the stop sold the shares between the decision and the cancel; selling again would open a short.
    from tradehub.scripts import paper_orders_protect
    monkeypatch.setattr(paper_orders_protect, "_sleep", lambda s: None)
    live_idea(db, 1, spec=INTRADAY)
    store.set_auto(db, 1, False, "kevin")
    fills = [{"id": "f1", "order_id": "a", "symbol": "GLD", "side": "buy", "qty": "66", "price": "300",
              "transaction_time": "2026-11-02T14:30:00Z"}]
    orders = [{"id": "a", "client_order_id": "idea-1-auto-20261102-GLD-open", "submitted_at": "t1"}]
    resting = [{"id": "r1", "client_order_id": "idea-1-stop-20261102-GLD-sl", "symbol": "GLD", "qty": "66",
                "side": "sell", "type": "stop", "stop_price": "285.00", "limit_price": None}]
    positions = [{"symbol": "GLD", "qty": "66", "market_value": "19800", "current_price": "300"}]
    alpaca = Alpaca(fills=fills, orders=orders, positions=positions, pending=resting)

    def get(path, params=None):
        return {"id": "r1", "status": "filled"} if path == "/v2/orders/r1" else alpaca(path, params)
    sub = Submit()
    monkeypatch.setattr(service, "paper_get", get)
    paper_orders_run.run(MORNING, db, submit=sub, closes=closes, fred=None, bars=flat_bars, cancel=lambda *a: None)
    assert sub.calls == []
    assert any("filled" in (r["reason"] or "") for r in db.db["paper_orders"])


def test_a_rule_with_no_rows_is_flat_not_a_failure(db, monkeypatch):
    # CodeRabbit #201: target_and_reason's "no data" must not reach _exit_text as an exit name.
    live_idea(db, 1)
    monkeypatch.setattr(paper_orders_run, "target_and_reason", lambda spec, prices, fred, div_yields=None: ({}, "no data"))
    monkeypatch.setattr(service, "paper_get", Alpaca())
    summary, failed = paper_orders_run.run(MORNING, db, submit=Submit(), closes=closes, fred=None)
    assert failed == {}


# ── Never-silent options (Kevin, 2026-11-03) + multi-leg placement ────────────────

def manual_rows(db):
    return db.db.get("manual_actions", [])


def test_rejection_creates_a_manual_action(db, monkeypatch):
    live_idea(db, 1)
    run(db, Alpaca(), Submit(fail={"GLD": paper_orders.OrderRejected("insufficient buying power")}), monkeypatch)
    rows = manual_rows(db)
    assert len(rows) == 1 and rows[0]["idea_id"] == 1 and rows[0]["symbol"] == "GLD"
    assert rows[0]["kind"] == "order" and "buying power" in rows[0]["detail"]


def _options_env(monkeypatch, mids):
    from tradehub.portfolio import options as opt_mod
    monkeypatch.setattr(opt_mod, "fetch_contracts", lambda *a, **k: [])
    monkeypatch.setattr(opt_mod, "select_contract",
                        lambda chain, leg, spot, day: {
                            ("buy", 100): "NVDA  261204C00200000",
                            ("sell", 110): "NVDA  261204C00220000",
                            ("sell", 105): "SPY   261204C00750000",
                        }[(leg.side, leg.strike_pct)])
    monkeypatch.setattr(opt_mod, "fetch_mid", lambda occ, book=None: mids.get(occ))


def _closes_with(**pinned):
    def closes2(tickers, start):
        frame = closes(tickers, start)
        for t, v in pinned.items():
            if t in frame:
                frame[t] = frame[t] / frame[t].iloc[-1] * v
        return frame
    return closes2


def _fred_stub(sid, start):  # an options idea's morning run reads its vol indexes + DTB3
    return pd.Series(20.0, index=IDX)


NVDA_SPEC = {**SPEC, "title": "NVDA vertical", "hold": ["NVDA"],
             "options": [{"underlying": "NVDA", "kind": "call", "side": "buy", "strike_pct": 100,
                          "days_to_expiry": 30, "qty_per_share": 1},
                         {"underlying": "NVDA", "kind": "call", "side": "sell", "strike_pct": 110,
                          "days_to_expiry": 30, "qty_per_share": 1}]}


def test_vertical_idea_sends_one_mleg_order(db, monkeypatch):
    live_idea(db, 1, spec=NVDA_SPEC)
    _options_env(monkeypatch, {"NVDA  261204C00200000": 5.0, "NVDA  261204C00220000": 3.0})
    sub = Submit()
    monkeypatch.setattr(service, "paper_get", Alpaca())

    def nvda_closes(tickers, start):  # the shared fake frame has no NVDA column
        rng = np.random.default_rng(0)
        frame = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0.0002, 0.01, len(IDX)))
                              for t in ("NVDA", "SPY")}, index=IDX)
        frame["NVDA"] = frame["NVDA"] / frame["NVDA"].iloc[-1] * 200.0
        return frame[[t for t in tickers if t in frame]]

    paper_orders_run.run(MORNING, db, submit=sub, closes=nvda_closes, fred=_fred_stub)
    mleg = [c for c in sub.calls if c[4].get("legs")]
    singles = [c for c in sub.calls if c[0].startswith("NVDA  ") and not c[4].get("legs")]
    assert len(mleg) == 1 and singles == []
    assert [(l["symbol"], l["position_intent"]) for l in mleg[0][4]["legs"]] == [
        ("NVDA  261204C00200000", "buy_to_open"), ("NVDA  261204C00220000", "sell_to_open")]
    assert mleg[0][4]["limit_price"] == 2.0


def test_unwritable_covered_call_creates_a_manual_action(db, monkeypatch):
    spec = {**SPEC, "title": "SPY covered call", "hold": ["SPY"],
            "options": [{"underlying": "SPY", "kind": "call", "side": "sell", "strike_pct": 105,
                         "days_to_expiry": 30, "qty_per_share": 1}]}
    live_idea(db, 1, spec=spec)
    _options_env(monkeypatch, {"SPY   261204C00750000": 3.0})
    monkeypatch.setattr(service, "paper_get", Alpaca())
    paper_orders_run.run(MORNING, db, submit=Submit(), closes=_closes_with(SPY=750.0), fred=_fred_stub)
    rows = [r for r in manual_rows(db) if r["kind"] == "option"]
    assert len(rows) == 1 and rows[0]["symbol"] == "SPY" and "100 shares per contract" in rows[0]["detail"]


COVERED = {**SPEC, "title": "SPY covered call", "hold": ["SPY"],
           "options": [{"underlying": "SPY", "kind": "call", "side": "sell", "strike_pct": 105,
                        "days_to_expiry": 30, "qty_per_share": 1}]}


def test_covered_call_waits_for_the_shares_without_a_false_alarm(db, monkeypatch):
    live_idea(db, 1, spec=COVERED)
    _options_env(monkeypatch, {"SPY   261204C00750000": 3.0})
    monkeypatch.setattr(service, "paper_get", Alpaca(equity=500_000.0))
    sub = Submit()
    summary, failed = paper_orders_run.run(MORNING, db, submit=sub, closes=_closes_with(SPY=750.0), fred=_fred_stub)
    assert [c[0] for c in sub.calls] == ["SPY"] and failed == {}  # the shares go in, the call doesn't yet
    assert manual_rows(db) == []
    held_back = [r for r in db.db["paper_orders"] if r["symbol"].startswith("SPY") and r["symbol"] != "SPY"]
    assert held_back[0]["status"] == "skipped" and "shares" in held_back[0]["reason"]


def test_covered_call_goes_in_once_the_shares_are_held(db, monkeypatch):
    live_idea(db, 1, spec=COVERED)
    _options_env(monkeypatch, {"SPY   261204C00750000": 3.0})
    fills = [{"id": "f1", "order_id": "a", "symbol": "SPY", "side": "buy", "qty": "133", "price": "750",
              "transaction_time": "2026-11-02T14:30:00Z"}]
    orders = [{"id": "a", "client_order_id": "idea-1-auto-20261102-SPY-open", "submitted_at": "t1"}]
    monkeypatch.setattr(service, "paper_get", Alpaca(equity=500_000.0, fills=fills, orders=orders))
    sub = Submit()
    paper_orders_run.run(MORNING, db, submit=sub, closes=_closes_with(SPY=750.0), fred=_fred_stub)
    assert any(c[0] != "SPY" and c[0].startswith("SPY") and c[1] == "sell" for c in sub.calls)


def test_a_tripped_breaker_refuses_openings_and_lets_closings_through(db, monkeypatch):
    monkeypatch.setattr("tradehub.portfolio.breakers.check",
                        lambda supa, book: {"enabled": True, "tripped": True, "reasons": ["daily loss 3%"]})
    live_idea(db, 1)
    sub = Submit()
    summary, failed = run(db, Alpaca(), sub, monkeypatch)
    assert sub.calls == [] and failed == {}
    row = db.db["paper_orders"][0]
    assert row["status"] == "skipped" and "circuit breaker" in row["reason"]
    assert [a["kind"] for a in manual_rows(db)] == ["breaker"]


def test_a_tripped_breaker_still_closes_a_switched_off_idea(db, monkeypatch):
    monkeypatch.setattr("tradehub.portfolio.breakers.check",
                        lambda supa, book: {"enabled": True, "tripped": True, "reasons": ["daily loss 3%"]})
    live_idea(db, 1)
    store.set_auto(db, 1, False, "kevin")
    fills = [{"id": "f1", "order_id": "a", "symbol": "GLD", "side": "buy", "qty": "66", "price": "300",
              "transaction_time": "2026-11-02T14:30:00Z"}]
    orders = [{"id": "a", "client_order_id": "idea-1-auto-20261102-GLD-open", "submitted_at": "t1"}]
    sub = Submit()
    positions = [{"symbol": "GLD", "qty": "66", "market_value": "19800", "current_price": "300"}]
    run(db, Alpaca(fills=fills, orders=orders, positions=positions), sub, monkeypatch)
    assert [(c[0], c[1], c[2]) for c in sub.calls] == [("GLD", "sell", 66)]


def test_breakers_off_change_nothing(db, monkeypatch):
    monkeypatch.delenv("TRADEHUB_BREAKER_DAILY_LOSS_PCT", raising=False)
    monkeypatch.delenv("TRADEHUB_BREAKER_MAX_DD_PCT", raising=False)
    live_idea(db, 1)
    sub = Submit()
    run(db, Alpaca(), sub, monkeypatch)
    assert sub.calls[0][0] == "GLD" and manual_rows(db) == []


def _manual_fill(fid, order, symbol, side, qty, at):
    return {"id": fid, "order_id": order, "symbol": symbol, "side": side, "qty": str(qty), "price": "300",
            "transaction_time": at}


def test_a_move_hands_manual_shares_to_the_idea_and_buys_only_the_difference(db, monkeypatch):
    live_idea(db, 1)  # target 66 GLD (20% of $100k at $300)
    store.add_manual_move(db, "main", "GLD", 1, "kevin")
    fills = [_manual_fill("f1", "m", "GLD", "buy", 50, "2026-11-02T14:30:00Z")]
    positions = [{"symbol": "GLD", "qty": "50", "market_value": "15000", "current_price": "300"}]
    alpaca = Alpaca(fills=fills, orders=[{"id": "m", "client_order_id": "manual-1", "submitted_at": "t"}],
                    positions=positions)
    sub = Submit()
    run(db, alpaca, sub, monkeypatch)
    assert [(c[0], c[1], c[2]) for c in sub.calls] == [("GLD", "buy", 16)]
    assert store.labels(db) == {"m": 1}
    run(db, alpaca, Submit(), monkeypatch)  # the second run has nothing left to hand over
    assert len(db.db["order_labels"]) == 1


def test_a_move_takes_shares_whose_label_names_no_idea(db, monkeypatch):
    # The machine door labels every order, with no idea when the caller names none: that is still manual.
    live_idea(db, 1)
    store.add_label(db, "m", None, "api:mac scripts")
    store.add_manual_move(db, "main", "GLD", 1, "kevin")
    fills = [_manual_fill("f1", "m", "GLD", "buy", 50, "2026-11-02T14:30:00Z")]
    positions = [{"symbol": "GLD", "qty": "50", "market_value": "15000", "current_price": "300"}]
    sub = Submit()
    run(db, Alpaca(fills=fills, orders=[{"id": "m", "client_order_id": "ext-1-mirror", "submitted_at": "t"}],
                   positions=positions), sub, monkeypatch)
    assert [(c[0], c[1], c[2]) for c in sub.calls] == [("GLD", "buy", 16)]
    assert store.labels(db) == {"m": 1}


def _ext_stop(oid, symbol, at="2026-11-02T16:23:41.987629123Z", cid=None, qty="1"):
    return {"id": oid, "symbol": symbol, "side": "sell", "qty": qty, "stop_price": "250",
            "client_order_id": cid or f"ext-1-stop-mirror-{oid}", "submitted_at": at}


def test_a_move_cancels_only_the_older_machine_stops_on_its_symbol_before_trading(db, monkeypatch):
    live_idea(db, 1)  # target 66 GLD
    store.add_manual_move(db, "main", "GLD", 1, "kevin")
    fills = [_manual_fill("f1", "m", "GLD", "buy", 50, "2026-11-02T14:30:00Z")]
    positions = [{"symbol": "GLD", "qty": "50", "market_value": "15000", "current_price": "300"}]
    log = []

    def submit(symbol, qty, side, client_order_id, **kw):
        log.append(("submit", symbol, side, qty))
        return {"id": "o1"}

    monkeypatch.setattr(service, "paper_get", Alpaca(
        fills=fills, positions=positions, pending=[_ext_stop("old", "GLD", qty="50")],
        orders=[{"id": "m", "client_order_id": "manual-1", "submitted_at": "t"}]))
    paper_orders_run.run(MORNING, db, submit=submit, closes=closes, fred=None,
                         cancel_machine=lambda oid, cid: log.append(("cancel", oid)))
    assert log == [("cancel", "old"), ("submit", "GLD", "buy", 16)]
    cancelled = [r for r in db.db["paper_orders"] if r["symbol"] == "GLD" and "cancelled" in (r["reason"] or "")]
    assert [(r["idea_id"], r["status"]) for r in cancelled] == [(1, "sent")]


def test_only_a_machine_stop_older_than_the_move_on_its_own_symbol_is_chosen():
    moves = {"GLD": (1, "2026-11-05T09:50:56.023793+00:00")}
    old = _ext_stop("old", "GLD")
    pending = [old, _ext_stop("new", "GLD", at="2026-11-05T15:00:00Z"), _ext_stop("other", "XOM"),
               _ext_stop("bare", "GLD", at=None), _ext_stop("hand", "GLD", cid="manual-stop-1"),
               _ext_stop("idea", "GLD", cid="idea-1-stop-20261105")]
    assert paper_orders_run._stops_under_moves(pending, moves) == [old]


def test_a_stop_that_will_not_cancel_is_flagged_and_the_idea_does_not_buy_against_it(db, monkeypatch):
    live_idea(db, 1)
    store.add_manual_move(db, "main", "GLD", 1, "kevin")
    fills = [_manual_fill("f1", "m", "GLD", "buy", 50, "2026-11-02T14:30:00Z")]
    positions = [{"symbol": "GLD", "qty": "50", "market_value": "15000", "current_price": "300"}]
    monkeypatch.setattr(service, "paper_get", Alpaca(
        fills=fills, positions=positions, pending=[_ext_stop("old", "GLD", qty="50")],
        orders=[{"id": "m", "client_order_id": "manual-1", "submitted_at": "t"}]))

    def refuse(oid, cid):
        raise paper_orders.OrderRejected("HTTP 500")

    sub = Submit()
    _, failed = paper_orders_run.run(MORNING, db, submit=sub, closes=closes, fred=None, cancel_machine=refuse)
    assert failed[1].startswith("stop on GLD")
    assert [(a["symbol"], a["kind"]) for a in db.db["manual_actions"]] == [("GLD", "order")]
    assert sub.calls == []


def test_a_stop_stays_when_no_job_manages_the_receiving_idea(db, monkeypatch):
    live_idea(db, 1)
    store.add_manual_move(db, "main", "GLD", 2, "kevin")  # idea 2 was never switched on
    monkeypatch.setattr(service, "paper_get", Alpaca(pending=[_ext_stop("old", "GLD")]))
    log = []
    paper_orders_run.run(MORNING, db, submit=Submit(), closes=closes, fred=None,
                         cancel_machine=lambda oid, cid: log.append(oid))
    assert log == []


def test_when_the_stop_sold_during_the_cancel_the_idea_does_not_sell_again(db, monkeypatch):
    live_idea(db, 2)
    store.set_auto(db, 2, False, "kevin")
    store.kill(db, 2)
    store.add_manual_move(db, "main", "META", 2, "kevin")
    fills = [_manual_fill("f1", "m", "META", "buy", 2, "2026-11-02T14:30:00Z")]
    positions = [{"symbol": "META", "qty": "2", "market_value": "1200", "current_price": "600"}]

    class StopFilled(Alpaca):
        def __call__(self, path, params=None):
            if path.startswith("/v2/orders/"):
                return {"id": path.rsplit("/", 1)[1], "status": "filled"}
            return super().__call__(path, params)

    monkeypatch.setattr(service, "paper_get", StopFilled(
        fills=fills, positions=positions, pending=[_ext_stop("old", "META", qty="2")],
        orders=[{"id": "m", "client_order_id": "manual-1", "submitted_at": "t"}]))
    sub = Submit()
    paper_orders_run.run(MORNING, db, submit=sub, closes=closes, fred=None, cancel_machine=lambda oid, cid: None)
    assert sub.calls == []
    assert [r["reason"] for r in db.db["paper_orders"] if r["status"] == "skipped"] == [
        "the old stop on META did not cleanly cancel: waiting a day"]


def test_a_stop_that_will_not_cancel_also_stops_a_small_buy_on_that_symbol(db, monkeypatch):
    live_idea(db, 1)
    store.add_manual_move(db, "main", "GLD", 1, "kevin")
    fills = [_manual_fill("f1", "m", "GLD", "buy", 50, "2026-11-02T14:30:00Z")]
    positions = [{"symbol": "GLD", "qty": "50", "market_value": "15000", "current_price": "300"}]
    monkeypatch.setattr(service, "paper_get", Alpaca(
        fills=fills, positions=positions, pending=[_ext_stop("old", "GLD", qty="1")],
        orders=[{"id": "m", "client_order_id": "manual-1", "submitted_at": "t"}]))

    def refuse(oid, cid):
        raise paper_orders.OrderRejected("HTTP 500")

    sub = Submit()
    paper_orders_run.run(MORNING, db, submit=sub, closes=closes, fred=None, cancel_machine=refuse)
    assert sub.calls == []


def test_no_move_means_no_machine_stop_is_touched(db, monkeypatch):
    live_idea(db, 1)
    monkeypatch.setattr(service, "paper_get", Alpaca(pending=[_ext_stop("old", "GLD")]))
    log = []
    paper_orders_run.run(MORNING, db, submit=Submit(), closes=closes, fred=None,
                         cancel_machine=lambda oid, cid: log.append(oid))
    assert log == []


def test_a_move_can_wind_down_manual_shares_through_a_killed_idea(db, monkeypatch):
    live_idea(db, 2)
    store.set_auto(db, 2, False, "kevin")
    store.kill(db, 2)
    store.add_manual_move(db, "main", "META", 2, "kevin")
    fills = [_manual_fill("f1", "m", "META", "buy", 2, "2026-11-02T14:30:00Z")]
    positions = [{"symbol": "META", "qty": "2", "market_value": "1200", "current_price": "600"}]
    sub = Submit()
    run(db, Alpaca(fills=fills, orders=[{"id": "m", "client_order_id": "manual-1", "submitted_at": "t"}],
                   positions=positions), sub, monkeypatch)
    assert [(c[0], c[1], c[2]) for c in sub.calls] == [("META", "sell", 2)]


def test_a_move_on_the_other_book_leaves_this_book_alone(db, monkeypatch):
    live_idea(db, 1)
    store.add_manual_move(db, "big", "GLD", 1, "kevin")
    fills = [_manual_fill("f1", "m", "GLD", "buy", 50, "2026-11-02T14:30:00Z")]
    run(db, Alpaca(fills=fills, orders=[{"id": "m", "client_order_id": "manual-1", "submitted_at": "t"}],
                   positions=[{"symbol": "GLD", "qty": "50", "market_value": "15000", "current_price": "300"}]),
        Submit(), monkeypatch)
    assert store.labels(db) == {}
