"""Claim-typed gates (spec 2026-11-08): the spec carries claim_type, the gate
dispatches on it, the basket battery grades allocations relatively, and the
registry leaves battery verdicts as stored (grandfathering)."""

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from tradehub.workshop import registry
from tradehub.workshop.engine import run_test
from tradehub.workshop.spec import IdeaSpec, blank_spec

N = 5000
IDX = pd.bdate_range("2006-01-03", periods=N)


def prices(returns: np.ndarray) -> np.ndarray:
    return 100 * np.cumprod(1 + returns)


def market(seed=0):
    rng = np.random.default_rng(seed)
    spy = rng.normal(0.0003, 0.01, N)
    frame = {"SPY": prices(spy),
             "QQQ": prices(spy * 1.2 + rng.normal(0, 0.004, N)),
             "IWM": prices(spy * 1.1 + rng.normal(0, 0.005, N))}
    return rng, spy, frame


def basket_spec(**over):
    base = {"title": "Two-name basket vs SPY", "hold": ["AAA", "BBB"], "claim": "beats_benchmark",
            "claim_type": "basket", "benchmark": "SPY"}
    return IdeaSpec.model_validate({**base, **over})


def closes_with(leg_returns: dict[str, np.ndarray], seed=0):
    _, _, frame = market(seed)
    return pd.DataFrame({**frame, **{t: prices(r) for t, r in leg_returns.items()}}, index=IDX)


# ── the field itself ─────────────────────────────────────────────────────────

def test_claim_type_defaults_to_timing_and_round_trips():
    s = IdeaSpec.model_validate({"title": "Plain timing idea", "hold": ["GLD"], "claim": "beats_benchmark"})
    assert s.claim_type == "timing"
    assert s.model_dump(mode="json")["claim_type"] == "timing"
    b = basket_spec()
    assert b.claim_type == "basket" and b.model_dump(mode="json")["claim_type"] == "basket"
    assert blank_spec()["claim_type"] == "timing"


def test_basket_rejects_a_timing_claim_in_allocation_clothes():
    with pytest.raises(ValidationError):  # an enter rule makes it a timing claim
        basket_spec(rules={"enter": {"mode": "all", "conditions": [
            {"source": "price", "series": "AAA", "measure": "vs_sma", "op": ">", "threshold": 0.0}]}})
    with pytest.raises(ValidationError):  # the allocation claim is beats_benchmark
        basket_spec(claim="ballast")
    with pytest.raises(ValidationError):  # option legs are model-priced timing claims in this pass
        basket_spec(options=[{"underlying": "AAA", "kind": "call", "side": "buy"}])


def test_event_and_overlay_are_storable_declarations():
    for ct in ("event", "overlay"):
        s = IdeaSpec.model_validate({"title": f"A {ct} declaration", "hold": ["GLD"],
                                     "claim": "beats_benchmark", "claim_type": ct})
        assert s.claim_type == ct


def test_design_only_types_are_refused_by_the_gate():
    s = IdeaSpec.model_validate({"title": "An event declaration", "hold": ["GLD"],
                                 "claim": "beats_benchmark", "claim_type": "event"})
    _, _, frame = market(4)
    closes = pd.DataFrame({**frame, "GLD": frame["SPY"]}, index=IDX)
    with pytest.raises(ValueError, match="design-only"):
        run_test(s, closes, {}, variations=1, seed=7)


# ── dispatch through run_test ────────────────────────────────────────────────

def test_basket_run_grades_relatively_and_passes_a_real_allocation():
    rng, spy, _ = market(21)
    legs = {t: spy + 0.0012 + rng.normal(0, 0.002, N) for t in ("AAA", "BBB")}
    out = run_test(basket_spec(), closes_with(legs, 21), {}, variations=1, seed=7)
    assert out["verdict"] == "PASS", out["battery"]["legs"]
    assert out["claim_type"] == "basket" and out["battery"]["type"] == "basket"
    assert out["shuffle"] is None and out["t_test"] is None  # neither was run; the record says so
    assert out["battery"]["spans"]["unseen"]["ci_low"] > 0
    assert out["claim"]["unseen"]["holds"]  # the excess-CAGR read agrees


def test_basket_run_fails_when_the_hole_is_too_deep():
    rng, spy, _ = market(22)
    legs = {t: spy + 0.0012 + rng.normal(0, 0.001, N) for t in ("AAA", "BBB")}
    wealth = np.cumprod(1 + spy)
    trough = int(np.argmin(wealth / np.maximum.accumulate(wealth)))
    peak = int(np.argmax(wealth[:trough + 1]))
    for t in legs:  # in SPY's worst slide the basket falls more than twice as far
        legs[t][peak:trough + 1] = spy[peak:trough + 1] * 2.2 + 0.0005
    out = run_test(basket_spec(), closes_with(legs, 22), {}, variations=1, seed=7)
    assert out["verdict"] == "FAIL"
    legs_out = {leg["name"]: leg for leg in out["battery"]["legs"]}
    assert not (legs_out["dd_built"]["holds"] and legs_out["dd_unseen"]["holds"])
    assert "deeper hole" in out["headline"]


