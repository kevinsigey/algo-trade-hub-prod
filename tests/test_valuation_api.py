"""Read-API tests for /api/valuation-bands (Phase 0): stubbed supabase,
admin override, latest-per-ticker shape, 404 on an unknown ticker."""
from fastapi.testclient import TestClient

from tradehub.api import admin, main


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def order(self, *_a, **_k):
        self._rows = sorted(self._rows, key=lambda r: r["computed_at"],
                            reverse=True)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _Resp(self._rows)


class _Supa:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _Query(list(self._rows))


ROWS = [
    {"ticker": "AMGN", "tier": "watch", "status": "banded",
     "baseline_verdict": "buy_zone", "computed_at": "2026-11-08T18:00:00Z",
     "bands": {"bear": 250.0, "base": 300.0, "bull": 330.0}},
    {"ticker": "AMGN", "tier": "watch", "status": "banded",
     "baseline_verdict": "neutral", "computed_at": "2026-11-07T18:00:00Z",
     "bands": {"bear": 240.0, "base": 290.0, "bull": 320.0}},
    {"ticker": "GILD", "tier": "watch", "status": "no_full_year_guide",
     "baseline_verdict": "no_bands", "computed_at": "2026-11-08T18:00:00Z",
     "bands": None},
]


def _client(monkeypatch):
    from tradehub.api.dependencies import get_supabase as real_get_supabase
    main.app.dependency_overrides[admin.require_admin] = (
        lambda: {"email": "k@example.com", "is_admin": True})
    main.app.dependency_overrides[real_get_supabase] = lambda: _Supa(ROWS)
    return TestClient(main.app)


def test_list_returns_latest_per_ticker(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/api/valuation-bands")
    assert r.status_code == 200
    rows = r.json()
    assert [x["ticker"] for x in rows] == ["AMGN", "GILD"]
    assert rows[0]["baseline_verdict"] == "buy_zone"  # newest AMGN row wins


def test_get_one_and_404(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/api/valuation-bands/amgn")
    assert r.status_code == 200 and r.json()["ticker"] == "AMGN"
    assert client.get("/api/valuation-bands/ZZZZ").status_code == 404
