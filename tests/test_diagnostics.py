"""The diagnostics pack (§6.1): the three tests must read known processes the way
the textbooks say -- white noise stationary and clean, a random walk
non-stationary, clustered volatility ARCH-flagged, an AR(1) Ljung-Box-flagged --
and the feature screen must catch a mostly-zero feature, the ghost failure mode."""
from __future__ import annotations

import numpy as np

from tradehub.diagnostics import adf_test, arch_lm, feature_diagnostics, ljung_box, residual_diagnostics

RNG = np.random.default_rng(20261101)
WHITE = RNG.normal(0, 1, 400)
WALK = np.cumsum(RNG.normal(0, 1, 400))


def _garch(n: int = 600) -> np.ndarray:
    rng = np.random.default_rng(7)
    e, var = np.zeros(n), 0.5
    for t in range(n):
        var = 0.05 + 0.85 * var + 0.1 * (e[t - 1] ** 2 if t else 0.0)
        e[t] = rng.normal(0, np.sqrt(var))
    return e


def test_adf_reads_white_noise_stationary_and_a_random_walk_not():
    assert adf_test(WHITE)["verdict"] == "stationary"
    assert adf_test(WALK)["verdict"] == "non_stationary"


def test_adf_declines_a_short_series_instead_of_guessing():
    assert adf_test([1.0, 2.0, 1.5]) == {"n": 3, "status": "too_short"}


def test_ljung_box_flags_autocorrelated_residuals_only():
    ar1 = np.zeros(400)
    for t in range(1, 400):
        ar1[t] = 0.6 * ar1[t - 1] + RNG.normal(0, 1)
    assert ljung_box(ar1)["flag"] is True
    assert ljung_box(WHITE)["flag"] is False


def test_arch_lm_flags_clustered_volatility_only():
    assert arch_lm(_garch())["flag"] is True
    assert arch_lm(WHITE)["flag"] is False


def test_feature_diagnostics_catches_a_mostly_zero_feature():
    rows = feature_diagnostics({
        "healthy": list(WHITE[:120]),
        "ghost_like": [0.0] * 115 + [1.0, 2.0, 1.0, 3.0, 2.0],
        "walk_feature": list(WALK[:120]),
    })
    by_name = {r["feature"]: r for r in rows}
    assert by_name["healthy"]["flags"] == []
    assert by_name["ghost_like"]["flags"] == ["mostly_zero"]
    assert by_name["ghost_like"]["zero_share"] >= 0.9
    assert by_name["walk_feature"]["flags"] == ["non_stationary"]


def test_residual_diagnostics_lifts_flags_to_the_top():
    clean = residual_diagnostics(list(WHITE))
    assert clean["flags"] == [] and clean["n"] == 400
    dirty = residual_diagnostics(list(_garch()))
    assert "residual_arch" in dirty["flags"]


def test_current_runs_carries_diagnostics_through_untouched():
    from tradehub.scoreboard import current_runs
    diag = {"features": [{"feature": "x", "flags": ["mostly_zero"]}], "residuals": {"flags": []}}
    rows = current_runs([{"engine": "labor_nowcast", "engine_version": "labor-v1", "mode": "taker",
                          "created_at": "2026-11-01T00:00:00Z", "diagnostics": diag}])
    assert rows[0]["diagnostics"] == diag
    rows = current_runs([{"engine": "labor_nowcast", "engine_version": "labor-v1", "mode": "taker",
                          "created_at": "2026-11-01T00:00:00Z"}])
    assert rows[0]["diagnostics"] is None  # unmeasured reads as absent, never as clean data


def test_health_report_carries_diagnostics_without_touching_problems():
    from datetime import datetime, timezone
    from tradehub.health import build_health_report
    base = dict(timers={}, frozen_by_family={}, cadences={}, orderbook_age_seconds=None,
                now=datetime(2026, 11, 1, tzinfo=timezone.utc), untracked=frozenset())
    clean = build_health_report(**base)
    assert clean["diagnostics"] is None
    flagged = build_health_report(**base, diagnostics={"engine": "labor_nowcast", "feature_flags": ["ghost: mostly_zero"],
                                                        "residual_flags": []})
    assert flagged["diagnostics"]["feature_flags"] == ["ghost: mostly_zero"]
    # Flags are not gates: the flagged report's status and problems are exactly
    # the clean report's -- diagnostics changed nothing but their own section.
    assert flagged["problems"] == clean["problems"] and flagged["status"] == clean["status"]