def test_basket_run_fails_on_noise():
    rng, spy, _ = market(23)
    legs = {t: rng.normal(0.0003, 0.01, N) for t in ("AAA", "BBB")}
    out = run_test(basket_spec(), closes_with(legs, 23), {}, variations=1, seed=7)
    assert out["verdict"] == "FAIL"
    assert out["battery"]["spans"]["unseen"]["ci_low"] < 0 < out["battery"]["spans"]["unseen"]["ci_high"]


def test_basket_run_still_needs_unseen_years():
    rng = np.random.default_rng(24)
    spy = rng.normal(0.0003, 0.01, 900)
    idx = pd.bdate_range("2023-01-02", periods=900)
    frame = {"SPY": prices(spy), "QQQ": prices(spy), "IWM": prices(spy)}
    legs = {t: prices(spy + 0.0012 + rng.normal(0, 0.002, 900)) for t in ("AAA", "BBB")}
    closes = pd.DataFrame({**frame, **legs}, index=idx)
    out = run_test(basket_spec(), closes, {}, variations=1, seed=7)
    assert out["verdict"] == "NOT ENOUGH DATA"  # 270 unseen days < 504, whichever battery


def test_timing_run_is_untouched_by_the_dispatch():
    rng, spy, _ = market(25)
    s = IdeaSpec.model_validate({"title": "Plain hold", "hold": ["AAA"], "claim": "beats_benchmark"})
    closes = closes_with({"AAA": spy + rng.normal(0, 0.004, N)}, 25)
    out = run_test(s, closes, {}, variations=1, seed=7)
    assert "battery" not in out and out["shuffle"] is not None


def test_ew_reference_is_na_for_the_equal_weight_basket_itself():
    rng, spy, _ = market(26)
    legs = {t: spy + 0.0012 + rng.normal(0, 0.002, N) for t in ("AAA", "BBB")}
    out = run_test(basket_spec(), closes_with(legs, 26), {}, variations=1, seed=7)
    # AAA+BBB held once each, no shorts, no blend: the idea IS the equal-weight basket.
    assert out["battery"]["ew_reference"] is None


def test_ew_reference_present_for_a_slot_weighted_basket():
    rng, spy, _ = market(27)
    legs = {"AAA": spy + 0.0024 + rng.normal(0, 0.002, N),  # the strong leg, overweighted by the slots
            "BBB": spy + 0.0006 + rng.normal(0, 0.002, N)}
    s = basket_spec(hold=["AAA", "AAA", "BBB"])  # slots: AAA counts twice (idea 69's construct)
    out = run_test(s, closes_with(legs, 27), {}, variations=1, seed=7)
    ew = out["battery"]["ew_reference"]
    assert ew is not None and ew["spans"]["unseen"]["excess_cagr"] > 0


# ── grandfathering in the registry's adjusted view ───────────────────────────

def _run_row(verdict, result):
    return {"verdict": verdict, "result": result}


def test_registry_leaves_battery_verdicts_as_stored():
    basket_run = _run_row("PASS", {"shuffle": None, "battery": {"type": "basket"},
                                   "walk_forward": {"held": 0, "of": 4, "folds": []}})
    out = registry.adjusted({69: basket_run})
    assert out[69]["verdict_now"] == "PASS"  # no shuffle p, no demotion: reported, not applied


def test_registry_still_demotes_a_timing_pass_that_fails_its_bars():
    timing_run = _run_row("PASS", {"shuffle": {"p": 0.5}, "walk_forward": {"held": 4, "of": 4, "folds": []}})
    out = registry.adjusted({1: timing_run})
    assert out[1]["verdict_now"] == "FAIL"


# ── the run endpoint refuses design-only types before any data loads ─────────

def test_run_endpoint_refuses_design_only_claim_types(monkeypatch):
    from fastapi.testclient import TestClient

    from tradehub.api import admin, main
    from tradehub.api.dependencies import get_supabase
    from workshop_fake import DB

    db = DB()
    main.app.dependency_overrides[get_supabase] = lambda: db
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    monkeypatch.setattr(main, "run_test", lambda *a, **k: pytest.fail("the gate must not run"))
    try:
        c = TestClient(main.app, raise_server_exceptions=False)
        idea = c.post("/api/workshop/ideas", json={"title": "Event idea", "plain_words": "x"}).json()
        spec = {"title": "An event declaration", "hold": ["GLD"], "claim": "beats_benchmark",
                "claim_type": "event"}
        r = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": spec})
        assert r.status_code == 422 and "design-only" in r.json()["detail"]
    finally:
        main.app.dependency_overrides.clear()
