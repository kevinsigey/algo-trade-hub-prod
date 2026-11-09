"""The portfolio check at its three doors (Kevin, 2026-11-09): the machine
preflight/placement gate, idea activations, and the Portfolio card endpoint --
one engine, so the three can never disagree.

The book below is the cohesion report's shape at $900k invested: GLD 13.0% of
invested (over its 12% cap, mid-trim), ballast ~5.6% a sleeve, T8 6%, index 20%.
"""
import pytest
import requests
from fastapi.testclient import TestClient
from workshop_fake import DB

from tradehub.api import admin, machine_api, machine_keys, main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import alpaca_paper, options as options_mod, paper_orders

BOOK_MV = {
    "GLD": 117_000.0, "XLP": 50_000.0, "XLU": 50_000.0, "XLRE": 50_000.0,
    "XLV": 50_000.0, "VNQ": 50_000.0, "DBC": 50_000.0, "USO": 50_000.0,
    "DLTR": 36_000.0, "DG": 36_000.0, "MO": 36_000.0, "WSM": 36_000.0,
    "SPY": 110_000.0, "VOO": 74_000.0,
    "AAPL": 9_000.0, "NVDA": 9_000.0, "MSFT": 9_000.0, "AVGO": 9_000.0,
    "MU": 9_000.0, "TSM": 9_000.0, "IBIT": 34_000.0,
    "TXN": 9_000.0, "INTC": 8_000.0,
}
PRICES = {"GLD": 378.0, "XLP": 50.0}
ACCOUNT = {"buying_power": "500000", "options_buying_power": "500000",
           "equity": "1050000", "cash": "150000"}

LONG_PUT = "SPY261113P00570000"
SHORT_PUT = "SPY261113P00565000"
IBIT_CALL = "IBIT261204C00050000"
CONTRACTS = {LONG_PUT, SHORT_PUT, IBIT_CALL}
MIDS = {LONG_PUT: 2.50, SHORT_PUT: 1.50, IBIT_CALL: 1.20}


def _http_error(code: int) -> requests.HTTPError:
    err = requests.HTTPError(f"HTTP {code}")
    err.response = requests.Response()
    err.response.status_code = code
    return err


@pytest.fixture
def api(monkeypatch):
    db = DB()
    state = {"positions": [{"symbol": s, "qty": "10", "market_value": str(mv),
                            "current_price": "100"}
                           for s, mv in BOOK_MV.items()],
             "account": dict(ACCOUNT)}
    sent = []

    def fake_submit(symbol, qty, side, client_order_id, **kwargs):
        sent.append({"symbol": symbol, "qty": qty, "side": side,
                     "client_order_id": client_order_id, **kwargs})
        return {"id": f"alpaca-{len(sent)}", "status": "accepted"}

    def fake_paper_get(path, params=None, **kw):
        if path.startswith("/v2/options/contracts/"):
            symbol = path.rsplit("/", 1)[-1]
            if symbol in CONTRACTS:
                return {"symbol": symbol, "tradable": True, "status": "active"}
            raise _http_error(404)
        if path == "/v2/account":
            return state["account"]
        if path == "/v2/positions":
            return state["positions"]
        if path == "/v2/orders":
            return []
        return {}

    monkeypatch.setattr(alpaca_paper, "paper_get", fake_paper_get)
    monkeypatch.setattr(alpaca_paper, "latest_price",
                        lambda symbol, **kw: PRICES.get(symbol, 100.0))
    monkeypatch.setattr(paper_orders, "submit", fake_submit)
    monkeypatch.setattr(options_mod, "fetch_mid", lambda symbol, **kw: MIDS.get(symbol))
    monkeypatch.setattr(machine_api, "LIMITER", machine_api.RateLimiter())
    monkeypatch.setenv("TRADEHUB_MACHINE_ORDERS", "on")
    main.app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(main.app), db, sent, state
    main.app.dependency_overrides.clear()


def _key(db, **caps):
    caps.setdefault("max_notional", 250_000)
    _, plaintext = machine_keys.create_key(
        db, "pc test", ["orders:place", "orders:read", "portfolio:read"], **caps)
    return {"Authorization": f"Bearer {plaintext}"}


