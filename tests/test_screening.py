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


def test_run_has_no_default_universe_cap(fake_fields):
    # Universe expansion (Nov 2026): the old 300-name default cap is gone --
    # a spec without max_universe evaluates its full universe, and the
    # footer's evaluation block accounts for every name.
    spec = {**BASE, "filters": [{"fn": "fake_beta", "op": "gt", "value": 0}]}
    result = runner.run_spec(spec, store=SimpleNamespace(asof={}, missing=[]))
    assert result.footer["universe_size"] == 3
    assert "universe_capped" not in result.footer
    ev = result.footer["evaluation"]
    assert ev["universe_total"] == 3 and ev["evaluated_count"] == 3
    assert ev["not_evaluated"] == [] and ev["not_evaluated_count"] == 0
    assert result.footer["universe_total"] == 3
    assert result.footer["evaluated_count"] == 3


def test_spec_cap_names_every_dropped_name_as_not_evaluated(fake_fields):
    spec = {**BASE, "max_universe": 2,
            "filters": [{"fn": "fake_beta", "op": "gt", "value": 0}]}
    result = runner.run_spec(spec, store=SimpleNamespace(asof={}, missing=[]))
    assert result.footer["universe_size"] == 2
    assert result.footer["universe_capped"] == {"cap": 2, "universe_size_full": 3}
    ev = result.footer["evaluation"]
    assert ev["evaluated_count"] == 2 and ev["not_evaluated_count"] == 1
    assert [n["ticker"] for n in ev["not_evaluated"]] == ["CCC"]
    assert "max_universe" in ev["not_evaluated"][0]["reason"]


def test_evaluation_block_groups_missing_fields_by_name(fake_fields):
    # A getter's missing note (seeded here the way the data layer records
    # it) lands in the per-name status block, counted per field.
    missing = [{"ticker": "CCC", "field": "fake_alpha", "reason": "no data"},
               {"ticker": "CCC", "field": "fake_beta", "reason": "no data"},
               {"ticker": "BBB", "field": "fake_alpha", "reason": "no data"},
               {"ticker": "BBB", "field": "unrelated_fn", "reason": "not used"}]
    spec = {**BASE, "filters": [{"fn": "fake_alpha", "op": "gt", "value": 0},
                                {"fn": "fake_beta", "op": "gt", "value": 0}]}
    result = runner.run_spec(spec, store=SimpleNamespace(asof={}, missing=missing))
    ev = result.footer["evaluation"]
    assert ev["missing_fields"] == {"BBB": ["fake_alpha"],
                                    "CCC": ["fake_alpha", "fake_beta"]}
    assert ev["missing_field_counts"] == {"fake_alpha": 2, "fake_beta": 1}
    assert ev["evaluated_count"] == 3  # missing data is evaluated, not dropped


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

    spec, model, notes = tr.translate("cheap stocks", post=lambda *a, **k: Resp())
    assert spec == good and model == "x/y:free" and notes == []
    bad = {"name": "t", "universe": {"type": "list", "tickers": ["AAA"]},
           "filters": [{"fn": "nope", "op": "lt", "value": 1}]}

    class BadResp(Resp):
        def json(self):
            return {"model": "x/y:free", "choices": [{"message": {"content": json.dumps(bad)}}]}

    # Nov 2026: an invalid AI spec no longer dead-ends when the rules can
    # read the query -- the rules spec is served WITH the refusal disclosed
    # in the notes (never a silent fix-up). A query the rules cannot read
    # still raises (test_screening_translate.py covers that path).
    spec2, model2, notes2 = tr.translate("cheap stocks", post=lambda *a, **k: BadResp())
    assert model2.startswith("rules") and spec2["filters"]
    assert any("refused" in n and "nope" in n for n in notes2)
    with pytest.raises(tr.TranslateUnavailable, match="nope"):
        tr.translate("???", post=lambda *a, **k: BadResp())


def test_catalog_endpoint_carries_the_filter_cards():
    from fastapi.testclient import TestClient

    from tradehub.api import main

    body = TestClient(main.app).get("/api/screening/catalog").json()
    assert len(body["cards"]) >= 30
    mom = next(c for c in body["cards"] if c["id"] == "mom6")
    assert mom["fn"] == "momentum" and mom["preset"] == {"op": "pct_gte", "value": 75}
