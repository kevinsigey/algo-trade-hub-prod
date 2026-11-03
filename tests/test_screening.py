"""Screening engine (Part A of Kevin's 2026-11-02 package): spec validation
names its offenders, derived ratios compose catalog fields and are usable in
filters/scores, the runner discloses the universe cap, and the API serves the
catalog + a run. The data layer is faked at the registry: two synthetic field
functions stand in for yfinance so the pipeline runs offline."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tradehub.api import main
from tradehub.screening import runner
from tradehub.screening.functions import REGISTRY
from tradehub.screening.spec import SpecError, validate_spec

BASE = {"name": "t", "universe": {"type": "list", "tickers": ["AAA", "BBB", "CCC"]}}


@pytest.fixture
def fake_fields(monkeypatch):
    def num_field(values):
        def fn(store, tickers, **params):
            return pd.Series({t: values.get(t) for t in tickers}, dtype=float)
        return fn

    saved = dict(REGISTRY)
    REGISTRY["fake_alpha"] = {"fn": num_field({"AAA": 10.0, "BBB": 4.0, "CCC": None}),
                              "kind": "field", "returns": "float", "params": {},
                              "source": "test", "category": "test", "doc": "fake"}
    REGISTRY["fake_beta"] = {"fn": num_field({"AAA": 2.0, "BBB": 2.0, "CCC": 1.0}),
                             "kind": "field", "returns": "float", "params": {},
                             "source": "test", "category": "test", "doc": "fake"}
    yield
    REGISTRY.clear()
    REGISTRY.update(saved)


def test_validation_names_an_unknown_function():
    with pytest.raises(SpecError, match="unknown function 'nope'"):
        validate_spec({**BASE, "filters": [{"fn": "nope", "op": "gt", "value": 1}]})


def test_derived_validation_rejects_unknown_refs_and_collisions():
    with pytest.raises(SpecError, match="unknown field 'ghost'"):
        validate_spec({**BASE, "derived": [{"name": "r", "expr": "fcf_yield / ghost"}]})
    with pytest.raises(SpecError, match="collides"):
        validate_spec({**BASE, "derived": [{"name": "pe_ratio", "expr": "1 / 2"}]})
    with pytest.raises(SpecError, match="only"):
        validate_spec({**BASE, "derived": [{"name": "r", "expr": "fcf_yield ** 2"}]})


def test_run_computes_a_derived_ratio_and_filters_on_it(fake_fields):
    spec = {**BASE,
            "derived": [{"name": "alpha_per_beta", "expr": "fake_alpha / fake_beta"}],
            "filters": [{"fn": "alpha_per_beta", "op": "gt", "value": 3}],
            "score": [{"fn": "alpha_per_beta", "weight": 1}]}
    result = runner.run_spec(spec, store=SimpleNamespace(asof={}, missing=[]))
    rows = result.table.to_dict("records")
    assert [r["ticker"] for r in rows] == ["AAA"]  # 10/2=5 passes; 4/2=2 fails; CCC is missing -> fails, never zero
    assert rows[0]["alpha_per_beta"] == 5.0
    assert result.footer["columns"]["alpha_per_beta"]["source"] == "derived: fake_alpha / fake_beta"


def test_run_discloses_the_universe_cap(fake_fields, monkeypatch):
    monkeypatch.setattr(runner, "MAX_UNIVERSE", 2)
    spec = {**BASE, "filters": [{"fn": "fake_beta", "op": "gt", "value": 0}]}
    result = runner.run_spec(spec, store=SimpleNamespace(asof={}, missing=[]))
    assert result.footer["universe_size"] == 2
    assert result.footer["universe_capped"] == {"cap": 2, "universe_size_full": 3}


def test_catalog_and_run_endpoints(monkeypatch):
    monkeypatch.setitem(main.app.dependency_overrides, main.admin.require_admin, lambda: {"email": "k@example.com"})
    client = TestClient(main.app)
    catalog = client.get("/api/screening/catalog")
    assert catalog.status_code == 200
    names = {f["name"] for f in catalog.json()["functions"]}
    assert len(names) >= 43 and "pe_ratio" in names
    bad = client.post("/api/screening/run", json={"spec": {**BASE, "filters": [{"fn": "nope", "op": "gt", "value": 1}]}})
    assert bad.status_code == 422 and "nope" in bad.json()["detail"]


def test_translate_validates_the_models_spec(monkeypatch):
    from tradehub.screening import translate as tr

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    good = {"name": "t", "universe": {"type": "list", "tickers": ["AAA"]},
            "filters": [{"fn": "pe_ratio", "op": "lt", "value": 12}]}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"model": "x/y:free", "choices": [{"message": {"content": "Here you go:\n" + json.dumps(good)}}]}

    spec, model = tr.translate("cheap stocks", post=lambda *a, **k: Resp())
    assert spec == good and model == "x/y:free"
    bad = {"name": "t", "universe": {"type": "list", "tickers": ["AAA"]},
           "filters": [{"fn": "nope", "op": "lt", "value": 1}]}

    class BadResp(Resp):
        def json(self):
            return {"model": "x/y:free", "choices": [{"message": {"content": json.dumps(bad)}}]}

    with pytest.raises(tr.TranslateUnavailable, match="nope"):
        tr.translate("???", post=lambda *a, **k: BadResp())


def test_catalog_endpoint_carries_the_filter_cards():
    from fastapi.testclient import TestClient

    from tradehub.api import main

    body = TestClient(main.app).get("/api/screening/catalog").json()
    assert len(body["cards"]) >= 30
    mom = next(c for c in body["cards"] if c["id"] == "mom6")
    assert mom["fn"] == "momentum" and mom["preset"] == {"op": "pct_gte", "value": 75}