def _preflight(client, headers, **over):
    body = {"symbol": "GLD", "qty": 14, "side": "buy", "client_order_id": "pf-1"}
    body.update(over)
    return client.post("/api/v1/orders/preflight", json=body, headers=headers)


# ── the preflight gate (acceptance a + b) ──────────────────────────────────────

def test_preflight_blocks_a_gld_buy_over_its_cap_naming_cap_and_weight(api):
    client, db, sent, _ = api
    r = _preflight(client, _key(db))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    gate = next(c for c in body["checks"] if c["name"] == "portfolio_check")
    assert gate["ok"] is False and gate["blocking"] is True
    assert "12" in gate["detail"] and "13.5" in gate["detail"]
    block = body["portfolio_check"]
    assert block["outcome"] == "block" and block["thesis"]["id"] == "t4_ballast"


def test_placement_refuses_what_preflight_blocked_and_audits_it(api):
    client, db, sent, _ = api
    headers = _key(db)
    r = client.post("/api/v1/orders",
                    json={"symbol": "GLD", "qty": 14, "side": "buy",
                          "client_order_id": "pf-1"}, headers=headers)
    assert r.status_code == 422
    assert r.json()["detail"].startswith("portfolio check:")
    assert sent == []
    outcomes = [e["outcome"] for e in db.db[machine_keys.EVENTS]]
    assert "refused:portfolio_check" in outcomes


def _gold_under_its_flag(state):
    """The fixture book's gold sits over its 12% flag at rest (13.0%), so every
    order on it warns on gold; tests that want a clean pass rest it under."""
    state["positions"] = [{**row, "market_value": "90000"} if row["symbol"] == "GLD" else row
                          for row in state["positions"]]


def test_preflight_passes_a_conforming_order_with_the_block_visible(api):
    client, db, _, state = api
    _gold_under_its_flag(state)
    r = _preflight(client, _key(db), symbol="XLP", qty=10, client_order_id="pf-2")
    body = r.json()
    assert body["ok"] is True
    assert body["portfolio_check"]["outcome"] == "pass"
    gate = next(c for c in body["checks"] if c["name"] == "portfolio_check")
    assert gate["ok"] is True and gate["blocking"] is False
    assert body["portfolio_check"]["weights"]["sleeves"]["t4_ballast"] > 50.0


def test_a_gld_sell_places_because_exits_reduce_the_breach(api):
    client, db, sent, _ = api
    r = client.post("/api/v1/orders",
                    json={"symbol": "GLD", "qty": 50, "side": "sell",
                          "client_order_id": "trim-1"}, headers=_key(db))
    assert r.status_code == 200 and len(sent) == 1
    assert r.json()["portfolio_check"]["outcome"] != "block"


def test_every_preflight_records_its_outcome(api):
    client, db, _, _ = api
    _preflight(client, _key(db))
    rows = db.db["portfolio_check_events"]
    assert len(rows) == 1
    assert rows[0]["source"] == "machine_preflight" and rows[0]["outcome"] == "block"
    assert rows[0]["symbol"] == "GLD" and rows[0]["book"] == "main"


def test_a_stored_targets_edit_changes_the_preflight_verdict(api):
    client, db, _, _ = api
    db.db["portfolio_targets"] = [{"scope": "global", "config": {
        "name_overrides": {"GLD": {"target_pct": 11.0, "max_pct": 20.0}}}}]
    r = _preflight(client, _key(db))
    assert r.json()["ok"] is True
    assert r.json()["portfolio_check"]["outcome"] != "block"


# ── Kevin's ruling (2026-11-09): exits win over the member floor ──────────────

def _dbc_at_the_floor_edge(state):
    """Rest the fixture book so DBC (a T4 ballast member) sits just over its 2%
    floor with enough shares held for a classified exit: DBC $20k of $843k
    invested = 2.4%, 100 shares held; GLD rested under its gold flag so the
    floor warning is the check's headline."""
    _gold_under_its_flag(state)
    state["positions"] = [
        {**row, "qty": "100", "market_value": "20000"} if row["symbol"] == "DBC" else row
        for row in state["positions"]]


