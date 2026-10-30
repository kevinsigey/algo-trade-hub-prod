from datetime import UTC, datetime

import pytest
import requests
from fastapi.testclient import TestClient

from tradehub.api import main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import service
from tradehub.portfolio.alpaca_paper import AccountNotConnected
from tradehub.scripts import portfolio_snapshot


class FakeQuery:
    def __init__(self, store, table):
        self.store, self.table, self.filters = store, table, []

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def order(self, col):
        self.col = col
        return self

    def range(self, lo, hi):
        self.lo, self.hi = lo, hi
        return self

    def insert(self, row):
        self.store.setdefault(self.table, []).append(row)
        return self

    def execute(self):
        rows = [r for r in self.store.get(self.table, []) if all(r[c] == v for c, v in self.filters)]
        rows.sort(key=lambda r: r[getattr(self, "col", "taken_at")])
        data = rows[self.lo:self.hi + 1] if hasattr(self, "lo") else rows
        return type("R", (), {"data": data})()


class FakeSupabase:
    def __init__(self, snapshots=()):
        self.store = {"portfolio_snapshots": list(snapshots)}

    def table(self, name):
        return FakeQuery(self.store, name)


def snap(t, account, equity, spy=500.0):
    return {"taken_at": t, "account_number": account, "equity": equity, "cash": equity, "spy_price": spy}


ACCOUNT = {"account_number": "PA2", "equity": "104820", "cash": "41200"}
POSITIONS = [{"symbol": "GLD", "qty": "60", "side": "long", "market_value": "21900", "unrealized_pl": "640"}]


def alpaca(account=ACCOUNT, positions=POSITIONS, fills=()):
    def fake(path, params=None):
        return {"/v2/account": account, "/v2/positions": positions,
                "/v2/account/activities/FILL": list(fills)}[path]
    return fake


@pytest.fixture
def client_with(monkeypatch):
    def make(supa):
        main.app.dependency_overrides[get_supabase] = lambda: supa
        return TestClient(main.app)
    monkeypatch.setattr(service, "latest_spy_price", lambda: 510.5)
    yield make
    main.app.dependency_overrides.clear()


def raise_(exc):
    def f(*a, **k):
        raise exc
    return f


def test_portfolio_not_connected_is_200(client_with, monkeypatch):
    monkeypatch.setattr(service, "paper_get", raise_(AccountNotConnected("no keys")))
    r = client_with(FakeSupabase()).get("/api/portfolio")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "not_connected" and body["positions"] == [] and body["scoreboard"]["equity"] is None


def test_portfolio_pre_start_when_account_number_unset(client_with, monkeypatch):
    monkeypatch.delenv("PORTFOLIO_ACCOUNT_NUMBER", raising=False)
    monkeypatch.setattr(service, "paper_get", alpaca())
    body = client_with(FakeSupabase()).get("/api/portfolio").json()
    assert body["state"] == "pre_start"
    assert body["scoreboard"]["equity"] == 104820
    assert [p["symbol"] for p in body["positions"]] == ["GLD", "Cash"]
    assert body["composition"][0]["idea"] == "No idea yet (manual)"


