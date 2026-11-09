"""Store mapping for fact sheets (Phase B): the band basis and the implied
revenue ride into valuation_fact_sheets; EPS rows keep implied_eps only."""
from tradehub.valuation import store


class _Resp:
    def __init__(self, data):
        self.data = data


class _Insert:
    def __init__(self, sink):
        self._sink = sink

    def insert(self, row):
        self._sink.append(row)
        return self

    def execute(self):
        return _Resp([])


class _Client:
    def __init__(self):
        self.rows = []

    def table(self, _name):
        return _Insert(self.rows)


def _sheet(**over):
    base = {"ticker": "GILD", "tier": "watch", "status": "banded",
            "price": 168.5, "price_as_of": "2026-11-06",
            "peer_group": "biotechnology", "peer_multiple": 7.1,
            "peer_count": 8, "peer_basis": "industry_group",
            "anchor": {"metric": "revenue"}, "bands": {"bear": 1, "base": 2, "bull": 3},
            "implied": {"revenue": 31.5e9, "vs_guide": "inside"},
            "gap_range_widths": 0.4, "guidance_percentile": None,
            "baseline_verdict": "neutral", "stale": False,
            "falsifier": "x", "directions": {}, "fundamentals": {},
            "inputs": {}, "band_basis": "revenue"}
    base.update(over)
    return base


def test_insert_sheet_maps_revenue_basis():
    client = _Client()
    store.insert_sheet(client, _sheet())
    [row] = client.rows
    assert row["band_basis"] == "revenue"
    assert row["implied_revenue"] == 31.5e9
    assert row["implied_eps"] is None


def test_insert_sheet_defaults_to_eps_basis():
    client = _Client()
    sheet = _sheet(implied={"eps": 9.4, "vs_guide": "above"})
    del sheet["band_basis"]
    store.insert_sheet(client, sheet)
    [row] = client.rows
    assert row["band_basis"] == "eps"
    assert row["implied_eps"] == 9.4
    assert row["implied_revenue"] is None