def test_preflight_an_exit_trim_below_the_floor_passes_with_a_named_warning(api):
    client, db, _, state = api
    _dbc_at_the_floor_edge(state)
    r = _preflight(client, _key(db), symbol="DBC", qty=50, side="sell",
                   client_order_id="floor-exit-1")   # -$5k -> 15k/838k = 1.8%
    body = r.json()
    assert body["ok"] is True
    assert body["exit"]["is_exit"] is True           # the #440 book math, not a claim
    block = body["portfolio_check"]
    assert block["outcome"] == "warn" and block["blocks"] == []
    warn = next(w for w in block["warnings"] if "DBC" in w["detail"])
    assert warn["rule"] == "member_floor_exit"
    assert "floor" in warn["detail"] and "exit" in warn["detail"]
    assert "floor" in block["detail"]                # the card feed's headline names it
    rows = db.db["portfolio_check_events"]
    assert rows[-1]["outcome"] == "warn" and "floor" in rows[-1]["detail"]


def test_preflight_the_same_trim_oversold_is_not_an_exit_and_still_blocks(api):
    client, db, _, state = api
    _dbc_at_the_floor_edge(state)
    r = _preflight(client, _key(db, max_qty=1000), symbol="DBC", qty=150, side="sell",
                   client_order_id="floor-over-1")   # 150 > the 100 held: no exit
    body = r.json()
    assert body["ok"] is False
    assert body["exit"]["is_exit"] is False
    block = body["portfolio_check"]
    assert block["outcome"] == "block"
    assert any(b["rule"] == "member_floor" and "DBC" in b["detail"]
               for b in block["blocks"])


# ── options through the same gate ──────────────────────────────────────────────

def test_a_spy_spread_preflight_carries_the_portfolio_block(api):
    client, db, _, state = api
    _gold_under_its_flag(state)
    r = client.post("/api/v1/orders/preflight", headers=_key(db), json={
        "client_order_id": "spread-1", "order_type": "limit", "limit_price": 1.20,
        "legs": [{"symbol": LONG_PUT, "side": "buy", "qty": 1},
                 {"symbol": SHORT_PUT, "side": "sell", "qty": 1}]})
    body = r.json()
    assert body["portfolio_check"]["outcome"] == "pass"
    assert body["portfolio_check"]["thesis"]["id"] == "t3_index"


def test_an_ibit_call_buy_blocks_as_exit_only(api):
    client, db, _, _ = api
    r = client.post("/api/v1/orders/preflight", headers=_key(db), json={
        "symbol": IBIT_CALL, "qty": 1, "side": "buy", "client_order_id": "ibit-1",
        "order_type": "limit", "limit_price": 1.10})
    body = r.json()
    assert body["ok"] is False
    assert body["portfolio_check"]["outcome"] == "block"
    assert "exit-only" in body["portfolio_check"]["blocks"][0]["detail"]


# ── the card endpoint (acceptance c, shape) ────────────────────────────────────

def test_the_card_reads_the_same_engine_state(api):
    client, db, _, _ = api
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    try:
        r = client.get("/api/portfolio/portfolio-check?book=main")
    finally:
        main.app.dependency_overrides.pop(admin.require_admin, None)
    assert r.status_code == 200
    body = r.json()
    assert body["invested"] == 900_000.0
    assert body["cash_pct"] == pytest.approx(150_000 / 1_050_000 * 100, abs=0.01)
    ballast = next(s for s in body["sleeves"] if s["id"] == "t4_ballast")
    gld = next(m for m in ballast["members"] if m["symbol"] == "GLD")
    assert gld["weight_pct"] == pytest.approx(13.0, abs=0.01)
    assert gld["target_pct"] == 11.0 and gld["max_pct"] == 12.0 and gld["status"] == "over"
    assert body["clusters"]["gold"]["pct"] == pytest.approx(13.0, abs=0.01)
    t8 = next(s for s in body["sleeves"] if s["id"] == "t8_ai")
    assert t8["weight_pct"] == pytest.approx(6.0, abs=0.01) and t8["status"] == "ok"


# ── activations: the same gate, earlier (acceptance d) ─────────────────────────

SPEC_GLD = {"title": "Gold when rates rise", "hold": ["GLD"], "otherwise": "SPY",
            "claim": "beats_benchmark_when",
            "when": {"source": "fred", "series": "DGS10", "measure": "change",
                     "op": ">", "threshold": 0.25}}
