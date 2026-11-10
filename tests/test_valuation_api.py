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
    # Reliability pass F1: the payload is a stamped envelope -- one
    # snapshot's sheets, never a bare list. The stub has no completed
    # snapshot, so the stamp is null (legacy fallback, honestly labeled)
    # and the sheets are the latest-per-ticker rows.
    client = _client(monkeypatch)
    r = client.get("/api/valuation-bands")
    assert r.status_code == 200
    body = r.json()
    assert body["snapshot"] is None
    rows = body["sheets"]
    assert [x["ticker"] for x in rows] == ["AMGN", "GILD"]
    assert rows[0]["baseline_verdict"] == "buy_zone"  # newest AMGN row wins


def test_get_one_and_404(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/api/valuation-bands/amgn")
    assert r.status_code == 200 and r.json()["ticker"] == "AMGN"
    assert client.get("/api/valuation-bands/ZZZZ").status_code == 404


def test_detail_carries_the_frozen_peer_group_members(monkeypatch):
    # The Valuation tab's per-name detail names the peers behind the multiple.
    # Members are derived read-side from the frozen group map -- the same map
    # the engine froze -- never stored on the sheet.
    from tradehub.api.dependencies import get_supabase as real_get_supabase
    rows = [{"ticker": "AMGN", "tier": "watch", "status": "banded",
             "band_basis": "eps", "peer_group": "biotechnology",
             "peer_basis": "industry_group", "peer_count": 7,
             "baseline_verdict": "short_zone_strong",
             "computed_at": "2026-11-09T18:00:00Z",
             "bands": {"bear": 272.18, "base": 310.17, "bull": 317.92}}]
    main.app.dependency_overrides[admin.require_admin] = (
        lambda: {"email": "k@example.com", "is_admin": True})
    main.app.dependency_overrides[real_get_supabase] = lambda: _Supa(rows)
    client = TestClient(main.app)
    body = client.get("/api/valuation-bands/AMGN").json()
    assert body["peer_members"] == ["ABBV", "AMGN", "BIIB", "GILD", "INCY",
                                    "MRNA", "REGN", "VRTX"]


def test_detail_peer_members_sector_fallback_and_unknown(monkeypatch):
    from tradehub.api.dependencies import get_supabase as real_get_supabase
    main.app.dependency_overrides[admin.require_admin] = (
        lambda: {"email": "k@example.com", "is_admin": True})
    rows = [{"ticker": "NBIS", "tier": "open", "status": "banded",
             "band_basis": "eps", "peer_group": "sector:Health Care",
             "peer_basis": "sector_fallback", "peer_count": 40,
             "baseline_verdict": "neutral",
             "computed_at": "2026-11-09T18:00:00Z", "bands": None},
            {"ticker": "ZZZZ", "tier": "open", "status": "no_full_year_guide",
             "band_basis": "eps", "peer_group": None, "peer_basis": None,
             "peer_count": None, "baseline_verdict": "no_bands",
             "computed_at": "2026-11-09T18:00:00Z", "bands": None}]
    main.app.dependency_overrides[real_get_supabase] = lambda: _Supa(rows)
    client = TestClient(main.app)
    nbis = client.get("/api/valuation-bands/NBIS").json()
    assert "AMGN" in nbis["peer_members"] and len(nbis["peer_members"]) > 20
    zzzz = client.get("/api/valuation-bands/ZZZZ").json()
    assert zzzz["peer_members"] == []


def test_list_rows_do_not_grow_peer_members(monkeypatch):
    # The list stays the stored rows verbatim; members are a detail-only cost.
    client = _client(monkeypatch)
    rows = client.get("/api/valuation-bands").json()
    assert all("peer_members" not in r for r in rows)


def test_revenue_basis_row_surfaces_its_basis(monkeypatch):
    # Phase B: a revenue-basis sheet is labeled wherever bands are shown --
    # the read API returns the stored basis and implied revenue verbatim.
    from tradehub.api.dependencies import get_supabase as real_get_supabase
    rows = [{"ticker": "GILD", "tier": "watch", "status": "banded",
             "band_basis": "revenue", "implied_revenue": 31.5e9,
             "implied_eps": None, "baseline_verdict": "neutral",
             "computed_at": "2026-11-09T18:00:00Z",
             "bands": {"bear": 150.0, "base": 170.0, "bull": 175.0}}]
    main.app.dependency_overrides[admin.require_admin] = (
        lambda: {"email": "k@example.com", "is_admin": True})
    main.app.dependency_overrides[real_get_supabase] = lambda: _Supa(rows)
    client = TestClient(main.app)
    r = client.get("/api/valuation-bands/GILD")
    assert r.status_code == 200
    body = r.json()
    assert body["band_basis"] == "revenue"
    assert body["implied_revenue"] == 31.5e9
    assert body["implied_eps"] is None
