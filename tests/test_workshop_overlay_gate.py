"""The overlay battery (spec 2026-11-08, amendment): a sleeve graded only in
combination — the run's benchmark blended with the sleeve at a frozen 20%
weight, judged on drawdown margin, a Sharpe guard and a return budget, per
span. Standalone return is never a leg."""

import numpy as np

from tradehub.workshop import overlay_gate

N = 4000
SPLIT = 2800


def _host(seed=31):
    return np.random.default_rng(seed).normal(0.0003, 0.01, N)


def _hedge(host, seed=32):
    """A counter-moving sleeve: rises when the host falls, modest drift of its own."""
    rng = np.random.default_rng(seed)
    return 0.0005 - 0.3 * (host - 0.0003) + rng.normal(0, 0.002, N)


def test_battery_passes_a_sleeve_that_cushions_the_fall():
    host = _host()
    out = overlay_gate.battery(_hedge(host), host, split=SPLIT)
    assert out["type"] == "overlay" and out["verdict"] == "PASS", out["legs"]
    for name in ("built", "unseen"):
        st = out["spans"][name]
        assert st["dd_margin"] >= overlay_gate.DD_MARGIN_PP
        assert st["combined"]["max_dd"] > st["host"]["max_dd"]  # a shallower hole (less negative)
        assert st["cagr_giveback"] <= overlay_gate.RETURN_BUDGET_PP


def test_battery_fails_the_host_itself_as_a_sleeve():
    host = _host(33)
    out = overlay_gate.battery(host.copy(), host, split=SPLIT)
    assert out["verdict"] == "FAIL"  # blended with itself, the portfolio falls exactly as far
    legs = {leg["name"]: leg for leg in out["legs"]}
    assert legs["dd_built"]["holds"] is False and legs["dd_unseen"]["holds"] is False
    assert abs(out["spans"]["unseen"]["dd_margin"]) < 1e-9


def test_battery_fails_when_protection_costs_too_much_return():
    host = _host(34)
    rng = np.random.default_rng(35)
    sleeve = -0.0015 + rng.normal(0, 0.002, N)  # bleeds ~30%/yr but barely moves: it cushions, at a price
    out = overlay_gate.battery(sleeve, host, split=SPLIT)
    assert out["verdict"] == "FAIL"
    legs = {leg["name"]: leg for leg in out["legs"]}
    assert legs["budget_unseen"]["holds"] is False
    assert out["spans"]["unseen"]["cagr_giveback"] > overlay_gate.RETURN_BUDGET_PP


def test_drawdown_leg_is_not_binding_when_nothing_fell():
    rng = np.random.default_rng(36)
    host = rng.normal(0.001, 0.002, N)  # a calm, rising host: no fall to protect against
    out = overlay_gate.battery(host.copy(), host, split=SPLIT)
    for name in ("built", "unseen"):
        st = out["spans"][name]
        assert st["dd_binding"] is False and abs(st["dd_margin"]) < 1e-9
    legs = {leg["name"]: leg for leg in out["legs"]}
    assert legs["dd_built"]["holds"] is True and legs["dd_unseen"]["holds"] is True


def test_span_stats_blend_at_the_frozen_weight():
    host = _host(37)
    sleeve = _hedge(host, 38)
    st = overlay_gate.span_stats(sleeve, host)
    w = overlay_gate.SLEEVE_WEIGHT
    combined = (1 - w) * host + w * sleeve
    assert st["weight"] == w == 0.20
    assert abs(st["combined"]["cagr"] - overlay_gate._cagr(combined)) < 1e-9
    assert st["sharpe_delta"] == st["combined"]["sharpe"] - st["host"]["sharpe"]
