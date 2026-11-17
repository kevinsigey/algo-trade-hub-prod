"""Tracker PR 5c — the machine-door tracker gate and the placement
link write (v6 spec Sections 2.4/4/7; tracker design PR 5).

The properties that matter: an order with no play_kind is untouched;
an event-lab entry blocks on a missing opposing case, a missing modal
value, a dead tracker reference, risk above the governing unit (which
forks on grader freshness), or a post-trade cash share under the
floor; play kind c is refused live and recorded as a shadow without
touching the broker; exits are exempt and write no link; and a placed
entry writes exactly one trade_links row keyed by the placed
client_order_id.
"""
from datetime import datetime, timedelta, timezone

import pytest
import requests
from fastapi.testclient import TestClient
from workshop_fake import DB

from tradehub.api import machine_api, machine_keys, main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import alpaca_paper, paper_orders, portfolio_check


@pytest.fixture(autouse=True)
def _no_real_alpaca(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("test reached the real HTTP transport")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(requests, "request", boom)


def _seed_tracker(db, *, fresh=True, cash="50000", equity="100000"):
    now = datetime.now(timezone.utc)
    db.db["tracker_config"] = [{
        "id": 1, "unit_v2_premium": 5000.0, "unit_v2_top": 10000.0,
        "unit_fallback": 1500.0, "play_kind_c_live": False,
        "cash_floor_pct": 10.0}]
    db.db["tracker_health"] = [{
        "id": 1,
        "last_grader_run_at": (now - timedelta(hours=1 if fresh else 30)).isoformat(),
        "last_grader_ok": True}]
    db.db["theses"] = [{"id": 1, "slug": "event-lab"}]
    db.db["forecast_cards"] = [{"id": 7, "thesis_id": 1, "ticker": "NVDA"}]
    return {"cash": cash, "equity": equity,
            "buying_power": "250000", "options_buying_power": "50000"}


@pytest.fixture
def api(monkeypatch):
    db = DB()
    sent = []
    state = {"account": _seed_tracker(db), "positions": []}

    def fake_submit(symbol, qty, side, client_order_id, **kwargs):
        if any(s["client_order_id"] == client_order_id for s in sent):
            raise paper_orders.DuplicateOrder(client_order_id)
        sent.append({"symbol": symbol, "qty": qty, "side": side,
                     "client_order_id": client_order_id, **kwargs})
        return {"id": f"alpaca-{len(sent)}", "status": "accepted"}

    def fake_paper_get(path, params=None, **kw):
        if path == "/v2/account":
            return state["account"]
        if path == "/v2/positions":
            return state["positions"]
        return []

    monkeypatch.setattr(paper_orders, "submit", fake_submit)
    monkeypatch.setattr(alpaca_paper, "latest_price", lambda symbol: 100.0)
    monkeypatch.setattr(alpaca_paper, "paper_get", fake_paper_get)

    def _unreadable_book(book=None):
        raise alpaca_paper.AccountNotConnected("test fixture: no readable book")
    monkeypatch.setattr(portfolio_check, "positions_by_underlying",
                        _unreadable_book)
    monkeypatch.setattr(machine_api, "LIMITER", machine_api.RateLimiter())
    monkeypatch.setenv("TRADEHUB_MACHINE_ORDERS", "on")
    main.app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(main.app), db, sent, state
    main.app.dependency_overrides.clear()


def _key(db):
    _, plaintext = machine_keys.create_key(db, "mac scripts", ["orders:place"])
    return {"Authorization": f"Bearer {plaintext}"}


def _post(client, headers, **over):
    body = {"symbol": "NVDA", "qty": 10, "side": "buy",
            "client_order_id": "run-1", "reason": "event lab entry",
            "play_kind": "a", "modal_value": 1.8,
            "opposing_case_ref": "research/nvda.md#opposing-case"}
    body.update(over)
    return client.post("/api/v1/orders", json=body, headers=headers)


def _links(db):
    return db.db.get("trade_links", [])


def test_a_plain_order_is_untouched(api):
    client, db, sent, _ = api
    r = client.post("/api/v1/orders", headers=_key(db), json={
        "symbol": "XLE", "qty": 2, "side": "buy", "client_order_id": "p-1",
        "reason": "plain discretionary"})
    assert r.status_code == 200 and len(sent) == 1
    assert _links(db) == []


def test_a_full_event_lab_entry_places_and_links(api):
    client, db, sent, _ = api
    r = _post(client, _key(db), forecast_id=7)
    assert r.status_code == 200, r.text
    assert len(sent) == 1
    links = _links(db)
    assert len(links) == 1
    link = links[0]
    assert link["client_order_id"] == "ext-1-run-1"
    assert link["book"] == "main" and link["play_kind"] == "a"
    assert link["forecast_id"] == 7 and link["thesis_id"] == 1  # via the card
    assert link["modal_value"] == 1.8 and link["shadow"] is False
    assert r.json()["tracker"]["unit_source"] == "schedule_v2"


def test_missing_opposing_case_and_modal_block(api):
    client, db, sent, _ = api
    r = _post(client, _key(db), opposing_case_ref=None)
    assert r.status_code == 422 and "opposing_case_ref" in r.text
    r = _post(client, _key(db), client_order_id="run-2", modal_value=None)
    assert r.status_code == 422 and "modal_value" in r.text
    assert sent == [] and _links(db) == []


def test_a_dead_forecast_reference_blocks(api):
    client, db, sent, _ = api
    r = _post(client, _key(db), forecast_id=99)
    assert r.status_code == 422 and "no forecast card" in r.text
    assert sent == []


def test_the_unit_forks_on_grader_freshness(api):
    client, db, sent, _ = api
    # fresh: unit 5000, a $2,000 notional entry passes
    r = _post(client, _key(db), qty=20)
    assert r.status_code == 200, r.text
    # stale: the same shape now faces the $1,500 fallback and blocks
    db.db["tracker_health"][0]["last_grader_run_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    r = _post(client, _key(db), qty=20, client_order_id="run-2")
    assert r.status_code == 422 and "governing unit" in r.text
    assert len(sent) == 1


def test_declared_risk_is_floored_by_the_computable_figure(api):
    client, db, sent, _ = api
    # A stop alone prices risk-to-stop: 100 @ $100 against a $60 stop
    # risks $4,000, under the fresh $5,000 unit.
    r = _post(client, _key(db), qty=100, stop_loss_price=60.0)
    assert r.status_code == 200, r.text
    # A declared figure beside the stop may agree or raise, never
    # lower: declared $4,000 = the risk-to-stop, passes the same way.
    r = _post(client, _key(db), qty=100, client_order_id="run-2",
              risk_amount=4000.0, stop_loss_price=60.0)
    assert r.status_code == 200, r.text
    # Claude's #549 hole: a declared $0 on a $10,000 buy with NO stop
    # was trusted and passed. With no stop the computable figure is
    # the full notional, and the declared figure cannot lower it.
    r = _post(client, _key(db), qty=100, client_order_id="run-3",
              risk_amount=0.0)
    assert r.status_code == 422 and "governing unit" in r.text
    # A declared figure under the risk-to-stop floors at the stop:
    # declared $100 against the $4,000 risk-to-stop passes while the
    # unit is $5,000, and blocks once the stale-grader fallback drops
    # the unit to $1,500 -- on trust it would have passed both.
    r = _post(client, _key(db), qty=100, client_order_id="run-4",
              risk_amount=100.0, stop_loss_price=60.0)
    assert r.status_code == 200, r.text
    db.db["tracker_health"][0]["last_grader_run_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    r = _post(client, _key(db), qty=100, client_order_id="run-5",
              risk_amount=100.0, stop_loss_price=60.0)
    assert r.status_code == 422 and "governing unit" in r.text
    assert len(sent) == 3


def test_the_cash_floor_blocks_an_entry(api):
    client, db, sent, state = api
    state["account"]["cash"] = "10500"  # 10.5% of equity; a $1,000 buy breaches 10%
    r = _post(client, _key(db))
    assert r.status_code == 422 and "cash floor" in r.text
    assert sent == [] and _links(db) == []


def test_kind_c_live_is_refused_and_shadow_is_recorded_not_placed(api):
    client, db, sent, _ = api
    r = _post(client, _key(db), play_kind="c")
    assert r.status_code == 422 and "shadow-only" in r.text
    r = _post(client, _key(db), play_kind="c", shadow=True,
              client_order_id="run-2")
    assert r.status_code == 200, r.text
    assert r.json()["shadow"] is True
    assert sent == []  # the broker never saw it
    links = _links(db)
    assert len(links) == 1 and links[0]["shadow"] is True
    assert links[0]["play_kind"] == "c"


def test_an_exit_is_exempt_and_writes_no_link(api):
    client, db, sent, state = api
    # hold 10 NVDA, then sell them as a tracker-tagged exit with none of
    # the entry evidence attached
    state["positions"] = [{"symbol": "NVDA", "qty": "10", "side": "long"}]
    r = client.post("/api/v1/orders", headers=_key(db), json={
        "symbol": "NVDA", "qty": 10, "side": "sell",
        "client_order_id": "exit-1", "reason": "close the play",
        "play_kind": "a"})
    assert r.status_code == 200, r.text
    assert r.json()["exit"]["is_exit"] is True
    assert _links(db) == []


def test_preflight_reports_the_tracker_block_without_placing(api):
    client, db, sent, _ = api
    r = client.post("/api/v1/orders/preflight", headers=_key(db), json={
        "symbol": "NVDA", "qty": 10, "side": "buy", "client_order_id": "p-1",
        "reason": "event lab entry", "play_kind": "a", "modal_value": 1.8})
    assert r.status_code == 200, r.text
    checks = {c["name"]: c for c in r.json()["checks"]}
    assert checks["tracker_opposing_case"]["ok"] is False
    assert sent == [] and _links(db) == []


# -- the options path: risk is the computed max loss, never declared ---------

LONG_CALL = "SPY261113C00580000"
SHORT_CALL = "SPY261113C00585000"


def _option_spec(**over):
    spec = {"legs": [
                {"symbol": LONG_CALL, "side": "buy", "qty": 4,
                 "position_intent": "buy_to_open"},
                {"symbol": SHORT_CALL, "side": "sell", "qty": 4,
                 "position_intent": "sell_to_open"}],
            "order_type": "limit", "time_in_force": "day",
            "limit_price": 2.00, "reason": "event lab premium play",
            "play_kind": "a", "modal_value": 1.8,
            "opposing_case_ref": "research/spy.md#opposing-case"}
    spec.update(over)
    return spec


def test_the_option_gate_uses_computed_max_loss(monkeypatch):
    from tradehub.portfolio import option_orders, options as options_mod

    db = DB()
    _seed_tracker(db)
    monkeypatch.setenv("TRADEHUB_MACHINE_ORDERS", "on")
    monkeypatch.setattr(option_orders, "contract",
                        lambda symbol, book=None: {"symbol": symbol})
    monkeypatch.setattr(option_orders, "positions_map", lambda book=None: {})
    monkeypatch.setattr(option_orders, "options_buying_power",
                        lambda book=None: 50000.0)
    monkeypatch.setattr(options_mod, "fetch_mid",
                        lambda symbol, book=None: {LONG_CALL: 3.0,
                                                   SHORT_CALL: 2.0}[symbol])
    monkeypatch.setattr(
        alpaca_paper, "paper_get",
        lambda path, params=None, **kw: (
            {"cash": "50000", "equity": "100000",
             "options_buying_power": "50000"}
            if path == "/v2/account" else []))

    def _unreadable_book(book=None):
        raise alpaca_paper.AccountNotConnected("test fixture")
    monkeypatch.setattr(portfolio_check, "positions_by_underlying",
                        _unreadable_book)
    key = {"id": 1, "book": "main", "label": "test", "max_qty": 100,
           "max_notional": 25000.0, "daily_cap": 50}

    # debit spread: 4 spreads at a 2.00 net limit -> max loss $800 <= $5,000
    out = machine_api.validate_order(db, key, _option_spec())
    assert out["refusal"] is None, out["checks"]
    assert out["tracker"]["risk"] == 800.0
    assert out["tracker"]["unit_source"] == "schedule_v2"

    # the same structure at a 20.00 limit risks $8,000: over the unit,
    # and a declared risk_amount does not soften computed math
    out = machine_api.validate_order(
        db, key, _option_spec(limit_price=20.00, risk_amount=100.0))
    assert out["refusal"] is not None
    assert out["refusal"][0] == "tracker"
    assert "governing unit" in out["refusal"][2]


# -- CodeRabbit round (PR #549): the shadow edges and the stop side ---------

def test_shadow_without_a_play_kind_is_refused(api):
    client, db, sent, _ = api
    r = client.post("/api/v1/orders", headers=_key(db), json={
        "symbol": "NVDA", "qty": 1, "side": "buy", "client_order_id": "s-0",
        "reason": "record only", "shadow": True})
    # Without a play_kind the gate never engages: the order would have
    # placed LIVE. The refusal is the whole point of a shadow record.
    assert r.status_code == 422
    assert sent == [] and _links(db) == []


def test_a_shadow_exit_is_refused(api):
    client, db, sent, state = api
    state["positions"] = [{"symbol": "NVDA", "qty": "10", "side": "long"}]
    r = _post(client, _key(db), side="sell", qty=10, client_order_id="s-1",
              shadow=True)
    assert r.status_code == 422
    assert sent == [] and _links(db) == []


def test_a_stop_on_the_gain_side_does_not_shrink_risk(api):
    client, db, sent, _ = api
    # Buy at the fixture's 100.0 with the stop ABOVE entry: the stop
    # limits nothing, so risk falls back to the $10,000 notional and
    # the $5,000 unit blocks. Priced off the stop it would read $1.
    r = _post(client, _key(db), qty=100, stop_loss_price=100.01,
              client_order_id="s-2")
    assert r.status_code == 422
    assert sent == []
    # The same order with the stop on the loss side risks $1,000.
    r = _post(client, _key(db), qty=100, stop_loss_price=90.0,
              client_order_id="s-3")
    assert r.status_code == 200 and len(sent) == 1


def test_a_failed_shadow_link_write_is_an_error(api, monkeypatch):
    from tradehub.tracker import links as tracker_links

    def boom(*args, **kwargs):
        raise RuntimeError("db down")
    monkeypatch.setattr(tracker_links, "record_link", boom)
    client, db, sent, _ = api
    r = _post(client, _key(db), play_kind="c", shadow=True,
              client_order_id="s-4")
    # A shadow request's only effect is its link: a 200 here would
    # report a record that does not exist.
    assert r.status_code == 503
    assert sent == [] and _links(db) == []


def test_a_duplicate_retry_repairs_a_failed_link(api, monkeypatch):
    from tradehub.tracker import links as tracker_links

    real = tracker_links.record_link
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return real(*args, **kwargs)
    monkeypatch.setattr(tracker_links, "record_link", flaky)
    client, db, sent, _ = api
    headers = _key(db)
    r = _post(client, headers)
    assert r.status_code == 200 and r.json()["link_note"]
    assert _links(db) == []
    failed = [e for e in db.db.get("api_key_events", [])
              if e["outcome"] == "tracker_link_failed"]
    assert len(failed) == 1  # the failure is in the audit trail
    # The retry hits the broker's duplicate guard — and repairs the
    # link on its way to the 409.
    r = _post(client, headers)
    assert r.status_code == 409
    assert len(_links(db)) == 1
    assert _links(db)[0]["client_order_id"] == "ext-1-run-1"