SPEC_XLP = {**SPEC_GLD, "title": "Staples", "hold": ["XLP"]}
PASS_RESULT = {"verdict": "PASS", "headline": "Did what it claims.", "data_end": "2026-10-29",
               "shuffle": {"p": 0.001, "bar": 0.05},
               "walk_forward": {"held": 4, "of": 4, "folds": []}}


@pytest.fixture
def workshop(monkeypatch):
    db = DB()
    main.app.dependency_overrides[get_supabase] = lambda: db
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: ("closes", tuple(tickers)))
    monkeypatch.setattr(main, "workshop_fred", lambda series, start: "series")
    monkeypatch.setattr(main, "run_test", lambda *a, **k: PASS_RESULT)
    monkeypatch.setattr(main, "workshop_daily_frame",
                        lambda spec, closes, fred, div_yields=None: "frame")
    gate = {"status": "ready", "new_days": 70, "needed": 63,
            "claim": {"holds": True}, "size_ok": True, "reasons": []}
    monkeypatch.setattr(main, "gate_check",
                        lambda spec, frame, data_end, size_pct:
                        {**gate, "size_ok": None if size_pct is None else gate["size_ok"]})

    def fake_paper_get(path, params=None, **kw):
        if path == "/v2/account":
            return {"equity": "900000", "cash": "0", "buying_power": "900000"}
        if path == "/v2/positions":
            return [{"symbol": s, "qty": "10", "market_value": str(mv)}
                    for s, mv in BOOK_MV.items()]
        return {}

    monkeypatch.setattr(alpaca_paper, "paper_get", fake_paper_get)
    yield TestClient(main.app), db
    main.app.dependency_overrides.clear()


def _passed_idea(client, spec):
    idea = client.post("/api/workshop/ideas",
                       json={"title": spec["title"], "plain_words": "x"}).json()
    run = client.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": spec}).json()
    client.post(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/save")
    return idea["id"], run["id"]


def test_a_breaching_go_live_refuses_and_lands_in_manual_actions(workshop):
    client, db = workshop
    idea_id, _ = _passed_idea(client, SPEC_GLD)
    r = client.post(f"/api/workshop/ideas/{idea_id}/live", json={"size_pct": 50})
    assert r.status_code == 409
    assert "portfolio check" in r.json()["detail"]
    actions = [a for a in db.db.get("manual_actions", []) if a["kind"] == "portfolio_check"]
    assert len(actions) == 1
    assert actions[0]["book"] == "main" and actions[0]["idea_id"] == idea_id
    # state defaults to 'open' in the table itself (migration 20261102000006);
    # the fake DB applies no column defaults, so an absent key is that default.
    assert actions[0].get("state", "open") == "open"
    assert "GLD" in actions[0]["detail"] and "12" in actions[0]["detail"]
    idea = next(i for i in db.db["ideas"] if i["id"] == idea_id)
    assert not idea.get("live_at")


def test_a_conforming_go_live_proceeds(workshop):
    client, db = workshop
    idea_id, _ = _passed_idea(client, SPEC_XLP)
    r = client.post(f"/api/workshop/ideas/{idea_id}/live", json={"size_pct": 2})
    assert r.status_code == 200
    idea = next(i for i in db.db["ideas"] if i["id"] == idea_id)
    assert idea.get("live_at")
    assert [a for a in db.db.get("manual_actions", []) if a["kind"] == "portfolio_check"] == []


def test_auto_on_a_breaching_book_activation_refuses_and_queues(workshop):
    client, db = workshop
    idea_id, run_id = _passed_idea(client, SPEC_GLD)
    db.db["book_activations"] = [{"book": "big", "idea_id": idea_id,
                                  "live_at": "2026-11-08T00:00:00+00:00",
                                  "live_run_id": run_id, "size_pct": 50.0,
                                  "auto_orders": False, "killed_at": None}]
    r = client.post(f"/api/workshop/ideas/{idea_id}/auto",
                    json={"on": True, "book": "big"})
    assert r.status_code == 409
    actions = [a for a in db.db.get("manual_actions", []) if a["kind"] == "portfolio_check"]
    assert len(actions) == 1 and actions[0]["book"] == "big"
    assert not db.db["book_activations"][0]["auto_orders"]