def test_portfolio_live_uses_snapshots_of_this_account_only(client_with, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_ACCOUNT_NUMBER", "PA2")
    monkeypatch.setattr(service, "paper_get", alpaca())
    supa = FakeSupabase([snap("2026-10-01T15:00:00+00:00", "PA1", 50_000),
                         snap("2026-11-02T15:00:00+00:00", "PA2", 100_000, 500.0)])
    body = client_with(supa).get("/api/portfolio").json()
    assert body["state"] == "live"
    assert body["scoreboard"]["start_at"] == "2026-11-02T15:00:00+00:00"
    assert body["scoreboard"]["return_pct"] == pytest.approx(4.82)
    assert body["scoreboard"]["spy_return_pct"] == pytest.approx(2.1)
    assert len(body["curve"]) == 2


def test_portfolio_stale_when_alpaca_times_out(client_with, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_ACCOUNT_NUMBER", "PA2")
    monkeypatch.setattr(service, "paper_get", raise_(requests.Timeout("slow")))
    supa = FakeSupabase([snap("2026-11-02T15:00:00+00:00", "PA2", 100_000),
                         snap("2026-11-03T15:00:00+00:00", "PA2", 101_000)])
    body = client_with(supa).get("/api/portfolio").json()
    assert body["state"] == "stale"
    assert body["as_of"] == "2026-11-03T15:00:00+00:00"
    assert body["scoreboard"]["equity"] == 101_000


def test_win_rate_comes_from_closed_trades(client_with, monkeypatch):
    fills = [{"id": "1", "symbol": "GLD", "side": "buy", "qty": "10", "price": "200", "transaction_time": "2026-11-02T15:00:00Z"},
             {"id": "2", "symbol": "GLD", "side": "sell", "qty": "10", "price": "210", "transaction_time": "2026-11-03T15:00:00Z"}]
    monkeypatch.setattr(service, "paper_get", alpaca(fills=fills))
    body = client_with(FakeSupabase()).get("/api/portfolio").json()
    assert body["scoreboard"]["win_rate"] == pytest.approx(100.0)


def test_closed_endpoint_newest_first_and_not_connected(client_with, monkeypatch):
    fills = [{"id": str(i), "symbol": s, "side": side, "qty": "1", "price": p, "transaction_time": t}
             for i, (s, side, p, t) in enumerate([("A", "buy", "10", "2026-11-02T15:00:00Z"),
                                                  ("A", "sell", "12", "2026-11-03T15:00:00Z"),
                                                  ("B", "buy", "10", "2026-11-02T15:00:00Z"),
                                                  ("B", "sell", "9", "2026-11-05T15:00:00Z")])]
    monkeypatch.setattr(service, "paper_get", alpaca(fills=fills))
    c = client_with(FakeSupabase())
    body = c.get("/api/portfolio/closed").json()
    assert body["state"] == "live" and [t["symbol"] for t in body["trades"]] == ["B", "A"]
    monkeypatch.setattr(service, "paper_get", raise_(AccountNotConnected("no keys")))
    assert c.get("/api/portfolio/closed").json() == {"state": "not_connected", "as_of": None, "trades": []}


def test_fill_paging_follows_page_token(monkeypatch):
    calls = []

    def fake(path, params=None):
        calls.append(dict(params))
        n = 100 if len(calls) == 1 else 3
        return [{"id": f"{len(calls)}-{i}"} for i in range(n)]
    monkeypatch.setattr(service, "paper_get", fake)
    assert len(service._fills()) == 103
    assert calls[1]["page_token"] == "1-99"


MONDAY_10_CT = datetime(2026, 11, 2, 16, 0, tzinfo=UTC)


def test_snapshot_job_inserts_one_row(monkeypatch):
    monkeypatch.setattr(service, "paper_get", alpaca())
    monkeypatch.setattr(service, "latest_spy_price", lambda: 510.5)
    supa = FakeSupabase()
    assert portfolio_snapshot.main(MONDAY_10_CT, supa) == 0
    assert supa.store["portfolio_snapshots"] == [{"taken_at": MONDAY_10_CT.isoformat(), "account_number": "PA2",
                                                  "equity": 104820.0, "cash": 41200.0, "spy_price": 510.5}]


def test_snapshot_job_skips_when_not_connected_or_closed(monkeypatch):
    monkeypatch.setattr(service, "paper_get", raise_(AccountNotConnected("no keys")))
    supa = FakeSupabase()
    assert portfolio_snapshot.main(MONDAY_10_CT, supa) == 0
    assert portfolio_snapshot.main(datetime(2026, 11, 1, 16, 0, tzinfo=UTC), supa) == 0  # Sunday
    assert supa.store["portfolio_snapshots"] == []
